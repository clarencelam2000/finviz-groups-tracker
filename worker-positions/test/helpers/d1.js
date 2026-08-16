// Real-SQLite D1 test harness for finviz-positions (WS5 phase 3b, SPRINT WS5-3b).
//
// WHY this replaces the old hand-rolled makeDb() mock: that mock hard-coded regex sniffing of
// each SQL string and reimplemented (badly) what the migrations already declare — schema drift
// between the mock and the real D1 schema was silent and undetectable by the test suite. This
// harness instead runs the ACTUAL migration files against Node 22's built-in `node:sqlite`
// (`DatabaseSync`, in-memory), so a migration that renames/drops/adds a column breaks the tests
// immediately instead of only in production. No new npm dependency — node:sqlite ships with
// Node 22 (verified v22.22.2 on this machine); it logs an ExperimentalWarning to stderr, which is
// expected and harmless for a test-only import.
//
// This file shims JUST the D1 surface this worker actually calls (see src/positions.js,
// src/quotes.js, src/sweep.js): `db.prepare(sql).bind(...).all()/.first()/.run()` and
// `db.batch([...])`. It is not a general D1 emulator.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

// vitest's pinned vite version pre-dates "node:sqlite" (still experimental as of Node 22) in its
// builtin-module list, so a plain `import { DatabaseSync } from "node:sqlite"` — or even a dynamic
// `import("node:sqlite")` — gets treated as a missing THIRD-PARTY package named "sqlite" and fails
// to resolve ("Failed to load url sqlite"), instead of being left alone for Node to serve natively.
// Routing through createRequire()'s CommonJS `require` sidesteps vite's ESM resolution graph
// entirely — Node's own module loader handles "node:sqlite" natively regardless of vite's builtin
// list. Safe here because this file only ever runs under Node (vitest), never bundled into the
// Worker itself.
const { DatabaseSync } = createRequire(import.meta.url)("node:sqlite");

// Migration files, resolved relative to THIS helper (not cwd) so `vitest run` works regardless of
// the invocation directory. Run in order — 0002 assumes 0001's tables already exist.
const MIGRATIONS = [
  "../../migrations/0001_init.sql",
  "../../migrations/0002_ticker_quotes.sql",
  "../../migrations/0003_watchlist.sql",
];

// The leading SQL keyword decides node:sqlite dispatch: SELECT reads (`.all()`), everything else
// writes (`.run()`). This also has to handle `INSERT ... SELECT ... WHERE EXISTS (...)` — the
// guarded event-insert shape sweep.js's persistAdvance() uses (see src/sweep.js) — which STARTS
// with INSERT despite containing a SELECT deeper in, so we only ever look at the first keyword,
// never scan-and-guess from anywhere in the string.
function isSelect(sql) {
  return /^\s*SELECT\b/i.test(sql);
}

// node:sqlite throws on an `undefined` bind param (D1/JS callers routinely pass `undefined` for
// "no value" — e.g. an omitted optional column); D1 itself is lenient there, so coerce here to
// keep the shim's calling convention identical to the real thing.
function coerceBinds(args) {
  return args.map((a) => (a === undefined ? null : a));
}

// node:sqlite rows are null-prototype objects (fine for property access, but `{...row}` / JSON.stringify
// friendliness and `toEqual` deep-equality in tests want a plain Object prototype) — spread on the way out.
function toPlain(row) {
  return row ? { ...row } : row;
}

function makeStatement(db, sql) {
  let binds = [];
  return {
    sql,
    bind(...args) {
      binds = coerceBinds(args);
      return this;
    },
    async all() {
      const stmt = db.prepare(sql);
      const results = (isSelect(sql) ? stmt.all(...binds) : stmt.run(...binds));
      if (isSelect(sql)) {
        const rows = results.map(toPlain);
        return { results: rows, success: true, meta: { changes: rows.length } };
      }
      // A non-SELECT called via .all() (uncommon, but D1 technically allows it) still reports meta.
      return { results: [], success: true, meta: { changes: results.changes ?? 0 } };
    },
    async first() {
      const stmt = db.prepare(sql);
      if (isSelect(sql)) {
        const rows = stmt.all(...binds);
        return rows.length ? toPlain(rows[0]) : null;
      }
      const r = stmt.run(...binds);
      return r ? { changes: r.changes } : null;
    },
    async run() {
      const stmt = db.prepare(sql);
      const r = isSelect(sql) ? { changes: stmt.all(...binds).length } : stmt.run(...binds);
      return { success: true, meta: { changes: r.changes ?? 0 } };
    },
  };
}

