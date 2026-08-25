# Watchlist status honesty + bar-seeding (WS-POSITIONS-*)

**Trigger:** owner report, 2026-08-25 — 5 tickers added Sat Aug 22 ~1:50pm ET still showed
"Adding — first morning check lands tomorrow AM after tonight's data run" on Monday evening,
with copy unchanged since the day they were added. Root cause was investigated live (D1 +
`morning_latest.csv` queried directly, not inferred) before any fix was proposed. Full
back-and-forth is in this session's chat; this doc is the durable record.

## Naming note

The first draft of this plan used placeholder labels **WS-A/B/C** — pure shorthand for "three
workstreams," not tied to any tracking scheme, and a mistake given this repo already has a
live naming convention (`WS5-8b-*`) for this exact feature area. Renamed here to
**WS-POSITIONS-***, per owner request, and cross-referenced against the existing `WS5-8b-*`
SPRINT rows rather than replacing them, since other docs/session-notes already cite those IDs
by name and renaming an existing tracked ID would break that trail.

| This doc | SPRINT.md row | Status |
|---|---|---|
| WS-POSITIONS-STATUS | new row, this PR | Build now |
| WS-POSITIONS-SEED | new row, backlog | Hold off (owner decision) |
| WS-POSITIONS-MONITOR | supersedes/refines existing `WS5-8b-MONITOR` | Backlog, scope revised |

## Live findings (verified against production, not inferred)

Queried directly via Cloudflare D1 API and the committed `morning_latest.csv` during this
investigation:

- The 5 tickers were created **2026-08-22 ~17:49–17:50 UTC** (Saturday afternoon ET), not
  "20 hours before" as originally estimated by the owner — the actual gap was closer to 52
  hours by the time this was reported.
- `watchlist_tick_log` had exactly two rows: `2026-08-21` (before these tickers existed) and
  `2026-08-24` (the only tick that could have touched them). The TTL counter reaching 9 proved
  only that a weekday passed — **not** that any per-ticker read succeeded. (This was asserted
  as "reassuring" earlier in the investigation and that was wrong — flagged and corrected
  mid-session.)
- Today's (2026-08-24) `data/picks/sessions/morning_latest.csv`, written by `collect_morning.py`
  at `10:06:57Z`, **did** contain a row for all 5 tickers with `list_category=watchlist`,
  `status=no_quote`. Copy shown for that status: *"Morning feed missed this ticker — shown
  explicitly, never silently dropped."*
- `ticker_quotes` (D1) **did** get a real bar dated `2026-08-24` for all 5 tickers, landed by
  the 17:30 ET held-feed run — after the 10:05 ET `collect_morning.py` run had already executed
  and written `no_quote`.

**Conclusion:** nothing was "missed." The 10:05 ET run genuinely ran before any bar existed for
tickers with zero trading history — `no_quote`'s copy is just wrong for that case. This is
distinct from, but related to, the actual 2026-08-20 incident (`WS5-8b-OPS`, already fixed) where
the watchlist union silently never ran due to missing secrets.

## Staff-level review (Opus subagent, requested explicitly to pressure-test the draft plan)

Everything in this section is the reviewer's finding, not this document's opinion — kept
separate from the "chosen approach" section below so it's clear which claims were externally
verified vs. which are this session's judgment call.

1. **The original WS-A design was wrong about what it could deliver.** FMP's `/stable/quote`
   endpoint returns the *current session's own running intraday OHLC*, not a prior completed
   session. Seeding that as `prior_high` would set `trigger = today's own high` and compare it
   against today's own price — a self-comparison that can manufacture a false `triggered`
   status. An EOD-history endpoint (last N completed bars) would be needed instead — a
   different call, different response shape, not validated in this pass. Best case even then:
   seeding saves **one trading morning**, not "instant."
2. **A same-day path already exists and was missed.** `preclose_status` at 15:30 ET reruns the
   identical `collect_morning.py --session pre_close` engine. A ticker seeded with a correct
   *prior*-session bar would get a real read that same afternoon via this existing job — no new
   evening job needed.
