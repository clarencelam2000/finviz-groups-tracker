// The daily-advancement engine for finviz-positions (WS5 phase 3 — issue #264, SPRINT WS5-3).
//
// This module is the HEART of the trade-lifecycle engine: a set of PURE functions that take a
// position + a settled daily bar (+ effective config) and return the next position state and the
// events to append. Nothing here touches D1, the network, or the clock — the wiring layer
// (WS5-3b) loads the row + bars, calls these, and persists the result. Keeping it pure is what
// makes the whole test plan (design §9) and future rule-variant replay (design §12) possible.
//
// Design: planning/trade-lifecycle-engine.md §4 (algorithm), §6 (constants), §7 (edge cases),
// §9 (test plan), §14 (per-position rules). ADR-012.
//
// -- The one non-obvious input transform (do not mis-read) ------------------------------------
// Finviz's SMA20/SMA50/SMA200 columns are the PERCENT DISTANCE of price from that moving average,
// NOT the MA price level (see migration 0002 header). advance() needs LEVELS. `normalizeBar()`
// recovers them:  level = close / (1 + pct/100).  advance() itself never sees the %-distance — it
// takes a bar whose sma* fields are already levels, so the Finviz representation quirk lives in
// exactly one place.

// ── Config constants (§6). Triple-documented: here + README § Configurable parameters + CLAUDE.md.
// Every one is a tunable; advance() reads them from an EFFECTIVE config (globals + per-position
// meta.config overrides, §14), never from this object directly, so a per-position rule is a data
// change, not an engine rewrite.
export const ENGINE_CONFIG = Object.freeze({
  // R-multiple at which profit_floor ratchets up to entry (breakeven). Owner: +1R exactly, not a
  // price-buffer variant (§6, alignment 2026-08-10).
  BREAKEVEN_R: 1.0,
  // Widen the trail from the 20MA to the 50MA once the 50MA has risen above entry. Global default;
  // a single position opts out via meta.widen_enabled=false (§6 per-position toggle).
  WIDEN_TRAIL_BASIS: true,
  // First WHOLE ATR-extension-from-50MA level that triggers a scale-out trim (7,8,9,...).
  TRIM_START_ATR: 7,
  // Fraction of REMAINING quantity trimmed at each newly-crossed whole ATR level. Trimming the
  // remainder (not the initial) is asymptotic — a lot is never fully trimmed to zero by the engine.
  TRIM_PCT: 0.1,
  // Consecutive closes below the 20MA that force a winner's soft exit. caution_flag counts them
  // (see below); exit fires when the count reaches this. Default 2 == the design's boolean caution.
  TWO_CLOSE_EXIT: 2,
  // Close below this MA is an immediate hard exit regardless of the two-close rule. "20ma"|"50ma".
  HARD_EXIT_BASIS: "50ma",
  // Single-day drop (in ATRs, prev_close→close) that counts as "really breaks" — a one-day crash
  // hard exit. Owner-set 2026-08-07 (1 ATR = noise, ~2 = bad day, 3+ = something broke); recalibrate
  // after real triggers. Set to Infinity to disable and rely on the close-below-50MA hard exit alone.
  SEVERE_BREAKDOWN_ATR: 3.0,
  // Days-to-earnings at/under which the guardrail FLAGS (never auto-exits — the user decides).
  // Reuses the Focus EARNINGS_CAUTION_DAYS (10) outer band; imminent (≤3) is a phase-4 notif nuance.
  EARNINGS_WARN_SESSIONS: 10,
  // Trading sessions a position may sit in Closing before auto-closing at expected_exit_price with
  // confirmation_status='auto' (§7 auto-confirm). Applied by autoConfirm(), not advance().
  EXIT_AUTOCONFIRM_SESSIONS: 5,
  // On "still holding", reset caution_flag so the two-close rule re-arms (needs two fresh closes)
  // rather than re-signalling on the next single close (§6, owner 2026-08-11). Applied by stillHolding().
  CAUTION_REARM_ON_HOLD: true,
});

