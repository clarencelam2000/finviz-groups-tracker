import { describe, it, expect } from 'vitest';
import { computeEtNow, jobsInWindow, jobsForTick, JOB_SCHEDULE, DISPATCH_WINDOW_MINUTES } from '../src/routing.js';

describe('computeEtNow — ET wall-clock + auto-DST', () => {
  it('produces EDT (summer) wall-clock time, 4 hours behind UTC', () => {
    // 2026-07-15 19:50 UTC = 15:50 EDT (UTC-4), a Wednesday.
    const etNow = computeEtNow(new Date('2026-07-15T19:50:00Z'));
    expect(etNow).toEqual({ hour: 15, minute: 50, weekday: 3, dateStr: '2026-07-15' });
  });

  it('produces EST (winter) wall-clock time, 5 hours behind UTC', () => {
    // 2026-01-15 20:50 UTC = 15:50 EST (UTC-5), a Thursday.
    const etNow = computeEtNow(new Date('2026-01-15T20:50:00Z'));
    expect(etNow).toEqual({ hour: 15, minute: 50, weekday: 4, dateStr: '2026-01-15' });
  });

  it('crosses correctly on the spring-forward transition day (2nd Sunday March 2026-03-08)', () => {
    // 06:30 UTC = 01:30 EST (still winter offset, pre-2am local transition).
    const before = computeEtNow(new Date('2026-03-08T06:30:00Z'));
    expect(before).toEqual({ hour: 1, minute: 30, weekday: 7, dateStr: '2026-03-08' });

    // 07:30 UTC = 03:30 EDT (clocks jumped 2am -> 3am local at the transition).
    const after = computeEtNow(new Date('2026-03-08T07:30:00Z'));
    expect(after).toEqual({ hour: 3, minute: 30, weekday: 7, dateStr: '2026-03-08' });
  });

  it('crosses correctly on the fall-back transition day (1st Sunday November 2026-11-01)', () => {
    // 05:30 UTC = 01:30 EDT (pre-transition, still summer offset).
    const before = computeEtNow(new Date('2026-11-01T05:30:00Z'));
    expect(before).toEqual({ hour: 1, minute: 30, weekday: 7, dateStr: '2026-11-01' });

    // 07:30 UTC = 02:30 EST (post-transition, winter offset resumed).
    const after = computeEtNow(new Date('2026-11-01T07:30:00Z'));
    expect(after).toEqual({ hour: 2, minute: 30, weekday: 7, dateStr: '2026-11-01' });
  });

  it('handles a Friday-evening ET tick that is already Saturday in UTC', () => {
    // 2026-07-18 (Sat) 02:00 UTC = 2026-07-17 (Fri) 22:00 EDT.
    const etNow = computeEtNow(new Date('2026-07-18T02:00:00Z'));
    expect(etNow.weekday).toBe(5); // Friday, ET
    expect(etNow.dateStr).toBe('2026-07-17');
  });

  it('handles a Sunday-night ET tick that is already Monday in UTC', () => {
    // 2026-07-13 (Mon) 03:00 UTC = 2026-07-12 (Sun) 23:00 EDT.
    const etNow = computeEtNow(new Date('2026-07-13T03:00:00Z'));
    expect(etNow.weekday).toBe(7); // Sunday, ET
    expect(etNow.dateStr).toBe('2026-07-12');
  });
});

describe('JOB_SCHEDULE — sanity', () => {
  it('every target time lands on the */5 tick grid', () => {
    for (const job of JOB_SCHEDULE) {
      expect(job.minute % 5).toBe(0);
    }
  });

  it('every job name is unique (KV key collisions would silently cross-suppress dispatch)', () => {
    const names = JOB_SCHEDULE.map((j) => j.name);
    expect(new Set(names).size).toBe(names.length);
  });
});