3. **Real correctness risk if WS-POSITIONS-SEED is built as originally scoped.**
   `ticker_quotes` is `ON CONFLICT(ticker, trade_date) DO UPDATE` — the held feed only ever
   writes *today's* date, so a seed stamped with a past date would never be overwritten and
   would permanently sit in a table `advance()`/`sweep()` also read for real positions, with
   `atr`/`sma20` null (FMP quote has neither). There's no provenance column today to distinguish
   Finviz-sourced bars from a seeded one. **Also independently caught:** `advance.js` documents
   `sma50` in this table as a **%-distance from price**, not a level (see `advance.js:14` /
   root `CLAUDE.md`'s deltas.csv section) — FMP's `priceAvg50` is a level, so a naive passthrough
   mapper would corrupt every downstream read of that field, not just watchlist ones.
4. **WS-C (monitoring) was over-scoped in the wrong direction.** A separate GH Actions step
   that logs a warning and exits non-zero has the same silent-failure shape as the original
   incident — a step that never runs (missing secret) exits 0 and nobody notices, again. The
   healthchecks.io dead-man's-switch, pinged only on a positive assertion, is the part that
   actually closes the loop and should be built first, not as a "fast-follow."
5. **Missing from the original plan entirely:** `sessions_remaining` decrements every weekday
   regardless of whether a given ticker's pipeline produced any real read that day — 2 of these
   5 tickers' 10 "mornings" were already consumed with zero information delivered, and nobody
   had flagged that as a bug.

**Verdict:** ship with changes — B1+B2 (status honesty) first, WS-POSITIONS-SEED held pending an
EOD-history endpoint + a `source` provenance column, WS-POSITIONS-MONITOR reduced to the
dead-man's-switch as the primary mechanism.

## Chosen approach (this session's judgment, informed by the review above)

### WS-POSITIONS-STATUS — build now, this PR

Two changes, shipped together because B1 alone leaves `no_quote` meaning two different things
(exactly what caused the original 2026-08-20 incident to go unnoticed):

- **B1 (client):** `docs/index.html`'s `watchCardHtml()` currently has exactly two states —
  "no bar, still Adding" and "real status." Split the second into two: a bar can now exist in
  `ticker_quotes` (live via `GET /watchlist`) hours before `collect_morning.py`'s next run has
  had a chance to classify it, and that interim state deserves its own honest copy and pill
  instead of falling through to whatever `pub.status` happens to say.
- **B2 (backend):** `/watchlist-tickers` (`worker-positions/src/watchlist.js`) gains
  `has_history: boolean` (cheap — it's the same `q_trade_date != null` check `refsFromRow()`
  already does). `collect_morning.py` threads it through `build_watch_levels()`.
  `pick_status.compute_pick_status()` gains an optional `has_history` param: when the existing
  missing-inputs gate would fire and `has_history is False`, return a new
  `STATUS_AWAITING_FIRST_READ` instead of `STATUS_NO_QUOTE`. Default `None` (every picks caller)
  preserves today's behavior byte-for-byte — same pattern already used for `ref`/`STATUS_RECLAIM`.

`no_quote` goes back to meaning what its copy says: an established ticker Finviz actually
missed. That distinction is also the precondition for WS-POSITIONS-MONITOR to mean anything.

### WS-POSITIONS-SEED — held off (owner decision, this session)

Not built this PR. Before it's picked up, per the staff review: confirm an FMP endpoint that
returns a genuine prior-session bar (not the running intraday quote), add a `source` column
migration to `ticker_quotes` so a seeded row can never silently masquerade as a Finviz-sourced
one for `advance()`'s stop/ATR math, and wire it to land ahead of the *existing* 15:30 ET
pre-close pass rather than inventing a new evening job. Reframe the pitch honestly: this buys
one trading morning, not zero wait.

### WS-POSITIONS-MONITOR — backlog, absorbs/refines `WS5-8b-MONITOR`

`WS5-8b-MONITOR` (SPRINT.md, raised 2026-08-20) already named this gap generically. Refined
scope per the staff review: build the healthchecks.io dead-man's-switch **first**, pinged only
when a post-run check asserts something positive (e.g. "N active watch tickers, M resolved to
a real level or a genuine no_quote — zero unexpectedly stuck on awaiting_first_read past 1
session"), not a stderr warning that can itself go unnoticed the same way the original bug did.

### Also tracked, not previously flagged

TTL burn during "Adding"/"awaiting_first_read": `sessions_remaining` currently decrements every
weekday a watch entry is active, regardless of whether it ever produced a real read that day.
Not fixed in this PR — flagged as a real, separate bug (see SPRINT.md `WS-POSITIONS-TTL-BURN`).