// Canonical exit-reason enum (§6). hard_exit is split into close_below_50ma (slow bleed) and
// severe_breakdown (one-day crash) so the honest record can say WHY. Earnings is NOT an exit reason.
// close_below_20ma is the HARD_EXIT_BASIS="20ma" override's immediate single-close counterpart to
// close_below_50ma — distinct from two_close_below_20ma, the stateful two-consecutive-closes rule
// in section (c) below, so the record never claims two closes happened when only one did.
export const EXIT_REASONS = Object.freeze([
  "stop_hit",
  "gap_down_below_stop",
  "close_below_50ma",
  "close_below_20ma",
  "severe_breakdown",
  "two_close_below_20ma",
  "manual_close",
]);

// Terminal-ish states advance() will not re-advance: `closed` is done; `closing` is awaiting the
// user's confirmed fill (or a "still holding" revert) and must not be silently advanced past (§4).
const NON_ADVANCING_STATES = new Set(["closed", "closing"]);

// ── Effective config (§4/§14): globals with this position's meta.config overrides layered on top.
// Overrides live under meta.config (a sub-bag) so they never collide with meta.source/group_id/
// widen_enabled. Empty for every position today, so effective == globals — but wiring it in from
// the start keeps advance() a pure function of (pos, bar, cfg).
export function effectiveConfig(pos, globals = ENGINE_CONFIG) {
  const overrides = pos && pos.meta && typeof pos.meta.config === "object" && pos.meta.config
    ? pos.meta.config
    : {};
  return { ...globals, ...overrides };
}

// ── Small pure helpers ──────────────────────────────────────────────────────────────────────────
function isNum(x) {
  return typeof x === "number" && Number.isFinite(x);
}

// R = entry − initial_stop (risk per share, frozen for the life of the trade, §3). r-multiple of a
// price is (price − entry)/R. Guarded: a non-positive R (bad data) yields NaN rather than a lie.
export function riskPerShare(pos) {
  return pos.entry_price - pos.initial_stop;
}
export function rMultiple(pos, price) {
  const r = riskPerShare(pos);
  if (!isNum(r) || r <= 0 || !isNum(price)) return NaN;
  return (price - pos.entry_price) / r;
}

// ATR extension of the close above the 50MA, in ATRs — identical to atr_ext_50 in picks_metrics.py.
// This is both the trim trigger (§4) and the retrace-heat gauge (§13).
export function atrExt50(bar) {
  if (!isNum(bar.close) || !isNum(bar.sma50) || !isNum(bar.atr) || bar.atr <= 0) return NaN;
  return (bar.close - bar.sma50) / bar.atr;
}

// A one-day crash: prev_close→close drop of ≥ SEVERE_BREAKDOWN_ATR ATRs. Uses prev_close (not open)
// so an intraday-recovered gap doesn't count and a genuine settled collapse does.
export function severeBreakdown(bar, cfg) {
  if (!isNum(bar.prev_close) || !isNum(bar.close) || !isNum(bar.atr) || bar.atr <= 0) return false;
  if (!isNum(cfg.SEVERE_BREAKDOWN_ATR)) return false;
  const dropAtr = (bar.prev_close - bar.close) / bar.atr;
  return dropAtr >= cfg.SEVERE_BREAKDOWN_ATR;
}

// Recover an MA price LEVEL from Finviz's %-distance-from-MA (see module header + migration 0002).
// pctDistance is the signed percent (e.g. 2.34 means price is 2.34% ABOVE the MA). Returns null if
// either input is unusable — a null MA level makes the corresponding rule a no-op that session
// rather than acting on a fabricated level.
export function recoverMaLevel(close, pctDistance) {
  if (!isNum(close) || !isNum(pctDistance)) return null;
  const denom = 1 + pctDistance / 100;
  if (denom <= 0) return null;
  return close / denom;
}

// ── State transition: signal an exit → Closing (NEVER Closed). Records the MODELED price as the
// EXPECTED fill and emits exit_signal; the user's confirmation (confirmExit) is what writes
// exit_price. A position in Closing is not re-advanced — it waits on the user (§4 exit semantics).
function signalExit(pos, bar, price, reason) {
  const next = {
    ...pos,
    state: "closing",
    expected_exit_price: price,
    exit_signal_date: bar.trade_date,
    exit_reason: reason,
    last_advanced_date: bar.trade_date,
  };
  const events = [
    { event_type: "exit_signal", payload: { reason, expected_exit_price: price, at_close: bar.close } },
  ];
  return { position: next, events };
}