export function makeD1() {
  const sqlite = new DatabaseSync(":memory:");
  for (const rel of MIGRATIONS) {
    const path = fileURLToPath(new URL(rel, import.meta.url));
    sqlite.exec(readFileSync(path, "utf8"));
  }

  const d1 = {
    prepare(sql) {
      return makeStatement(sqlite, sql);
    },
    // D1's batch() is ONE transaction — sweep.js's persistAdvance() depends on that (events +
    // the CAS UPDATE either both land or neither does). Mirror it with an explicit BEGIN/COMMIT,
    // rolling back on any statement throwing so a partial batch never leaks into the DB.
    async batch(stmts) {
      sqlite.exec("BEGIN");
      try {
        const out = [];
        for (const s of stmts) {
          out.push(await s.all()); // .all() dispatches SELECT vs write internally (see makeStatement).
        }
        sqlite.exec("COMMIT");
        return out;
      } catch (e) {
        sqlite.exec("ROLLBACK");
        throw e;
      }
    },

    // ── Test-only conveniences (not part of the D1 surface) ──────────────────────────────────
    // Seed a positions row, filling every NOT NULL column with a sane default so callers only
    // need to specify what THEIR test cares about. Mirrors buildPositionRow()'s initial-state
    // convention (src/positions.js) without importing it, so seeding stays independent of that
    // code path (a bug in buildPositionRow shouldn't silently make its own tests pass).
    _seedPosition(partial = {}) {
      const row = {
        trade_id: partial.trade_id || crypto.randomUUID(),
        user_id: "owner",
        ticker: "TEST",
        state: "managing",
        entry_date: null,
        entry_price: null,
        initial_stop: null,
        stop_basis: "manual",
        initial_qty: null,
        expected_exit_price: null,
        exit_signal_date: null,
        exit_reason: null,
        profit_floor: null,
        current_stop: null,
        trail_basis: "20ma",
        remaining_qty: null,
        caution_flag: 0,
        highest_trim_atr: 0,
        days_to_earnings: null,
        opened_at: null,
        closed_at: null,
        exit_price: null,
        confirmation_status: "unconfirmed",
        last_advanced_date: null,
        meta: "{}",
        ...partial,
      };
      const cols = Object.keys(row);
      const placeholders = cols.map(() => "?").join(", ");
      sqlite
        .prepare(`INSERT INTO positions (${cols.join(", ")}) VALUES (${placeholders})`)
        .run(...coerceBinds(cols.map((c) => row[c])));
      return row;
    },

    // Seed a ticker_quotes row. requires ticker + trade_date (the primary key); everything else
    // defaults to null / '{}' like an absent scrape field would.
    _seedQuote(partial = {}) {
      if (!partial.ticker || !partial.trade_date) {
        throw new Error("_seedQuote requires { ticker, trade_date }");
      }
      const row = {
        ticker: partial.ticker,
        trade_date: partial.trade_date,
        prev_close: null,
        open: null,
        high: null,
        low: null,
        close: null,
        change_pct: null,
        atr: null,
        volume: null,
        days_to_earnings: null,
        raw: "{}",
        collected_at: partial.collected_at || "2026-01-01T00:00:00Z",
        ...partial,
      };
      const cols = Object.keys(row);
      const placeholders = cols.map(() => "?").join(", ");
      sqlite
        .prepare(`INSERT INTO ticker_quotes (${cols.join(", ")}) VALUES (${placeholders})`)
        .run(...coerceBinds(cols.map((c) => row[c])));
      return row;
    },

    // Seed a watchlist row. Requires nothing beyond sane defaults: user_id 'owner', status 'active',
    // sessions_remaining 10 (WATCHLIST_TTL_SESSIONS), created_at set. Mirrors _seedPosition/_seedQuote's
    // convention of not importing src/watchlist.js, so a bug in addWatch() can't silently make its own
    // tests pass.
    _seedWatchlist(partial = {}) {
      const row = {
        user_id: "owner",
        ticker: "TEST",
        level_type: null,
        level_value: null,
        sessions_remaining: 10,
        status: "active",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: null,
        expired_at: null,
        meta: "{}",
        ...partial,
      };
      const cols = Object.keys(row);
      const placeholders = cols.map(() => "?").join(", ");
      sqlite
        .prepare(`INSERT INTO watchlist (${cols.join(", ")}) VALUES (${placeholders})`)
        .run(...coerceBinds(cols.map((c) => row[c])));
      return row;
    },

    _positions() {
      return sqlite.prepare("SELECT * FROM positions").all().map(toPlain);
    },
    _events() {
      return sqlite.prepare("SELECT * FROM position_events ORDER BY id ASC").all().map(toPlain);
    },
    _quotes() {
      return sqlite.prepare("SELECT * FROM ticker_quotes ORDER BY ticker ASC, trade_date ASC").all().map(toPlain);
    },
    _watchlist() {
      return sqlite.prepare("SELECT * FROM watchlist ORDER BY id ASC").all().map(toPlain);
    },
  };
  return d1;
}
