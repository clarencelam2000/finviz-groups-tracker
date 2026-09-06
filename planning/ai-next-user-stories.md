# AI-NEXT — user stories and acceptance criteria

**Status:** Ready for pickup. Written 2026-09-06 by the staff review pass, working backwards from
the owner's own usage (opens the Morning tab first, on a phone, ~10:10 and ~15:35 ET; acts on
`triggered` / `gapped_through` / `reclaim` rows; is annoyed by prose that restates a chip).
**Parent docs:** `planning/ai-llm-integration-proposal.md` (why, decisions) ·
`planning/ai-evidence-pack-schema.md` (the contract) · `.session/SPRINT.md` (task rows).
**Rule:** a SPRINT task is Done only when every AC below for it passes. AC are written to be
checkable by someone who did not build the feature.

The persona throughout is **the owner** — a single swing trader running this system on their own
account. There are no other users; "the user" and "the owner" are the same person.

---

## Epic story

> As a swing trader who already gets deterministic status chips, I want the app to *reason over
> my own rows* — what changed since the morning read, what argues against the name I like, what
> pattern runs across today's invalidations — so that the 10 minutes I have at 10:10 and 15:35 go
> to decisions, not to re-deriving what the numbers say.

Non-goals that hold for every story: the model never writes a number on screen (slot filling);
the model never changes a stop, a status, or a position (engine decides, LLM explains); no forced
prose where nothing happened (silence convention).

---

## US-P0a — Pack builder, registry, validator (no UI)

**Story.** As the engineer building any AI surface, I want one pure-Python module that turns a
row (or a session) into a typed evidence pack and validates model output against it, so every
surface gets grounding, provenance, and tests for free.

**Acceptance criteria**
1. `python scripts/evidence_pack.py --emit-schema` writes `data/ai/pack_schema.json`; a test fails
   if the committed file differs from the generated one.
2. `build_morning_card(row, prior_row, group_row, context)` returns a pack matching schema §2.4
   for a fixture row; every emitted field id is in the registry; an unregistered id raises.
3. `build_morning_triage(session_rows, prior_rows, context)` returns `derived.*` aggregates that
   match a hand-computed fixture (counts per status, count changed, median extension of
   invalidated rows).
4. `canonical(pack)` is byte-stable across calls; `pack_hash` changes when any field value changes
   and does not change when `meta.generated_at` changes.
5. `validate(response, pack)` has one test per rule in schema §3.1, plus the lexicon case
   (`"reclaimed the 20MA"` passes; `"up 3 sessions"` fails), the `slots → context:` rejection, the
   per-surface cap, the unknown-kind drop, and the "missing catch drops the card" rule.
6. A statement citing a `v: null` field is forced to `confidence: low` regardless of the model's
   value.
7. Derived formulas for `sma20_dist`, `sma50_ext_atr`, `pct_of_52w_high` are asserted against the
   same fixture values the PWA's ATR-extension test uses (find or add that fixture; do not
   eyeball).
8. `python3 -m pytest tests/ -q` green; no change to any ground-truth CSV.

## US-P0c — Structured-output spike

**Story.** As the tech lead, I want measured evidence that `gemini-3.5-flash` can hold the
`text + slots + cites` contract on real Morning rows before anyone builds a renderer on it, because
this repo already tried forced JSON mode once and backed it out.

**Acceptance criteria**
1. ≥50 real `morning_card` packs built from historical `morning.csv` / `pre_close.csv` rows,
   spanning all actionable statuses and at least 10 status-changed rows.
2. Each sent with `response_schema` set, through the P0a validator with retry-once; the run records
   per-call: validated first try / validated after retry / dropped, and latency.
3. Same set run batched (5, 10 rows per call) to measure whether batching holds the contract.
4. A knowledge note `knowledge/investigations/ai-next-structured-output-spike.md` records the
   rates, the decision against schema §3.2 thresholds, three example outputs (good, retried,
   dropped), and the projected wall-clock for a 40-row session under the chosen mode.
5. Outcome is written into SPRINT `AI-NEXT-P0c` and, if the fallback path is taken, the schema doc
   §3 is amended in the same PR.

## US-P0b — Shared renderer

**Story.** As the owner reading any AI sentence, I want every number in it to be formatted exactly
like the chip next to it, and I want "ⓘ Behind this" to show only what the sentence used.

**Acceptance criteria**
1. `renderStatements(statements, pack)` fills `{slot}` by unit: `usd` → `$184.20`, `pct` → `+3.4%`,
   `atr` → `0.8 ATR`, `x` → `2.1×`, `sessions` → `1 session` / `6 sessions`, `enum` → the `d`
   string, `null` → `—`.
2. Drawer lists cited `fields` as `label: value` and `context:` cites as the block label plus row
   count (or the single row for a `#row` cite); never the full `context` payload. Verified in
   Playwright by counting rendered rows against a fixture that has 144 context rows.
3. `low` confidence renders the agreed marker (variant per owner); `medium` / `high` render
   nothing.