// ── The daily-advancement algorithm (§4). advance(pos, bar, cfg) → { position, events, stale? }.
// PURE and idempotent per (position, trade_date): the last_advanced_date guard makes a same-date
// re-run a no-op, and the trim ledger + monotonic ratchets make the state deterministic. Rules are
// checked EXIT-BEFORE-ADVANCE so a position that should exit today is not first trailed then exited.
export function advance(pos, bar, cfg = ENGINE_CONFIG) {
  // Terminal / awaiting-user states: no-op (§4). Closing waits on the user; Closed is done.
  if (NON_ADVANCING_STATES.has(pos.state)) return { position: pos, events: [] };

  // Stale / missing bar (delist, feed miss): flag + alert, DO NOT advance and DO NOT stamp
  // last_advanced_date (so a real bar later that day still advances it). Never act on stale data.
  if (!bar || !isNum(bar.close) || !bar.trade_date) {
    return {
      position: pos,
      events: [{ event_type: "note", payload: { stale: true, message: "stale or missing quote — not advanced" } }],
      stale: true,
    };
  }

  // Idempotency guard (§7 same-day re-run): never advance a date already advanced (or an older,
  // out-of-order bar). This is what keeps the caution counter from double-incrementing on a re-run.
  if (pos.last_advanced_date && bar.trade_date <= pos.last_advanced_date) {
    return { position: pos, events: [] };
  }

  let next = { ...pos };
  const events = [];

  // ── EXIT CHECKS (ordered; first match SIGNALS the exit → Closing and returns immediately, so no
  // stop-move/trim/earnings event is ever emitted on the bar that signals an exit — pinned by test).

  // (a) Stop hit — including an honest gap-down (opened below the stop → fill at the open, worse).
  if (isNum(next.current_stop) && bar.low <= next.current_stop) {
    const gap = isNum(bar.open) && bar.open < next.current_stop;
    const exitPrice = gap ? bar.open : next.current_stop;
    return signalExit(next, bar, exitPrice, gap ? "gap_down_below_stop" : "stop_hit");
  }

  // (b) Hard exit — two DISTINCT reasons, reported separately (§6 split of the old bundled hard_exit).
  const hardBasisLevel = cfg.HARD_EXIT_BASIS === "20ma" ? bar.sma20 : bar.sma50;
  if (isNum(hardBasisLevel) && bar.close < hardBasisLevel) {
    const reason = cfg.HARD_EXIT_BASIS === "20ma" ? "close_below_20ma" : "close_below_50ma";
    return signalExit(next, bar, bar.close, reason);
  }
  if (severeBreakdown(bar, cfg)) {
    return signalExit(next, bar, bar.close, "severe_breakdown");
  }

  // (c) Stateful two-close-below-20MA soft exit. Fires even after the trail widened to the 50MA
  // (price can lose the 20MA while still above the 50MA stop) — deliberate (§7 "two-close above 50MA").
  // caution_flag is used as a COUNTER of consecutive closes below the 20MA; the boolean design case
  // (default TWO_CLOSE_EXIT=2) is exactly count 0→1 (caution) then 1→2 (exit).
  if (isNum(bar.sma20) && bar.close < bar.sma20) {
    const count = (next.caution_flag || 0) + 1;
    const twoCloseExit = isNum(cfg.TWO_CLOSE_EXIT) ? cfg.TWO_CLOSE_EXIT : 2;
    if (count >= twoCloseExit) {
      return signalExit(next, bar, bar.close, "two_close_below_20ma");
    }
    next.caution_flag = count; // 1st close below → caution; keep advancing the stop/trim this bar.
    events.push({ event_type: "caution", payload: { closes_below_20ma: count, at_close: bar.close } });
  } else if (isNum(bar.sma20)) {
    next.caution_flag = 0; // any close back at/above the 20MA resets the counter.
  }

  // ── STILL MANAGING: stop advancement ────────────────────────────────────────────────────────

  // Profit floor: monotonic non-decreasing (§4 the ONLY monotonic quantity). Ratchets to entry at
  // +BREAKEVEN_R — "once past breakeven, never red again".
  if (rMultiple(next, bar.close) >= cfg.BREAKEVEN_R) {
    next.profit_floor = Math.max(next.profit_floor, next.entry_price);
  }

  // Trailing basis: default 20MA; WIDEN to 50MA once the 50MA is above entry (global toggle AND the
  // per-position meta.widen_enabled). The widen is a deliberate one-time loosen that may LOWER the
  // stop, but never below the profit floor (invariant current_stop ≥ profit_floor always holds).
  const widenAllowed = cfg.WIDEN_TRAIL_BASIS && (next.meta ? next.meta.widen_enabled !== false : true);
  const wantBasis = widenAllowed && isNum(bar.sma50) && bar.sma50 > next.entry_price ? "50ma" : "20ma";
  const trailLevel = wantBasis === "50ma" ? bar.sma50 : bar.sma20;
  const prevStop = next.current_stop;
  if (isNum(trailLevel)) {
    if (wantBasis !== next.trail_basis) {
      next.current_stop = Math.max(next.profit_floor, trailLevel);
      next.trail_basis = wantBasis;
    } else {
      next.current_stop = Math.max(next.current_stop, trailLevel, next.profit_floor);
    }
  } else {
    // No MA level this bar → keep the stop where it is, but still enforce the floor.
    next.current_stop = Math.max(next.current_stop, next.profit_floor);
  }
  if (next.current_stop !== prevStop) {
    events.push({
      event_type: "stop_moved",
      payload: { from: prevStop, to: next.current_stop, basis: next.trail_basis },
    });
  }

  // ── SCALE-OUT trims (ATR extension from the 50MA). Ledger guard (highest_trim_atr) makes trims
  // idempotent and catch-up-correct: a jump from 6.5→8.2 ATR trims once for 7 and once for 8; a
  // re-run trims nothing. TRIM_PCT of REMAINING each level (asymptotic, never fully to zero).
  const ext = atrExt50(bar);
  if (isNum(ext) && ext >= cfg.TRIM_START_ATR) {
    for (let m = cfg.TRIM_START_ATR; m <= Math.floor(ext); m++) {
      if (m > (next.highest_trim_atr || 0)) {
        const trimQty = next.remaining_qty * cfg.TRIM_PCT;
        next.remaining_qty -= trimQty;
        next.highest_trim_atr = m;
        events.push({
          event_type: "partial_exit",
          payload: { qty: trimQty, at_atr: m, price: bar.close, remaining_qty: next.remaining_qty },
        });
      }
    }
  }

  // ── EARNINGS guardrail (§4): FLAG only, never auto-exit — the user integrates earnings manually.
  // Refresh days_to_earnings from the bar if the feed derived a fresh value.
  if (isNum(bar.days_to_earnings)) next.days_to_earnings = Math.trunc(bar.days_to_earnings);
  if (isNum(next.days_to_earnings) && next.days_to_earnings <= cfg.EARNINGS_WARN_SESSIONS) {
    events.push({
      event_type: "note",
      payload: { earnings_warning: true, days_to_earnings: next.days_to_earnings },
    });
  }

  // Survived its first advance without exiting: Open → Managing (§1). The engine now manages it.
  if (next.state === "open") next.state = "managing";
  next.last_advanced_date = bar.trade_date;

  return { position: next, events };
}

