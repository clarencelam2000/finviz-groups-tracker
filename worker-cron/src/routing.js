/**
 * Pure ET-wall-clock routing for the single-tick cron dispatcher (ADR-010,
 * WS1 — planning/cron-consolidation-state-machine.md).
 *
 * No I/O anywhere in this file. `scheduled()` in index.js is the only place
 * that touches KV or fetch(); everything here is a plain function of its
 * arguments so it can be unit-tested with fixed clock fixtures.
 */

// Issue #259: picks no longer fires on a fixed time margin — it re-checks
// collect.yml's actual EOD run outcome every tick inside its window (see
// picksGate.js and index.js's runPicksGate). PICKS_GATE_WINDOW_MINUTES lives
// in picksGate.js (the module that owns the gate decision logic, also I/O
// free); imported here only to size the 'picks' JOB_SCHEDULE entry's window.
import { PICKS_GATE_WINDOW_MINUTES } from './picksGate.js';

// IANA zone for all job scheduling. Cloudflare Workers' V8 runtime ships full
// ICU tz data, so Intl.DateTimeFormat tracks EST/EDT transitions with no
// lookup table to maintain — this is what makes the twice-yearly manual DST
// edit (previously required in wrangler.toml + index.js + collect.yml)
// disappear. See ADR-010 § Decision "Auto-DST via Intl.DateTimeFormat".
const ET_ZONE = 'America/New_York';

// Intl weekday abbreviation -> ISO weekday number (Mon=1..Sun=7), matching
// the convention documented in JOB_SCHEDULE below.
const WEEKDAY_MAP = { Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6, Sun: 7 };

/**
 * Compute the current Eastern wall-clock time as a plain object, DST-adjusted
 * automatically. Isolated as its own function (per the design doc's testing
 * plan) so it can be tested independently of the routing logic with fixed
 * UTC Date inputs spanning both DST regimes.
 *
 * @param {Date} [date] - defaults to now; pass a fixed Date in tests.
 * @returns {{hour: number, minute: number, weekday: number, dateStr: string}}
 *   weekday: ISO convention, Mon=1..Sun=7. dateStr: ET calendar date "YYYY-MM-DD".
 */
export function computeEtNow(date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: ET_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(date);

  const byType = {};
  for (const { type, value } of parts) byType[type] = value;

  // Intl's hour12:false can render midnight as "24" rather than "00" in some
  // engines — normalize so downstream minute-of-day arithmetic is correct.
  let hour = parseInt(byType.hour, 10);
  if (hour === 24) hour = 0;

  return {
    hour,
    minute: parseInt(byType.minute, 10),
    weekday: WEEKDAY_MAP[byType.weekday],
    dateStr: `${byType.year}-${byType.month}-${byType.day}`,
  };
}

// DISPATCH_WINDOW_MINUTES: how long after a job's target ET time the tick
// keeps considering that job "due" before giving up on it for the day. Also
// the retry budget for the self-heal amendment below (staff review on #258):
// a delayed/skipped Cloudflare tick within this window still gets picked up
// by the next 5-minute tick, since dispatch is gated on "already dispatched
// today", not on hitting the exact target minute. Must be a multiple of the
// */5 tick interval to be meaningful. Documented in worker-cron/README.md
// § Configurable parameters and CLAUDE.md § Automation.
export const DISPATCH_WINDOW_MINUTES = 30;

/**
 * The single source of truth for what fires when. Each entry replaces one of
 * the old `wrangler.toml` cron strings. Target hour/minute are ET wall-clock
 * and must land on the every-5-minutes tick grid (multiples of 5).
 *
 * `name` is the KV/observability key (`last_dispatch_<name>`) — distinct per
 * logical job even where two jobs share a `workflow` (both collect jobs
 * dispatch collect.yml, but must track "dispatched today" independently, or
 * the pre-close dispatch would wrongly suppress the EOD one).
 *
 * Documented in worker-cron/README.md § Configurable parameters and
 * CLAUDE.md § Automation, per this repo's 3-places rule for configurable
 * constants.
 */