4. No surface is wired yet; no `releases.json` entry (nothing user-visible).
5. New Playwright test file is added to the `tests.yml` `--ignore=` list in the same PR.

## US-P2a — Morning pipeline

**Story.** As the owner, when I open Morning at ~10:15 or ~15:35, I want the AI read to already be
there for the rows I would act on, without waiting for the EOD run.

**Acceptance criteria**
1. A new workflow cascades off `Morning Status` and `Pre-close Status` (`workflow_run`,
   `conclusion == success`), in the `finviz-data-commit` concurrency group, with `AI_CAPTURE=1`.
2. Row scope is exactly: status ∈ {`triggered`, `gapped_through`, `reclaim`} **or**
   `status != prior session status` (for `morning`, prior = previous day's `pre_close`; for
   `pre_close`, prior = same day's `morning`). `setting_up` / `invalidated` rows with no change get
   no call.
3. Output lands at `data/ai/morning/YYYY-MM-DD.{morning,pre_close}.json` with `{meta, cards,
   triage}`; the packs land under `data/ai/provenance/morning/` (Tier 1). `index.json` gains
   per-date `rejected_statements` / `rejected_cards`.
4. Shared context (all session rows + 144 industries) is a byte-identical prompt prefix across the
   run's calls (assert on the Tier-2 capture).
5. Measured end-to-end: prose committed **≤10 min** after the read's `collected_at`, on three
   consecutive trading days, recorded in the PR.
6. `DailyQuotaExhaustedError` aborts fast and leaves a partial file that a re-run resumes.
7. A `morning`-session run that finds no in-scope rows writes a file with empty `cards` and a
   `triage` that says so — never an error, never a missing file.

## US-P2b — Morning per-card read

**Story.** As the owner looking at a `triggered` card at 15:35, I want one sentence on what changed
since 10:05 and one sentence on what argues against taking it, so I can decide before 15:50.

**Acceptance criteria**
1. In-scope cards show `read` then `catch`, below the existing status chips; out-of-scope cards
   are unchanged (`_mNote()`).
2. The card says which session the prose came from ("15:30 read") and the 10:05 → 15:30 change
   is explicit when `derived.status_changed` is true.
3. Every number in the prose is a filled slot; a Playwright test asserts the rendered price equals
   the row's `price` column formatted by the app's existing formatter.
4. "ⓘ Behind this" opens on each AI card and shows only the cited subset (US-P0b AC2).
5. If the day's file is missing or the card was dropped, the card renders exactly as today.
6. Fetched via `BASE` (raw.githubusercontent) — a Playwright route assertion, not a code comment.
7. Release triplet in the same PR: `docs/releases.json` entry (tab `morning`), `current` bumped,
   `sw.js` `CACHE` bumped; `tests/test_guide_releases.py` green.

## US-P2c — Morning triage summary

**Story.** As the owner, before I read any card, I want a ranked list of what's actionable today
and the one pattern across the rows that a lookup table can't see.

**Acceptance criteria**
1. One card at the top of Morning: ≤5 statements from the `morning_triage` pack, kinds `triage`
   (ranked names, tapping a name scrolls to its card via `subjects`), `pattern`, `catch`.
2. Aggregate numbers ("4 invalidated, median 2.7 ATR extended") are `derived.*` slots, not model
   arithmetic; the drawer shows them.
3. On a day with zero actionable rows the card says so in one line and shows no pattern.
4. Release triplet in the same PR.

## US-P1 — Picks thesis + catch

**Story.** As the owner scanning Focus, I want each of the top names to argue with itself — the
frozen reason it was selected, and the strongest reason not to take it — so a high Focus score
never reads as a recommendation.

**Acceptance criteria**
1. `picks_card` packs built from `picks_latest.csv` (uses `grp_*` attribution and the earnings
   column, which Morning lacks), top ~25 Focus rows.
2. `thesis` + mandatory `catch`; a pick whose `catch` failed validation renders **no** AI text.
3. No backtest number appears anywhere in the prose (honesty chip is dropped; see #404).
4. Same renderer, same drawer, same release triplet rule.

## US-P3 — The Brief (public half)

**Story.** As the owner opening the app, I want five lines at the top — regime, what changed, the
one action, the one non-action, what's uncertain — so the app leads with a decision, not a tab bar.

**Acceptance criteria**
1. `brief_public` pack built after the morning read; kinds `regime`, `action`, `non_action`,
   `uncertainty`, each capped at one statement; `regime` slot-fills the existing
   `rotation_phase` label.
2. Renders signed-out; a placeholder line marks where the personal half (P4/P5) will go.
3. Silence convention: on a day with nothing actionable, `action` may be "nothing to take today"
   — the `non_action` and `uncertainty` lines are still required.

---

## Definition of ready (for anyone picking up a task)

- The proposal §6 table and the schema §6 list are read; nothing there is re-asked.
- The task's SPRINT row and its AC above are read; the PR description lists the AC by number
  with pass/fail.
- Anything deferred from the task gets a SPRINT row or an issue **before** the PR is opened.