// ── User-driven state transitions (pure; the wiring layer's endpoints call these) ────────────────

// Confirm the exit fill: Closing → Closed. Writes the USER's actual fill to exit_price (pre-filled
// with expected_exit_price in the UI but editable — the modeled price is a default, never the
// recorded truth when they differ, §7). confirmation_status='confirmed'.
export function confirmExit(pos, { exit_price, trade_date, now_iso }) {
  const price = isNum(exit_price) ? exit_price : pos.expected_exit_price;
  const next = {
    ...pos,
    state: "closed",
    exit_price: price,
    closed_at: now_iso || null,
    confirmation_status: "confirmed",
  };
  return {
    position: next,
    events: [
      {
        event_type: "closed",
        payload: {
          exit_price: price,
          exit_reason: pos.exit_reason,
          confirmation_status: "confirmed",
          r_multiple: rMultiple(pos, price),
        },
      },
    ],
    trade_date,
  };
}

// "Still holding" (§7): the user rejects an exit signal from Closing → back to Managing. Clears the
// expected-exit fields; re-arms the two-close rule (caution_flag=0) when CAUTION_REARM_ON_HOLD, so
// it takes two FRESH closes to re-signal rather than re-signalling on the next single close. A note
// event records the discretionary override.
export function stillHolding(pos, cfg = ENGINE_CONFIG, { trade_date } = {}) {
  const next = {
    ...pos,
    state: "managing",
    expected_exit_price: null,
    exit_signal_date: null,
    exit_reason: null,
  };
  if (cfg.CAUTION_REARM_ON_HOLD) next.caution_flag = 0;
  return {
    position: next,
    events: [{ event_type: "note", payload: { still_holding: true, prior_exit_reason: pos.exit_reason } }],
    trade_date,
  };
}