export const JOB_SCHEDULE = [
  {
    name: 'collect_morning',
    workflow: 'morning',
    weekdays: [1, 2, 3, 4, 5], // Mon-Fri
    hour: 10,
    minute: 5,
    windowMinutes: DISPATCH_WINDOW_MINUTES,
    // ADR-013 Decision 6 (WS3 Phase B): ungated, unlike `picks`. The input —
    // yesterday's committed picks_latest.csv — already exists at dispatch
    // time (no same-day upstream job to wait on), so there is nothing to
    // gate on. collect_morning.py's own stale-input guard (max date strictly
    // before today, <= MAX_STALE_SESSIONS old) covers the failure case
    // instead.
    // 10:05 ET (owner-set 2026-08-08), NOT 09:30/09:45 — it leaves at least
    // one full 30-min candle after the 09:30 open, so the intraday High/Low
    // the state machine reads are a real session range, not a one-tick open
    // print. Must stay in sync with session_config.py MORNING.capture_et.
    // Late self-heal dispatch up to ~10:35 ET is acceptable — the store
    // records real collected_at and the PWA displays it.
  },
  {
    name: 'collect_preclose',
    workflow: 'collect',
    weekdays: [1, 2, 3, 4, 5], // Mon-Fri
    hour: 15,
    minute: 50, // shifted from legacy 15:48 to land on the 5-min grid
    windowMinutes: DISPATCH_WINDOW_MINUTES,
  },
  {
    name: 'collect_eod',
    workflow: 'collect',
    weekdays: [1, 2, 3, 4, 5],
    hour: 17,
    minute: 0, // shifted from legacy 17:01
    windowMinutes: DISPATCH_WINDOW_MINUTES,
  },
  {
    name: 'picks',
    workflow: 'picks',
    weekdays: [1, 2, 3, 4, 5],
    // Target is the SAME as collect_eod's (17:00 ET), not a fixed margin
    // after it (legacy was 18:31 = EOD + 90min). Issue #259: picks no
    // longer waits out a fixed margin and hopes — the window opens as soon
    // as collect_eod's own window opens, and `gated: true` below means
    // index.js's runPicksGate re-checks collect.yml's *actual* EOD run
    // outcome (via the GitHub Actions API) every tick inside the window,
    // dispatching picks the moment a success is confirmed rather than
    // waiting until 18:30 regardless of how fast collect_eod actually ran.
    hour: 17,
    minute: 0,
    // PICKS_GATE_WINDOW_MINUTES (120 = 17:00-19:00 ET), not the shorter
    // DISPATCH_WINDOW_MINUTES used for plain self-heal — the gate needs
    // room for collect_eod's own self-heal window (up to 30 min late) plus
    // its run time, not just a single job's normal margin. See
    // picksGate.js for the exact reasoning.
    windowMinutes: PICKS_GATE_WINDOW_MINUTES,
    // gated: true marks this job as dependency-gated rather than plain
    // fire-at-window-open — index.js's scheduled() branches on this flag to
    // call runPicksGate() instead of dispatchJob() directly. jobsInWindow/
    // jobsForTick treat it identically to any other job for the "is a
    // window open" and "already dispatched today" checks (same self-heal
    // mechanism, not a second one-off — see PR #269).
    gated: true,
  },
];

function isWithinWindow(job, etNow) {
  if (!job.weekdays.includes(etNow.weekday)) return false;
  const nowMinutes = etNow.hour * 60 + etNow.minute;
  const targetMinutes = job.hour * 60 + job.minute;
  return nowMinutes >= targetMinutes && nowMinutes < targetMinutes + job.windowMinutes;
}

/**
 * Pure: which jobs have an open dispatch window on this tick, by weekday and
 * time-of-day alone (no "already dispatched" check). Used by the caller to
 * decide whether any KV reads are needed at all this tick — on a tick where
 * this returns [], scheduled() does zero I/O, keeping the ~288 no-op
 * ticks/day genuinely free per ADR-010's observability requirement.
 *
 * @returns {string[]} job names
 */
export function jobsInWindow(etNow) {
  return JOB_SCHEDULE.filter((job) => isWithinWindow(job, etNow)).map((job) => job.name);
}

/**
 * Pure: which jobs to actually dispatch this tick.
 *
 * Staff-review amendment (issue #258): do NOT match ticks by exact-minute
 * equality against the target — a delayed or skipped Cloudflare tick would
 * then silently drop that job for the day with nothing to retry it. Instead:
 * a job is due whenever `etNow` falls anywhere in its
 * [target, target + windowMinutes) window AND it has no successful dispatch
 * recorded for today's ET date. This makes every job self-healing the same
 * way the picks dependency gate (#259) already is meant to be — one
 * mechanism, not two.
 *
 * Stays pure by taking the "already dispatched today" fact as an argument
 * instead of reading KV itself — the caller resolves `dispatchedToday` from
 * KV (only for jobs `jobsInWindow` says are in-window; see index.js).
 *
 * @param {{hour:number,minute:number,weekday:number,dateStr:string}} etNow
 * @param {Object<string,string|null>} dispatchedToday - job name -> ET date
 *   string ("YYYY-MM-DD") of that job's last *successful* dispatch, or null/
 *   undefined if none. Compared against etNow.dateStr.
 * @returns {string[]} job names to dispatch this tick
 */
export function jobsForTick(etNow, dispatchedToday = {}) {
  return JOB_SCHEDULE.filter((job) => {
    if (!isWithinWindow(job, etNow)) return false;
    return dispatchedToday[job.name] !== etNow.dateStr;
  }).map((job) => job.name);
}
