/**
 * Picks dependency gate (issue #259, ADR-010 "dependency-driven dispatch").
 *
 * Replaces picks' old fixed-time-margin dispatch (fire at EOD target + 90min
 * and hope) with a check against collect.yml's *actual* EOD run outcome:
 * picks only fires once the EOD collect run is confirmed `conclusion ===
 * 'success'`, not just "N minutes have passed."
 *
 * Pure decision logic lives here so it's unit-testable with injected fake
 * run-status data (no network) — see worker-cron/test/picksGate.test.js.
 * The I/O (KV read + GitHub Actions runs-list fetch) lives in index.js
 * (`runPicksGate`), same split as routing.js's jobsForTick/scheduled().
 */

// PICKS_GATE_WINDOW_MINUTES: how long, from the picks job's target ET time
// (JOB_SCHEDULE's 'picks' entry — 17:00 ET, the same target as collect_eod,
// since the gate is now what decides *whether* to fire, not a fixed later
// time), the gate keeps re-checking every tick before giving up for the day
// and recording a "miss". 120 min is a generous margin over the observed
// worst case: collect.py (2-4 min, up to 3 retries at 30/60/120s backoff =
// ~3.5 min worst case) + compute_deltas.py (~5s) + evaluate_picks.py + git
// push, plus GitHub Actions queueing/runner-startup latency. Must be a
// multiple of the */5 tick interval (routing.js). Documented in
// worker-cron/README.md § Configurable parameters and CLAUDE.md §
// Automation, per this repo's 3-places rule for configurable constants.
export const PICKS_GATE_WINDOW_MINUTES = 120;

// RUN_MATCH_TOLERANCE_MS: our workflow_dispatch POST and GitHub actually
// creating the corresponding Actions run are not perfectly simultaneous.
// Allow the matched run's created_at to be up to this much *before* our
// recorded last_dispatch_collect_eod timestamp (clock skew + GitHub queuing
// latency) when picking the run that corresponds to our EOD dispatch out of
// collect.yml's run history. collect.yml also runs from the earlier
// collect_preclose dispatch and the GitHub schedule: backstop the same day,
// so "most recent run" alone is not a safe disambiguator — issue #259
// review finding #1 ("the run-success check can be satisfied by the wrong
// run").
const RUN_MATCH_TOLERANCE_MS = 60_000;

/**
 * Pure: pick the GitHub Actions run that corresponds to our EOD collect
 * dispatch out of collect.yml's run history, disambiguating from the
 * earlier same-day pre-close run.
 *
 * @param {Array<{created_at: string, status: string, conclusion: string|null}>} runs
 *   collect.yml runs, any order.
 * @param {string} dispatchTs - ISO timestamp of our last_dispatch_collect_eod record.
 * @returns {object|null} the earliest run created at/after (dispatchTs - tolerance), or null.
 */
export function findEodRun(runs, dispatchTs) {
  if (!runs || !runs.length || !dispatchTs) return null;
  const cutoff = new Date(dispatchTs).getTime() - RUN_MATCH_TOLERANCE_MS;
  const candidates = runs
    .filter((r) => new Date(r.created_at).getTime() >= cutoff)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
  return candidates[0] || null;
}

/**
 * Pure: is this tick the last one inside the job's window (i.e. the next
 * tick, 5 minutes later, would fall outside it)? Used to decide whether a
 * still-not-successful gate check should be recorded as "waiting" (retry
 * next tick) or "miss" (window closing, give up for today).
 */
export function isTerminalTick(job, etNow, tickIntervalMinutes = 5) {
  const nowMinutes = etNow.hour * 60 + etNow.minute;
  const targetMinutes = job.hour * 60 + job.minute;
  const windowEnd = targetMinutes + job.windowMinutes;
  return nowMinutes + tickIntervalMinutes >= windowEnd;
}

/**
 * Pure: decide the picks dependency-gate outcome for this tick.
 *
 * @param {object} params
 * @param {{hour:number,minute:number,windowMinutes:number}} params.job - the picks JOB_SCHEDULE entry
 * @param {{hour:number,minute:number,weekday:number,dateStr:string}} params.etNow
 * @param {{ok:boolean,etDate:string,ts:string}|null} params.collectEodDispatch - last_dispatch_collect_eod KV record
 * @param {{status:string,conclusion:string|null}|null} params.eodRun - matched GitHub Actions run (findEodRun), or null
 * @param {string|null} params.fetchError - set if the runs-list fetch itself failed (network/auth), for diagnosis
 * @returns {{outcome: 'dispatch'|'waiting'|'miss', reason: string}}
 */
export function evaluatePicksGate({ job, etNow, collectEodDispatch, eodRun, fetchError }) {
  let reason;
  let satisfied = false;

  if (!collectEodDispatch || !collectEodDispatch.ok || collectEodDispatch.etDate !== etNow.dateStr) {
    reason = 'collect_eod_not_dispatched';
  } else if (fetchError) {
    reason = `run_status_fetch_failed:${fetchError}`;
  } else if (!eodRun) {
    reason = 'eod_run_not_found';
  } else if (eodRun.status !== 'completed') {
    reason = 'eod_run_in_progress';
  } else if (eodRun.conclusion !== 'success') {
    reason = `eod_run_${eodRun.conclusion || 'unknown'}`;
  } else {
    satisfied = true;
    reason = 'eod_run_success';
  }

  if (satisfied) return { outcome: 'dispatch', reason };
  return { outcome: isTerminalTick(job, etNow) ? 'miss' : 'waiting', reason };
}