// Auto-confirm a stuck Closing position (§7): after EXIT_AUTOCONFIRM_SESSIONS sessions in Closing it
// closes at the price frozen AT SIGNAL time (expected_exit_price — do NOT re-derive from later bars),
// labeled confirmation_status='auto'. `sessionsInClosing` is computed by the wiring layer (trading
// sessions between exit_signal_date and today). Returns null when it is not yet time.
export function autoConfirm(pos, cfg = ENGINE_CONFIG, { sessionsInClosing, trade_date, now_iso } = {}) {
  if (pos.state !== "closing") return null;
  if (!isNum(sessionsInClosing) || sessionsInClosing < cfg.EXIT_AUTOCONFIRM_SESSIONS) return null;
  const price = pos.expected_exit_price;
  const next = {
    ...pos,
    state: "closed",
    exit_price: price,
    closed_at: now_iso || null,
    confirmation_status: "auto",
  };
  return {
    position: next,
    events: [
      {
        event_type: "closed",
        payload: {
          exit_price: price,
          exit_reason: pos.exit_reason,
          confirmation_status: "auto",
          r_multiple: rMultiple(pos, price),
        },
      },
    ],
    trade_date,
  };
}

// Append-only correction of a closed position's exit price (§7): emits exit_corrected and recomputes
// R — the original `closed` event is NOT mutated (the ledger keeps both). exit_price is updated on
// the spine so reads reflect the correction; confirmation_status becomes 'confirmed' (a human fixed it).
export function correctExit(pos, { exit_price, trade_date }) {
  const price = exit_price;
  const next = { ...pos, exit_price: price, confirmation_status: "confirmed" };
  return {
    position: next,
    events: [
      {
        event_type: "exit_corrected",
        payload: { from: pos.exit_price, to: price, r_multiple: rMultiple(pos, price) },
      },
    ],
    trade_date,
  };
}

// Reopen a wrongly-closed trade (§7): Closed → Managing, emits reopened. Clears the exit fields so
// advance() resumes cleanly from the next bar; the original closed/exit events stay in the ledger.
// caution_flag is also reset (mirrors stillHolding's re-arm) so the two-close-below-20MA rule
// requires two fresh closes post-reopen instead of reusing the stale pre-reopen counter.
export function reopen(pos, { trade_date } = {}) {
  const next = {
    ...pos,
    state: "managing",
    exit_price: null,
    closed_at: null,
    expected_exit_price: null,
    exit_signal_date: null,
    exit_reason: null,
    confirmation_status: "unconfirmed",
    caution_flag: 0,
  };
  return {
    position: next,
    events: [{ event_type: "reopened", payload: { prior_exit_price: pos.exit_price } }],
    trade_date,
  };
}

