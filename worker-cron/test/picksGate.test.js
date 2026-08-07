import { describe, it, expect } from 'vitest';
import { findEodRun, isTerminalTick, evaluatePicksGate, PICKS_GATE_WINDOW_MINUTES } from '../src/picksGate.js';
import { JOB_SCHEDULE } from '../src/routing.js';

const picksJob = JOB_SCHEDULE.find((j) => j.name === 'picks');
const etNow = (hour, minute, dateStr = '2026-07-15') => ({ hour, minute, weekday: 3, dateStr });

describe('picksJob wiring', () => {
  it('is gated with the picks gate window', () => {
    expect(picksJob.gated).toBe(true);
    expect(picksJob.windowMinutes).toBe(PICKS_GATE_WINDOW_MINUTES);
    expect(picksJob.hour).toBe(17);
    expect(picksJob.minute).toBe(0);
  });
});

describe('findEodRun — disambiguating the EOD run from earlier same-day runs', () => {
  it('picks the earliest run created at/after the dispatch timestamp', () => {
    const runs = [
      { created_at: '2026-07-15T19:50:05Z', status: 'completed', conclusion: 'success' }, // pre-close run
      { created_at: '2026-07-15T21:00:03Z', status: 'completed', conclusion: 'success' }, // EOD run
    ];
    const eodRun = findEodRun(runs, '2026-07-15T21:00:00.000Z');
    expect(eodRun.created_at).toBe('2026-07-15T21:00:03Z');
  });

  it('allows a small clock-skew tolerance before the dispatch timestamp', () => {
    const runs = [{ created_at: '2026-07-15T20:59:35Z', status: 'completed', conclusion: 'success' }];
    const eodRun = findEodRun(runs, '2026-07-15T21:00:00.000Z');
    expect(eodRun).not.toBeNull();
  });

  it('ignores a run older than the tolerance window (the pre-close run)', () => {
    const runs = [{ created_at: '2026-07-15T19:50:05Z', status: 'completed', conclusion: 'success' }];
    const eodRun = findEodRun(runs, '2026-07-15T21:00:00.000Z');
    expect(eodRun).toBeNull();
  });

  it('returns null for an empty or missing run list', () => {
    expect(findEodRun([], '2026-07-15T21:00:00.000Z')).toBeNull();
    expect(findEodRun(null, '2026-07-15T21:00:00.000Z')).toBeNull();
  });

  it('returns null when dispatchTs is missing', () => {
    const runs = [{ created_at: '2026-07-15T21:00:03Z', status: 'completed', conclusion: 'success' }];
    expect(findEodRun(runs, null)).toBeNull();
  });
});

describe('isTerminalTick', () => {
  it('is false well inside the window', () => {
    expect(isTerminalTick(picksJob, etNow(17, 30))).toBe(false);
  });

  it('is true on the last 5-minute tick before the window closes', () => {
    // window: 17:00 + 120min = 19:00; the tick at 18:55 is the last one
    // whose next tick (19:00) would fall outside the window.
    expect(isTerminalTick(picksJob, etNow(18, 55))).toBe(true);
  });

  it('is false one tick earlier (18:50, next tick 18:55 still inside)', () => {
    expect(isTerminalTick(picksJob, etNow(18, 50))).toBe(false);
  });
});