describe('jobsInWindow — pure, no "already dispatched" awareness', () => {
  it('returns [] outside any job window (illustrative routing table: any-other-tick)', () => {
    const etNow = { hour: 12, minute: 0, weekday: 3, dateStr: '2026-07-15' };
    expect(jobsInWindow(etNow)).toEqual([]);
  });

  it('returns collect_morning at 09:45 ET on a weekday (ADR-013 Phase B)', () => {
    const etNow = { hour: 9, minute: 45, weekday: 3, dateStr: '2026-07-15' };
    expect(jobsInWindow(etNow)).toEqual(['collect_morning']);
  });

  it('stays open through the window (10:14 ET, 29 min late, still inside the 30-min window)', () => {
    const etNow = { hour: 10, minute: 14, weekday: 3, dateStr: '2026-07-15' };
    expect(jobsInWindow(etNow)).toEqual(['collect_morning']);
  });

  it('closes collect_morning\'s window at 10:15 ET (target 09:45 + 30 min)', () => {
    const etNow = { hour: 10, minute: 15, weekday: 3, dateStr: '2026-07-15' };
    expect(jobsInWindow(etNow)).toEqual([]);
  });

  it('is not yet open at 09:44 ET, one minute before target', () => {
    const etNow = { hour: 9, minute: 44, weekday: 3, dateStr: '2026-07-15' };
    expect(jobsInWindow(etNow)).toEqual([]);
  });

  it('does not fire collect_morning on a weekend even at 09:45 local time', () => {
    const saturday = { hour: 9, minute: 45, weekday: 6, dateStr: '2026-07-18' };
    const sunday = { hour: 9, minute: 45, weekday: 7, dateStr: '2026-07-19' };
    expect(jobsInWindow(saturday)).toEqual([]);
    expect(jobsInWindow(sunday)).toEqual([]);
  });

  it('collect_morning is ungated (no `gated` flag), unlike picks', () => {
    const job = JOB_SCHEDULE.find((j) => j.name === 'collect_morning');
    expect(job.gated).toBeUndefined();
  });

  it('09:45 ET holds across DST: summer (EDT) instant', () => {
    // 2026-07-15 13:45 UTC = 09:45 EDT (UTC-4), a Wednesday.
    const etNow = computeEtNow(new Date('2026-07-15T13:45:00Z'));
    expect(jobsInWindow(etNow)).toEqual(['collect_morning']);
  });

  it('09:45 ET holds across DST: winter (EST) instant', () => {
    // 2026-01-15 14:45 UTC = 09:45 EST (UTC-5), a Thursday.
    const etNow = computeEtNow(new Date('2026-01-15T14:45:00Z'));
    expect(jobsInWindow(etNow)).toEqual(['collect_morning']);
  });

  it('returns collect_preclose at 15:50 ET on a weekday', () => {
    const etNow = { hour: 15, minute: 50, weekday: 3, dateStr: '2026-07-15' };
    expect(jobsInWindow(etNow)).toEqual(['collect_preclose']);
  });

  it('returns collect_eod AND picks at 17:00 ET on a weekday (issue #259: picks shares collect_eod\'s target, gated on dependency not a later fixed time)', () => {
    const etNow = { hour: 17, minute: 0, weekday: 3, dateStr: '2026-07-15' };
    expect(jobsInWindow(etNow)).toEqual(['collect_eod', 'picks']);
  });

  it('returns just picks once collect_eod\'s own (shorter) window has closed but picks\' (longer, gate) window is still open', () => {
    const etNow = { hour: 18, minute: 30, weekday: 3, dateStr: '2026-07-15' };
    expect(jobsInWindow(etNow)).toEqual(['picks']);
  });

  it('stays open for the full window, not just the exact target minute', () => {
    // 15 minutes late, still inside collect_eod's 30-minute window (and
    // picks' much wider 120-minute gate window, since #259 sized it to
    // start at the same 17:00 target).
    const etNow = { hour: 17, minute: 15, weekday: 3, dateStr: '2026-07-15' };
    expect(jobsInWindow(etNow)).toEqual(['collect_eod', 'picks']);
  });

  it('closes once a job\'s own window elapses (collect_preclose, isolated — does not overlap picks\' window)', () => {
    // collect_preclose targets 15:50 with DISPATCH_WINDOW_MINUTES (30) window
    // -> closes at 16:20, exactly the tick asserted here.
    expect(DISPATCH_WINDOW_MINUTES).toBe(30);
    const etNow = { hour: 16, minute: 20, weekday: 3, dateStr: '2026-07-15' };
    expect(jobsInWindow(etNow)).toEqual([]);
  });

  it('gates on weekday: no jobs fire on Saturday or Sunday even at a valid time-of-day', () => {
    const saturday = { hour: 17, minute: 0, weekday: 6, dateStr: '2026-07-18' };
    const sunday = { hour: 17, minute: 0, weekday: 7, dateStr: '2026-07-19' };
    expect(jobsInWindow(saturday)).toEqual([]);
    expect(jobsInWindow(sunday)).toEqual([]);
  });
});