// ── Bar normalization: a ticker_quotes row → the bar advance() consumes. PURE. Recovers the SMA
// LEVELS from Finviz's %-distance columns in `raw` (the one representation quirk, module header).
// The typed columns (close/high/low/open/prev_close/atr) are used as-is. days_to_earnings prefers
// the typed column (the feed may derive it later); when that's null/absent it falls back to
// parsing raw["Earnings"] (Finviz "Mon DD[/a|/b]") via parseEarningsToDays(), anchored on the
// bar's own trade_date so the parse is a pure function of the row, not the wall clock.
export function normalizeBar(row) {
  if (!row || typeof row !== "object") return null;
  const raw = typeof row.raw === "string" ? safeJson(row.raw) : row.raw || {};
  const close = numOrNull(row.close);
  const typedEarnings = numOrNull(row.days_to_earnings);
  return {
    trade_date: row.trade_date || null,
    close,
    high: numOrNull(row.high),
    low: numOrNull(row.low),
    open: numOrNull(row.open),
    prev_close: numOrNull(row.prev_close),
    atr: numOrNull(row.atr),
    volume: numOrNull(row.volume),
    sma20: recoverMaLevel(close, pctFromRaw(raw, "SMA20")),
    sma50: recoverMaLevel(close, pctFromRaw(raw, "SMA50")),
    sma200: recoverMaLevel(close, pctFromRaw(raw, "SMA200")),
    // row.trade_date is required here (not just passed through): without it, parseEarningsToDays
    // would fall back to its own `new Date()` default and normalizeBar would no longer be a pure
    // function of the row (module header, line 5-7).
    days_to_earnings:
      typedEarnings !== null
        ? typedEarnings
        : row.trade_date
          ? parseEarningsToDays(raw["Earnings"], row.trade_date)
          : null,
  };
}

// Finviz "Earnings" column month abbreviation → 0-indexed month. 12 entries, no locale lookup
// (the column is always English 3-letter abbreviations regardless of Finviz account locale).
const EARNINGS_MONTH_ABBR = {
  Jan: 0, Feb: 1, Mar: 2, Apr: 3, May: 4, Jun: 5,
  Jul: 6, Aug: 7, Sep: 8, Oct: 9, Nov: 10, Dec: 11,
};

// Parse Finviz "Earnings" column ("Mon DD" + optional /a after-close or /b before-open) into an
// integer count of CALENDAR days from asOf to the earnings date. Year is inferred (roll forward a
// year if the date is >180 days in the past — Finviz gives no year). Returns null on "-"/blank/
// unparseable. NOTE: this is calendar days, a conservative proxy for the "sessions" the guardrail
// wants (calendar days >= trading sessions, so the flag fires slightly early — safe). asOf is an
// ISO-8601 date string (e.g. the bar's trade_date "YYYY-MM-DD") or a Date; default new Date().
export function parseEarningsToDays(earningsStr, asOf) {
  if (!earningsStr || earningsStr === "-") return null;
  const m = String(earningsStr).trim().match(/^([A-Za-z]{3})\s+(\d{1,2})(?:\/([ab]))?$/);
  if (!m || !(m[1] in EARNINGS_MONTH_ABBR)) return null;
  const month = EARNINGS_MONTH_ABBR[m[1]];
  const day = parseInt(m[2], 10);

  // Anchor "today" from asOf. A "YYYY-MM-DD" string is parsed as UTC y/m/d fields directly (not
  // via `new Date(string)`, which is UTC-midnight and would drift a day against the UTC math
  // below in negative-offset zones) — everything here stays in UTC to avoid mixing local/UTC.
  let today;
  if (asOf instanceof Date) {
    today = Date.UTC(asOf.getUTCFullYear(), asOf.getUTCMonth(), asOf.getUTCDate());
  } else if (typeof asOf === "string") {
    const dm = asOf.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!dm) return null;
    today = Date.UTC(Number(dm[1]), Number(dm[2]) - 1, Number(dm[3]));
  } else {
    const now = new Date();
    today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  }

  const msPerDay = 86400000;
  const todayYear = new Date(today).getUTCFullYear();
  let earningsMs = Date.UTC(todayYear, month, day);
  if ((today - earningsMs) / msPerDay > 180) earningsMs = Date.UTC(todayYear + 1, month, day);
  return Math.round((earningsMs - today) / msPerDay);
}

function pctFromRaw(raw, key) {
  const v = raw ? raw[key] : null;
  if (v === null || v === undefined) return null;
  // Finviz %-distance columns come through as e.g. "2.34%" or "-1.20%" (or already a number).
  const s = typeof v === "string" ? v.replace("%", "").trim() : v;
  const n = typeof s === "number" ? s : Number(s);
  return Number.isFinite(n) ? n : null;
}
function numOrNull(x) {
  if (x === null || x === undefined || x === "") return null;
  const n = typeof x === "number" ? x : Number(x);
  return Number.isFinite(n) ? n : null;
}
function safeJson(s) {
  try {
    return JSON.parse(s || "{}");
  } catch {
    return {};
  }
}
