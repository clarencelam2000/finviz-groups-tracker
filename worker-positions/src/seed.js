// Watch-add FMP seed bar (WS-POSITIONS-SEED, step 2).
//
// When a ticker is added to the watchlist (POST /watchlist), best-effort-seed its most recent
// completed daily bar into ticker_quotes from FMP, labeled source='fmp_seed'. This lets a
// brand-new watch ticker resolve to a real level (prior_high/prior_low/atr/sma via
// advance.js's normalizeBar()) on its very next status read, instead of waiting for the 17:30 ET
// held feed to pick it up via heldTickers()'s watchlist union.
//
// Why INSERT OR IGNORE, never ON CONFLICT DO UPDATE: a seeded bar must never clobber a real
// Finviz-scraped bar (source='finviz', the held feed's ingestQuotes()) or a prior seed for the
// same (ticker, trade_date) — an existing row of either kind is already a better outcome than
// re-seeding it. This is the opposite uniqueness stance from ingestQuotes()'s upsert, which is
// intentional last-write-wins for same-day re-scrapes of the SAME source.
//
// Why OHLC-only (atr/raw left at their column defaults, not computed here): every downstream
// consumer (advance.js's normalizeBar(), watchlist.js's listWatch()/watchlistTickerRefs()) gates
// on isNum() and already tolerates a bar with some fields null — a partial-Finviz-scrape row has
// this exact shape today, so a seed bar with only open/high/low/close/volume/prev_close/change_pct
// filled in is not a new case to handle, just a case that already exists.
//
// Why a seeded bar can never corrupt a real position's advance: sweep.js's loadBarsAfter() reads
// strictly `trade_date > max(last_advanced_date, entry_date, openedAtEtDate)` — a seed bar is
// always the MOST RECENT completed session (never past-dated relative to "now"), so it can only
// ever be the newest row in the window, never retroactively fold into history a position's floor
// has already moved past.

const FMP_HISTORICAL_URL = "https://financialmodelingprep.com/stable/historical-price-eod/full";
// FMP_TIMEOUT_MS mirrors worker/src/index.js's FMP_TIMEOUT_MS convention (5s) — a watch-add must
// stay snappy even when FMP is slow, since seeding is best-effort and never blocks the response.
const FMP_TIMEOUT_MS = 5000;

function toNumOrNull(x) {
  if (x === null || x === undefined || x === "") return null;
  const n = typeof x === "number" ? x : Number(x);
  return Number.isFinite(n) ? n : null;
}

// PURE. Map FMP's descending-date-order historical-price-eod array into a ticker_quotes row shape.
// Returns null on empty/invalid input. rows[0] is the newest completed bar; rows[1] (if present)
// supplies prev_close. Does not compute atr/sma/raw — see module header for why.
export function mapFmpBar(rows, ticker) {
  if (!Array.isArray(rows) || rows.length === 0) return null;
  const bar = rows[0];
  if (!bar || typeof bar !== "object") return null;
  return {
    ticker,
    trade_date: bar.date,
    open: toNumOrNull(bar.open),
    high: toNumOrNull(bar.high),
    low: toNumOrNull(bar.low),
    close: toNumOrNull(bar.close),
    change_pct: toNumOrNull(bar.changePercent),
    volume: toNumOrNull(bar.volume),
    prev_close: rows[1] ? toNumOrNull(rows[1].close) : null,
  };
}

// Best-effort: seed the newest completed daily bar for `ticker` into ticker_quotes, source
// 'fmp_seed', without overwriting any existing row. Never throws — every failure mode returns
// { seeded:false, reason } instead, since a seed failure must never break the watchlist add.
export async function seedTickerBar(db, ticker, env, opts = {}) {
  const apiKey = env.FMP_API_KEY;
  if (!apiKey) {
    return { seeded: false, reason: "no_api_key" };
  }

  const apiUrl =
    `${FMP_HISTORICAL_URL}?symbol=${encodeURIComponent(ticker)}&apikey=${encodeURIComponent(apiKey)}`;

  let resp;
  try {
    resp = await fetch(apiUrl, { signal: AbortSignal.timeout(FMP_TIMEOUT_MS) });
  } catch (e) {
    return { seeded: false, reason: "fmp_timeout" };
  }

  if (resp.status === 429) {
    return { seeded: false, reason: "rate_limited" };
  }
  if (resp.status >= 500 || !resp.ok) {
    return { seeded: false, reason: "fmp_unavailable" };
  }

  let payload;
  try {
    payload = await resp.json();
  } catch (e) {
    return { seeded: false, reason: "bad_json" };
  }

  const mapped = mapFmpBar(payload, ticker);
  if (!mapped) {
    return { seeded: false, reason: "no_data" };
  }

  const collected_at = opts.now ?? new Date().toISOString();
  const sql =
    "INSERT OR IGNORE INTO ticker_quotes " +
    "(ticker, trade_date, prev_close, open, high, low, close, change_pct, volume, source, collected_at) " +
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)";

  try {
    await db
      .prepare(sql)
      .bind(
        mapped.ticker,
        mapped.trade_date,
        mapped.prev_close,
        mapped.open,
        mapped.high,
        mapped.low,
        mapped.close,
        mapped.change_pct,
        mapped.volume,
        "fmp_seed",
        collected_at,
      )
      .run();
  } catch (e) {
    return { seeded: false, reason: "db_error" };
  }

  return { seeded: true, ticker: mapped.ticker, trade_date: mapped.trade_date };
}