describe('jobsForTick — self-healing dispatch (staff amendment on #258)', () => {
  it('dispatches every job whose window is open and not yet dispatched today (collect_eod and picks share the 17:00 target — #259)', () => {
    const etNow = { hour: 17, minute: 0, weekday: 3, dateStr: '2026-07-15' };
    expect(jobsForTick(etNow, {})).toEqual(['collect_eod', 'picks']);
  });

  it('does not re-dispatch a job already recorded as dispatched today, while an undispatched sibling in the same window still is', () => {
    const etNow = { hour: 17, minute: 0, weekday: 3, dateStr: '2026-07-15' };
    const dispatchedToday = { collect_eod: '2026-07-15' };
    expect(jobsForTick(etNow, dispatchedToday)).toEqual(['picks']);
  });

  it('re-dispatches if the recorded date is stale (yesterday, not today)', () => {
    const etNow = { hour: 17, minute: 0, weekday: 3, dateStr: '2026-07-15' };
    const dispatchedToday = { collect_eod: '2026-07-14' };
    expect(jobsForTick(etNow, dispatchedToday)).toEqual(['collect_eod', 'picks']);
  });

  it('self-heals a delayed tick: a late tick within the window still dispatches', () => {
    // The exact :00 tick was skipped/delayed by Cloudflare; the :20 tick
    // picks it up because the job hasn't been dispatched today yet.
    const etNow = { hour: 17, minute: 20, weekday: 3, dateStr: '2026-07-15' };
    expect(jobsForTick(etNow, {})).toEqual(['collect_eod', 'picks']);
  });

  it('does not dispatch a job once its own window has closed, even if never dispatched (collect_preclose, isolated)', () => {
    const etNow = { hour: 16, minute: 20, weekday: 3, dateStr: '2026-07-15' }; // collect_preclose window closes at 16:20
    expect(jobsForTick(etNow, {})).toEqual([]);
  });

  it('a plain no-op tick (no job in window) returns [] regardless of dispatchedToday', () => {
    const etNow = { hour: 12, minute: 0, weekday: 3, dateStr: '2026-07-15' };
    expect(jobsForTick(etNow, { collect_eod: '2026-07-14' })).toEqual([]);
  });

  it('dispatches collect_morning at 09:45 ET when not yet dispatched today', () => {
    const etNow = { hour: 9, minute: 45, weekday: 3, dateStr: '2026-07-15' };
    expect(jobsForTick(etNow, {})).toEqual(['collect_morning']);
  });

  it('self-heals a delayed collect_morning tick (10:00 ET, 15 min late, still inside window)', () => {
    const etNow = { hour: 10, minute: 0, weekday: 3, dateStr: '2026-07-15' };
    expect(jobsForTick(etNow, {})).toEqual(['collect_morning']);
  });

  it('does not re-dispatch collect_morning already recorded as dispatched today', () => {
    const etNow = { hour: 9, minute: 45, weekday: 3, dateStr: '2026-07-15' };
    expect(jobsForTick(etNow, { collect_morning: '2026-07-15' })).toEqual([]);
  });
});