describe('evaluatePicksGate', () => {
  it('waits when collect_eod has not been dispatched today at all', () => {
    const { outcome, reason } = evaluatePicksGate({
      job: picksJob,
      etNow: etNow(17, 5),
      collectEodDispatch: null,
      eodRun: null,
      fetchError: null,
    });
    expect(outcome).toBe('waiting');
    expect(reason).toBe('collect_eod_not_dispatched');
  });

  it('waits when the collect_eod dispatch record is for a prior date', () => {
    const { outcome, reason } = evaluatePicksGate({
      job: picksJob,
      etNow: etNow(17, 5),
      collectEodDispatch: { ok: true, etDate: '2026-07-14', ts: '2026-07-14T21:00:00.000Z' },
      eodRun: null,
      fetchError: null,
    });
    expect(outcome).toBe('waiting');
    expect(reason).toBe('collect_eod_not_dispatched');
  });

  it('waits when collect_eod dispatch itself failed (ok: false)', () => {
    const { outcome, reason } = evaluatePicksGate({
      job: picksJob,
      etNow: etNow(17, 5),
      collectEodDispatch: { ok: false, etDate: '2026-07-15', ts: '2026-07-15T21:00:00.000Z' },
      eodRun: null,
      fetchError: null,
    });
    expect(outcome).toBe('waiting');
    expect(reason).toBe('collect_eod_not_dispatched');
  });

  it('waits when the run-status fetch itself failed (never dispatches on an unverifiable read)', () => {
    const { outcome, reason } = evaluatePicksGate({
      job: picksJob,
      etNow: etNow(17, 10),
      collectEodDispatch: { ok: true, etDate: '2026-07-15', ts: '2026-07-15T21:00:00.000Z' },
      eodRun: null,
      fetchError: 'github_403',
    });
    expect(outcome).toBe('waiting');
    expect(reason).toBe('run_status_fetch_failed:github_403');
  });

  it('waits when no matching run is found yet', () => {
    const { outcome, reason } = evaluatePicksGate({
      job: picksJob,
      etNow: etNow(17, 5),
      collectEodDispatch: { ok: true, etDate: '2026-07-15', ts: '2026-07-15T21:00:00.000Z' },
      eodRun: null,
      fetchError: null,
    });
    expect(outcome).toBe('waiting');
    expect(reason).toBe('eod_run_not_found');
  });

  it('waits while the matched run is still in progress', () => {
    const { outcome, reason } = evaluatePicksGate({
      job: picksJob,
      etNow: etNow(17, 10),
      collectEodDispatch: { ok: true, etDate: '2026-07-15', ts: '2026-07-15T21:00:00.000Z' },
      eodRun: { status: 'in_progress', conclusion: null },
      fetchError: null,
    });
    expect(outcome).toBe('waiting');
    expect(reason).toBe('eod_run_in_progress');
  });

  it('dispatches once the matched run completed successfully', () => {
    const { outcome, reason } = evaluatePicksGate({
      job: picksJob,
      etNow: etNow(17, 10),
      collectEodDispatch: { ok: true, etDate: '2026-07-15', ts: '2026-07-15T21:00:00.000Z' },
      eodRun: { status: 'completed', conclusion: 'success' },
      fetchError: null,
    });
    expect(outcome).toBe('dispatch');
    expect(reason).toBe('eod_run_success');
  });

  it('records the failure reason when the run completed but failed, mid-window (waiting, not miss)', () => {
    const { outcome, reason } = evaluatePicksGate({
      job: picksJob,
      etNow: etNow(17, 15),
      collectEodDispatch: { ok: true, etDate: '2026-07-15', ts: '2026-07-15T21:00:00.000Z' },
      eodRun: { status: 'completed', conclusion: 'failure' },
      fetchError: null,
    });
    expect(outcome).toBe('waiting');
    expect(reason).toBe('eod_run_failure');
  });

  it('records a miss when the window closes without a successful run', () => {
    const { outcome, reason } = evaluatePicksGate({
      job: picksJob,
      etNow: etNow(18, 55), // terminal tick
      collectEodDispatch: { ok: true, etDate: '2026-07-15', ts: '2026-07-15T21:00:00.000Z' },
      eodRun: { status: 'completed', conclusion: 'failure' },
      fetchError: null,
    });
    expect(outcome).toBe('miss');
    expect(reason).toBe('eod_run_failure');
  });

  it('still dispatches on the terminal tick if the run only just succeeded', () => {
    const { outcome } = evaluatePicksGate({
      job: picksJob,
      etNow: etNow(18, 55),
      collectEodDispatch: { ok: true, etDate: '2026-07-15', ts: '2026-07-15T21:00:00.000Z' },
      eodRun: { status: 'completed', conclusion: 'success' },
      fetchError: null,
    });
    expect(outcome).toBe('dispatch');
  });
});
