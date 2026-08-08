# ADR-013 — WS3 morning confirmation surface: status engine, provisional store, quote scrape

- **Status:** Accepted (staff decision, 2026-08-08). Implementation not started.
- **Scope:** WS3 (#262) and, by reuse, WS3b (#268). First provisional-store writer under
  ADR-011 Option C.
- **Reading order:** roadmap § WS3 → alignment § 10 → issue #262 (+ owner comment) →
  `planning/mocks/trade-lifecycle-surfaces.html` (WS3 section) → **this ADR** → phase PRs.
- **Supersedes:** nothing. Resolves the open decision points raised in the 2026-08-08
  senior-eng WS3 assessment so implementation can proceed without further sign-off.

## Context

WS3 tags each **prior-session pick** with one of six states at ~10:05 ET (Triggered /
Setting-up / Gapped-through / Failed-breakout / Invalidated / No-quote) and surfaces them in
the PWA. Dependencies WS1 (#258/#259) and WS2 (#261, `scripts/session_config.py`) are merged.
WS2 deliberately shipped identity-only — WS3 is the **first** thing that writes a provisional
session store, so its store/schema/scrape decisions set precedent for WS3b and WS5. Every EOD
pick row already carries the reference levels (`High` = trigger, `Low` = planned stop, `Open`,
`Prev Close`, `ATR`, `Earnings`, SMAs) — the only missing input is a live morning quote for a
fixed ticker set (~225 unique tickers/day as of 2026-08-07).

The decisions below were seven open questions. They are now closed. Do not re-litigate them
inside implementation PRs; if reality contradicts one (e.g. the live probe fails), amend this
ADR first.

## Decision 1 — No further design gate; this ADR is the design doc

WS3 gets this ADR, not a separate `planning/` doc plus a review cycle. The state machine,
store schema, and scrape mechanism are fully specified here; the mock is the visual spec.
Rationale: the WS1/WS2 "ADR before code" pattern is honored, but a second waiting-on-review
round would idle the workstream for a document that would say what this one says.

## Decision 2 — Morning quote source: Finviz screener `t=` ticker filter, batched

Use the existing screener endpoint filtered to an explicit ticker list:

```
https://finviz.com/screener.ashx?v=151&t=TICK1,TICK2,...&c=1,81,86,87,88,65,66,49,67
```

- Column ids from `data/picks/screener_config.json` `wide.columns` (the label→id SSOT):
  `1=Ticker, 81=Prev Close, 86=Open, 87=High, 88=Low, 65=Price, 66=Change, 49=ATR, 67=Volume`.
  This **narrow, purpose-built column set** is the morning config — do NOT reuse the 84-column
  wide block; the morning scrape needs 9 fields and a smaller surface is less brittle under
  Finviz header drift. Store the narrow set as a new `morning` block in `screener_config.json`
  (same shape as `wide`), so `collect_picks.py`-style label validation reuses one mechanism.
- **Batching is mandatory, not optional:** ~225 tickers/day. Chunk the ticker list into
  batches of ≤ 50 per URL (URL-length safety) and walk `&r=` pages within each batch
  (PAGE_SIZE=20, same pagination walk as `probe_picks._scrape_group`). Reuse
  `probe_picks._parse_table` (it already handles the avatar-markup ticker-anchor gotcha).
- **Build it as a shared pure-ish component from day one:** `fetch_ticker_quotes(page,
  tickers) -> list[dict]` in the new morning script (extract to its own module the day WS5
  needs it — a function is the shared component; do not build a "quote service"). WS3b and
  WS5's held-tickers feed call the same function. This closes the "WS3-narrow vs shared feed"
  question: shared function now, shared module later, no extra architecture.
- **Verification path (the one genuinely unverifiable-from-cloud item):** Cloudflare blocks
  headless Chromium from cloud-session IPs, so the first live validation runs on GitHub
  Actions (Azure IPs). Phase B's first slice is `collect_morning.yml` shipped
  `workflow_dispatch`-only with a `--dry-run` flag (scrape + parse + log row counts, no
  write); the cron job is enabled only after one clean manual run. Owner can also eyeball the
  sample URL above in a normal browser — if it renders a table with Prev Close/Open/High/Low
  for those tickers, the mechanism is confirmed. (Owner direction 2026-08-08: assume the `t=`
  link works; the dry-run exists to catch field-population surprises at 10:05, e.g. whether
  High/Low are intraday-fresh, not to re-debate the mechanism.)

## Decision 3 — State machine: exact predicates with explicit precedence

Inputs per ticker: prior-session pick row (`trigger = prior High`, `stop = prior Low`,
`atr = prior ATR`) and morning quote (`price`, `open`, `high`, `low` — today's values).
Single-snapshot semantics; evaluate top-down, **first match wins** (the predicates overlap,
so precedence is part of the spec, not an implementation detail):

| Order | State | Predicate |
|---|---|---|
| 1 | `no_quote` | quote row missing, or any of price/open/high/low unparseable |
| 2 | `invalidated` | `price <= stop` |
| 3 | `gapped_through` | `open > trigger` |
| 4 | `triggered` | `price >= trigger` |
| 5 | `failed_breakout` | `high >= trigger` (and, by falling through 4, `price < trigger`) |
| 6 | `setting_up` | everything else |

Notes locked here:
- **Invalidated outranks everything with a quote** — a name whose *current price* is at or
  below its planned stop is dead even if it tagged the trigger earlier the same session. This
  is the conservative, correct read: the thesis is broken right now.
- **Gapped-through outranks Triggered**: `open > trigger` means no entry near the trigger was
  available — that's the chase-risk case even though `price >= trigger` also holds. Triggered
  therefore implies `open <= trigger <= price` — a genuine intraday break of the level.
- **Failed-breakout and the deferred "whipsaw" are structural mirror images** (owner insight,
  2026-08-08). Failed-breakout = price *poked above the trigger* (`high >= trigger`) and fell
  back below it — an upside poke-and-fail, which v1 **does** detect. The whipsaw is the exact
  reverse on the downside: price *poked below the stop* (`low <= stop`) and recovered above it.
  v1 does **not** surface that reverse case as its own state — that is the single deferred piece.
- **Invalidation is on `price` (current), not `low` — and this is NOT under-reporting.** Do
  not "fix" it to `low <= stop`. Reasons, in order of weight:
  1. **It would over-report, not correct an under-report.** The owner's stops are close-based /
     discretionary, not hard intraday stops. At the 10:05 snapshot an intraday wick that dipped
     below the stop and recovered has **not** actually stopped the trade out, so `price <= stop`
     (where the stock *is now*) is the accurate "are you out?" test. `low <= stop` (did any wick
     touch it) would flag as *dead* many trades that are perfectly alive — the worse error for a
     decision surface.
  2. **It conflates two distinct states.** "Currently dead" and "wicked-your-stop-and-recovered"
     are acted on differently; folding the second into Invalidated erases that under one red label.
  3. **A 10:05 `low` is a partial-session low** — it can only fall further by the close, so a
     provisional `low <= stop` call is a claim the settled EOD data may not support, shown with
     the same amber "not settled" chrome but reading far more damning than a mid-morning wick is.
  4. **The correct surfacing is a separate future annotation** ("wicked stop, recovered"), not a
     broadening of Invalidated. Until that state is designed, the honest v1 behavior is to let
     `price` speak. Anyone tempted to change `price <= stop` to `low <= stop` reads this bullet
     first and, if still convinced, amends this ADR — not the code alone.
- `ATR_from_LoD = (price − low_today) / atr_prior`, computed only for `triggered` and
  `gapped_through` (mock: entry-quality gate, meaningless elsewhere). Display thresholds
  (owner-set 2026-08-08): `<= 0.8` clean entry (ok to act), `> 1.0` chasing, `0.8 < x <= 1.0`
  caution — these are PWA display constants and land in `docs/index.html` + `docs/CLAUDE.md`'s
  threshold table per house rules.
- The function is **session-agnostic by contract**: signature takes levels + a quote, never
  reads clocks, files, or session names. WS3b calls it verbatim with a 15:30 quote against
  *today's* setups. Name it `compute_pick_status` in a new `scripts/pick_status.py` (pure
  module, no I/O — mirrors `picksGate.js`'s pure/impure split).

## Decision 4 — Provisional store: committed CSVs under `data/picks/sessions/`

```
data/picks/sessions/morning.csv          # append-only history, keyed (date, ticker)
data/picks/sessions/morning_latest.csv   # latest date's rows only (PWA fetch target)
```

- **Committed to the repo (not ephemeral).** The PWA is static GitHub Pages reading raw
  CSVs — an uncommitted store would need net-new serving infra just to be visible. The
  privacy argument that pushes WS5 positions to D1 does not apply: morning quotes of public
  picks are public data. WS3b adds `pre_close.csv`/`pre_close_latest.csv` beside it for free.
- Schema: `date, session, collected_at, ticker, group, list_category, trigger, stop, atr,
  price, open, high, low, change, status, atr_from_lod`. The `session` column is redundant
  with the filename **on purpose** — rows stay self-describing when concatenated across
  sessions, per `session_config.PROVISIONAL_KEY_PREFIX` `(date, session, <entity>)`.
- Writer calls `session_config.assert_provisional(session)` at the write boundary — this is
  the enforcement point WS2 built the guard for; the first writer must actually use it.
- Same dedup convention as `picks.csv`: last-write-wins per `(date, ticker)` within the file;
  `collected_at` (ISO 8601 UTC) not part of the key.
- **Non-trading-day semantics differ from `collect.py` — do not copy `trading_date()`
  rollback.** A morning run on a weekend/NYSE holiday must **exit 0 without writing**
  (there is no live session to snapshot; rolling back would re-stamp yesterday). Also guard
  the input: the max `date` in `picks_latest.csv` must be **strictly before** today's ET
  date — if it isn't (or picks are stale by > 5 sessions), exit loud without writing rather
  than tagging the wrong day's setups.

## Decision 5 — "I took it" ships visible as a local-state marker, not a dead stub

Neither of the binary options (invisible until WS5 / visible no-op) is right. v1 behavior:
tapping "I took it →" on Triggered/Gapped-through sets a per-`(date, ticker)` flag in
`localStorage` and flips the button to a "✓ Taken" state. No position engine, no D1, no sync.
Rationale: it matches the committed mock, builds the habit loop the owner asked for, is
honest (state visibly persists), and gives WS5 phase 1 a seed to migrate ("found N locally
marked entries — import?"). A button that does nothing erodes trust in every other button.
Copy under the ✓ state: "Position tracking arrives with the lifecycle engine." Keep the
localStorage key shape `taken:<date>:<ticker>` and document it in `docs/CLAUDE.md` so WS5
can find it.

## Decision 6 — Phasing: three PRs, docs ride each PR

- **Phase A** — `scripts/pick_status.py` (pure status engine) + store writer skeleton
  (`scripts/collect_morning.py`: load picks_latest → compute statuses from a quotes list →
  write store; scrape function present but exercised via fixtures) + tests. Fully in-cloud
  verifiable. This is the WS3b-reused core.
- **Phase B** — live scrape wiring + `collect_morning.yml` (`workflow_dispatch` + dry-run
  first, then enable cron) + worker-cron `collect_morning` job at **10:05 ET, Mon–Fri,
  ungated,** standard 30-min self-heal window in `routing.js` `JOB_SCHEDULE` (+ KV key
  `last_dispatch_collect_morning`, tests). **10:05 ET (owner-set 2026-08-08), not 09:45** —
  it leaves at least one full 30-minute candle after the 09:30 open, so the intraday High/Low
  the state machine reads are a real session range, not a one-tick print at the open. No
  picks-style dependency gate needed: the input (yesterday's committed picks) already exists at
  dispatch time; the stale-input guard in Decision 4 covers the failure case. Late self-heal
  dispatch (up to ~10:35 ET) is acceptable — the store records real `collected_at` and the PWA
  displays it.
- **Phase C** — PWA "Morning check" surface, built **verbatim against the mock's WS3
  markup** (severity stripe + pill, provisional banner + amber tint non-negotiable per
  ADR-011, actionability sort Triggered → Gapped → Failed → Setting-up → Invalidated →
  No-quote, ATR-from-LoD on actionable states only, Decision-5 button) + release triplet
  (`releases.json` + `sw.js` bump in the same PR, house hard rule) + `docs/CLAUDE.md`
  threshold-table rows + Guide/glossary entries.
- There is no separate docs phase: the 3-places rule and the release triplet bind each PR
  individually.
- Delegation (per owner's standing direction): Phases A/B implementation → Sonnet subagents
  against this ADR; Phase C markup is written from the mock by the lead (taste-sensitive),
  with Sonnet on the mechanical wiring/tests; all reviewed in the main loop before commit.

## Decision 7 — WS3b tracking

Already done — **issue #268 exists** (opened 2026-08-07). No action; the senior-eng question
is moot. WS3b consumes `compute_pick_status` + the `pre_close` store files and its own gated
job; it needs no further ADR unless its dispatch-time choice (15:30 vs the existing 15:50
collect) turns contentious.

## Consequences

- First `assert_provisional` call site exists; the ADR-011 invariant becomes enforced, not
  aspirational.
- `data/picks/sessions/` becomes the pattern for all provisional pick-adjacent stores; WS5's
  held-tickers quote feed reuses `fetch_ticker_quotes` but stores positions in D1 per ADR-012
  (different data class — private/mutable vs public/append-only).
- Risk accepted: the `t=` screener behavior at 10:05 ET (intraday High/Low freshness) is
  confirmed only at Phase B's dry run. If it fails, the fallback is per-ticker
  `quote.ashx?t=` scrapes (slower, same parse idiom) — amend § Decision 2 here if that
  happens.
