---

## 2026-09-17 — Public agent feed (manifest + latest_signals) for external agents

**Status:** safe-to-close once PR is merged. Public-feed work landed; private-book access is deliberate fast-follow (see SPRINT § AGENT-FEED).

**Context:** Owner (Clarence) wants his Meta agent "Muse" to read the Finviz tracker directly. Repo is public (verified), so reads need no credentials. Decided against Muse consuming raw CSVs (118-col picks, generated delta schema → brittle coupling) in favor of a small, versioned JSON contract the pipeline publishes.

**What landed:**
- `scripts/build_signals.py` — pure builders `build_signals()` / `build_manifest()` + `main()`. Writes `data/api/manifest.json` (freshness, self-describing file index, history pointers, config constants: `atr_bands`, `lookback_windows`, `regime_short_long`) and `data/api/latest_signals.json` (`schema_version` 1.0, `as_of`, `session=eod`, `universe`, `emerging_leaders` top-15 by regime, `top_movers`/`fading` by `rank_ytd_delta_20d`, `picks` grouped by real `list_category` = leaders/all_green/accel/emerging/rs_new_high). ~80KB output.
- Wired into `collect.yml` (after evaluate_picks; existing `git add data/` catches it) and `collect_picks.yml` (after scrape; expanded `git add` to `data/picks/ data/api/` so the picks section is same-day fresh).
- `tests/test_build_signals.py` — 7 tests (shape/version, sort+NaN drop, movers/fading split, picks-by-category with raw ATR + NaN passthrough, manifest index/config, empty-frame safety, main() writes valid JSON). Full non-playwright suite green (123 passed).
- Docs: README § Agent feed (config table), CLAUDE.md scripts table + data/api/ in the data-structure block.

**Design decisions (grounded, not assumed):**
- **Privacy boundary:** feed is public-signals-only. Position/held/P&L status lives only in worker-positions D1 (HMAC bearer auth) and is NEVER written to a public file. Muse's proposed picks `status` field was dropped for this reason.
- **ATR band not persisted:** per data-pipeline.md, emit raw `atr_ext_50` + publish thresholds in manifest; consumer derives the band. Avoids stale labels on retune.
- **Two files, not one:** manifest = cheap freshness poll + index; signals = payload. Combining would drag the full payload on every freshness check.
- Corrected two of Muse's assumptions against real schema: `list_category` is selector buckets (not All/Focus), and `atr_ext_50` is per-ticker (not per-group).

**Next steps / deferred (SPRINT § AGENT-FEED):**
- Fast-follow: read-only authenticated endpoint on worker-positions (`GET /positions/summary`) + vaulted token for Muse, if/when owner wants position-aware answers. Security-sensitive; needs explicit sign-off. Prefer a narrow REST endpoint over handing Muse Cloudflare/wrangler account keys (blast-radius).
- Verify the two new workflow steps actually run green in Actions on the next scheduled collect (couldn't run collect.py in cloud — Cloudflare blocks it).

---

## 2026-09-06 — PR #412 review, fix, and merge (AI-NEXT-P0a evidence pack)

**Status: safe to close** — PR #412 merged to default; fixes verified with tests; one unrelated
pre-existing failure filed as its own issue rather than scope-creeped into the PR.

**What landed:** Code review of PR #412 (`scripts/evidence_pack.py` — the AI-NEXT-P0a evidence
pack builder/registry/validator) surfaced two confirmed bugs, both fixed and pushed to the PR
branch before merge:
1. `setup_present` ORed together two Finviz field groups with different coverage-cliff start
   dates (RSI/Volatility/RelVol/52W High from 2026-09-01 vs SMA20/SMA50/ATR from 2026-09-03).
   During that 2-day gap this wrongly emitted the still-missing SMA fields as `null` instead of
   omitting them, and skipped the required caveat note — contradicting the omitted-vs-null
   contract the PR itself documents. Fixed by splitting into independent `rsi_block_present` /
   `sma_block_present` flags, each gating only its own fields.
2. The confidence-downgrade "field flagged in notes" check used a raw substring test, so the
   field id `change` matched inside the routine no-prior-read note's "...what changed.",
   forcing every `row.change` citation to `low` confidence on the common case of a ticker with
   no prior read. Fixed with a word-boundary regex match.

Both fixes have regression tests (`tests/test_evidence_pack.py`, +3 tests, 49 total). Full
non-Playwright suite green (795/795) both before and after merge. `--check-schema` and
`--dry-run` (the PR's own "owner should verify after merge" commands) both confirmed passing
against the merged default branch.

**CI:** the `test` job's pytest suite was green throughout. Its later `eval_ai.py --all` step
failed on `data/ai/debug/2026-09-04.json` (`'Leisure' in output but not in input_blocks`,
`industries.note`/`industries.rotation_map`) — confirmed pre-existing and unrelated to PR #412
by reproducing it identically on the base branch with none of the PR's changes applied. Filed
as **#414** rather than pulled into this PR's scope; needs someone to inspect that capture file
and decide if it's a genuine hallucination or an `eval_ai.py` false positive.

**Notable finding for the owner:** while checking whether PR #412's `AI-NEXT-P0c` spike
(`scripts/spike_structured_output.py --limit 60`, real Gemini calls) could run from this cloud
session, found `GOOGLE_API_KEY` and `VERTEX_API_KEY` already present as env vars here —
contradicting the PR's (and `CLAUDE.md`'s Playwright-derived) assumption that Vertex creds are
never available in a Claude Code cloud session. Deliberately did **not** spend against them:
P0c's result is a recorded, hard-to-reverse decision (it selects the AI renderer design and the
owner explicitly wanted to paste its output into a knowledge doc). Flagged to the owner directly
and noted in the `AI-NEXT-P0c` SPRINT row; needs the owner to confirm the key is meant for this
before anyone runs it.

**Next steps:** (1) owner decides whether to authorize running `AI-NEXT-P0c` from this
environment or run it themselves per the PR's original instructions; (2) someone looks at issue
#414's hallucination flag; (3) once P0c's drop-rate table lands, `AI-NEXT-P0b`/`P2a` unblock per
the SPRINT ordering.

---

## 2026-09-06 — AI-NEXT-P0c structured-output spike run (real API, owner-authorized)

**Status: safe to close** — spike run complete, decision recorded, a validator bug it surfaced
is fixed and tested, follow-ups tracked as issue #416.

**What happened:** owner explicitly authorized the spend (stated they hold ~$260 in Google API
credit expiring within days; not independently verified which billing account the in-session
`GOOGLE_API_KEY` draws from, taken on the owner's word) to run the real `AI-NEXT-P0c` spike — 60
real `gemini-3.5-flash` calls through
`scripts/spike_structured_output.py --limit 60`, using the `GOOGLE_API_KEY`/`VERTEX_API_KEY`
found present in this cloud session (see prior session-notes entry). Ran to completion (~55 min
wall clock, unusually slow per-call latency — see below).

**Headline result:** raw harness output said 90% dropped / 3.3% first-try, selecting
**renderer-owned templates** (the >15%-drop-rate design: AI picks the situation, app writes the
sentence). **Before accepting that number, re-inspected the two "first-try" successes against
their raw output and found both were actually malformed** — the model had written the field id
directly into the response text (e.g. `{row.status}`) instead of a short name mapped through
`slots`, and a gap in our own validator's regex (`_SLOT_RE` didn't match dots) let it slip
through undetected. Fixed `_SLOT_RE` in `scripts/evidence_pack.py` to also recognize dotted
field ids as placeholders, added a regression test, verified against the two real raw responses
that they now correctly get rejected. Corrected true result: **0/60 clean first-try passes**, not
2/60. The renderer-design decision doesn't change (still far past the >15% cutoff either way),
but the corrected number matters for anyone reading this later. Full writeup:
`knowledge/investigations/ai-next-structured-output-spike.md` §4/§4.0/§6.

**Also found, independent of the drop rate:** median 141s/call, p90 289s — a naive serial
per-row loop over a 40-row morning session would take ~94 minutes, blowing the documented
≤10-minute budget regardless of which renderer design ships. Not root-caused (possibly SDK-level
retry-on-rate-limit rather than genuine model latency).

**Why the number might not be the model's ceiling:** the model got `cites` (a flat array) right
100% of the time and only failed the semantically-redundant `slots` object every time —
`RESPONSE_SCHEMA` doesn't structurally require `slots` to be non-empty, so nothing but prose
instructions asked for it. A schema restructure (e.g. `slots` as `{name, field}` pairs, same
shape as `cites`) followed by a small ~10-20 call confirmatory run might tell a different story.
Not run — flagged in issue #416, needs owner sign-off given API spend already used.

**Tracking:** `.session/SPRINT.md` `AI-NEXT-P0c` row marked Done with the corrected result;
issue #416 opened for the two follow-ups (schema-fix retest, latency budget). `AI-NEXT-P0b`/`P2a`
are now unblocked per the SPRINT ordering.

**Next steps:** owner decides whether the ~10-20 call confirmatory retest (issue #416, item 1) is
worth the remaining API credit before the expiry window closes; otherwise `AI-NEXT-P0b` (shared
renderer) is next in the SPRINT order.

---

## 2026-09-10 — AI-WALLET: protect Gemini spend before free-trial credits expire

**Status: safe to close** for the wallet core (5 commits, pushed, PR opened — backend only,
fully tested). Two user-facing PWA items deliberately deferred + tracked (see below).

**Why:** owner's $300 GCP free-trial credits expire within ~24h; after that spend draws on a
$10/mo Gemini credit **shared with other projects**. Measured the real bill from Tier-2
captures (29 clean runs): ~11 calls/run × **3 runs/day**, ~7k prompt + ~2.6k visible-output +
**~21k billed _thinking_ tokens/run**. Thinking bills at the output rate, so on
`gemini-3.5-flash` (~$9/1M out) that's **~$14–17/mo — exceeds the shared $10 alone.** (My first
pass wrongly called it "trivial" using a placeholder output price 20× too low; corrected with
real pricing via web search + the captured token metadata.)

**What landed (branch `claude/amazing-wozniak-vc8hwi`):**
1. `GEMINI_MODEL` 3.5→**3.8 Flash** — durably cheaper output, much cheaper during intro window
   (through 2026-12-31). API-safe (we never used the `minimal` level 3.8 dropped).
2. **`THINKING_LEVEL="low"`** — the big lever (~85% of the bill was MEDIUM-default thinking).
   Applied every call via `_build_call_config`, defensively (degrades to default, not outage).
3. **`AI_DISABLED=1` kill switch**, **`MAX_API_CALLS_PER_RUN=25`** runaway guard
   (`RunawayGuardError`, exit 1), **`DEFAULT_MAX_OUTPUT_TOKENS=2048`** anti-truncation rail.
4. **Actual-cost accounting:** `_extract_usage` now captures `thoughts_token_count` +
   `cached_content_token_count` + full `usage_metadata.model_dump()` (field names confirmed by
   introspecting the installed `google-genai`, not docs). New **`scripts/ai_cost.py`** meter
   (date-aware pricing incl. the 2027-01-01 intro→standard cliff) — **reused by AI-NEXT**.
   Per-run tokens+`cost_usd` logged to `ai_run_log.jsonl`; `data/ai/spend.json` = month-to-date.
5. **Input-diff dedupe** (`_compute_input_signature`) kills the EOD backstop's redundant 3rd
   run (~33%); also covers non-trading-day re-fires. No separate trading-day guard (unreachable).
6. Docs in 3 places (README / scripts CLAUDE.md / root CLAUDE.md).

Tests: 856 pass (full non-Playwright suite). ai_cost: 13 tests; generate_ai: +12 new tests.

**Owner to handle (GCP console, out of repo — owner said they'd do it):** billing budget +
**hard API quota cap** (the only real server-side stop; budgets only alert). Confirmed: the
expiring credit is the $300 trial, NOT the $10/mo (which survives).

**Deferred + tracked (both are `index.html` / user-facing → need real-browser verification not
reliable in this cloud session; see SPRINT AI-WALLET):**
- **AI-WALLET-PWA**: render `spend.json` at the bottom of the AI tab (owner's explicit ask — no
  Python dashboard). Backend data already ships; render is a small follow-up + release triplet.
- **AI-WALLET-CONVICTION**: remove the Conviction half of the `pulse` call (owner finds it
  unused; modest token save). Backend prompt/parser + guarded PWA render deletion + release triplet.

**Next:** do both PWA items in a follow-up PR with a browser check, then gate the AI-NEXT
expansion (60–90 calls/day) behind thinking_level + Batch API + the spend surface.

---

## 2026-09-08 — Emerging-bucket alpha: methodology riff + exec-brief comms skill

**Status: safe to close** — no code touched in the pipeline; this session produced a measurement
plan (SPRINT § EMRG-1..8), a communication skill, and one outstanding owner decision.

**What the owner asked:** is there alpha in the `emerging` picks bucket, and is
`scripts/evaluate_picks.py` even the right instrument? Explicitly wanted methodology discussed
before any code.

**Grounding measured (do not re-derive):**
- 62 trading dates in `data/industries/deltas.csv` (2026-06-09 → 09-04). The emerging gate is
  computable on **55** (needs `rs_score`, first non-null 2026-06-18).
- Gate (`regime_short_long > 0.15 & rs_score > 0.5`) fires on **393 group-days**; mean 7.1/day,
  range 3–16. Only **202** reach `picks.csv` — `EMERGING_SLOTS = 4` at priority 2.
- All **202/202** emerging rows genuinely pass the gate. **The backfill-contamination hypothesis
  is disproved** — `add_bucket_with_backfill` walks only the already-filtered qualifying pool,
  so it can never pad with non-qualifiers. 14 rows sit past natural rank 4; all 14 still pass.
  Don't re-open this.
- 77/202 emerging rows are multi-tagged (`emerging|rs_new_high` 29, `emerging|leaders` 15, …).
- `picks.csv` spans 49 dates across **three selector versions** (v1: 5, v2: 35, v3: 9), which
  `print_report` currently pools without splitting.

**Owner decisions taken this session (locked — do not re-litigate):**
1. **No waiting for a longer sample.** The owner's hypothesis is that signal efficacy is
   *regime-dependent* (a swing trader adapts style to a trending vs choppy tape). That
   reframes the problem rather than just the timeline: pooling more history across regimes
   yields an average true in no regime. Analyse *within* regime instead. My "wait until spring"
   argument was wrong on its own terms and was withdrawn.
2. **Bucket overlap is a feature, not contamination.** A group tagged by several buckets is
   "firing on more cylinders" — that's a candidate conviction/sizing signal (EMRG-6), not noise
   to isolate. The goal is deciding where to put money, not a clean experiment.
3. **Tradeability gap is out of scope.** The owner picks the strongest names inside a chosen
   group; the group is a heuristic pointer, not a position.
4. Terminology: "spike" in this project means a *research spike*, never a price spike.

**Real methodological findings that survived:**
- **Row-pooling bias.** `evaluate_picks.py` averages 393 rows, so a 16-qualifier day counts 16×
  and a 3-qualifier day 3×. Broad-signal days are likely strong-market days, so part of the
  measured "edge" is just market direction. Fix: collapse to one number per date
  (mean firing − mean non-firing) → a daily spread series and a cumulative equity curve, which
  also makes the regime hypothesis *visible* rather than statistical. (EMRG-2/EMRG-3.)
- **We grade the picker, never the signal.** Everything to date measures a 4-slot ranked
  selector on `picks.csv`, not the gate. Replaying from `deltas.csv` gives 393 obs instead of
  202 and starts a week earlier, with no slots/priority/version breaks. (EMRG-2/EMRG-5.)
- **The thresholds are unexamined.** `EMERGING_REGIME_FLOOR = 0.15` / `EMERGING_RS_FLOOR = 0.5`
  were picked, never tested. Owner flagged the **gradient/dose-response test as the highest-value
  item** (EMRG-4): daily quintile-sort all 144 groups by `regime_short_long`, forward return per
  bin. Shape → action: staircase means the threshold is just a dial; flat-then-jump means tighten
  it; flat means the variable is wrong; inverted means wrong side.
- **No negative control anywhere.** Nothing has ever checked whether the harness shows an edge on
  randomly-selected groups (EMRG-7). Cheap and highest-leverage-per-hour.
- **Execution-timing bias** (EMRG-8): picks publish 17:00 ET, post-close, but forward returns
  start `close(t)→close(t+1)` — an overnight gap we couldn't have traded. Likely only
  documentable; `snapshots.csv` has no opens.

**What landed in this PR**
- `.claude/skills/exec-brief/SKILL.md` — the owner's required communication style (headline
  first, one decision with a recommendation + cost-of-not-deciding, layered detail, three
  bullets not eight, pushback rules incl. "statistical rigour is not the goal, making money is").
  Written at the owner's request after this session's first two replies were, fairly, called out
  as information dumps.
- `CLAUDE.md` § Communication style — pointer so the skill applies by default, not only on
  explicit invocation.
- `.session/SPRINT.md` § Emerging-bucket alpha study — EMRG-1..8 with the locked framing and the
  "not doing" list, so none of the above lives only in chat.

**Blocker / next step.** **EMRG-1 needs an owner decision: how to define market regime**
(SPY vs its 20-day average / add a chop filter / the owner's own mental model). It's a trading
judgment, not a data question, and EMRG-3 can't start without it. EMRG-2, EMRG-4, EMRG-5,
EMRG-6 and EMRG-7 are all unblocked and runnable from a cloud session today — no Finviz access
needed, they read committed CSVs only.

**Follow-up in the same session — regime definition answered, EMRG-1 unblocked.**

Owner had no quantitative model, only chart-reading heuristics: time split above/below the 20SMA,
staying inside a 50d high/low range, MA slope, MACD-ish. Checked what the data can actually
support before designing anything:

- `data/benchmark/snapshots.csv` carries **only `perf_*` for SPY** — no price, no SMA, no 52W
  high/low. `SMA20`/`SMA50`/`52W High`/`52W Low` exist only in `picks.csv`, per *stock ticker*,
  and only from 2026-09-03.
- A synthetic SPY index compounds cleanly from `perf_day` (55 days, +3.93% total). But a 20SMA
  costs 19 warm-up days → **36 of 55 usable**; a 50d high/low leaves ~5. **The 50d-range
  heuristic is not viable on current history** — that's a data fact, not a judgment.
- Recommended substitute: **efficiency ratio** over 10 days (`abs(net move) / sum(abs(daily
  moves))`) — same "moving around but going nowhere" intuition, 9 days of warm-up instead of 19.
- Secondary source: cross-sectional breadth over the 144 industries (share with `perf_week > 0`),
  available on all 62 days. Mean 0.52, std 0.12, but **crosses 0.50 seventeen times in 62 days** —
  too noisy raw, needs smoothing.

**The better move, found while checking the above: July vs August is a natural experiment.**
July = SPY **+0.03% over 22 sessions** (textbook chop). August = **+2.67% over 21 sessions**
(trend). Two regimes of near-equal length already in the data. Split EMRG-2/EMRG-4 on the month
and the regime question gets a first answer with **no classifier at all**. Tracked as **EMRG-1a**,
and it demotes EMRG-1 from blocker to "build it properly only if EMRG-1a shows the split matters".

**Also extended `.claude/skills/exec-brief`** at the owner's request with six more executive-comms
rules: separate measured/inferred/guessed and always state what would change your mind; recommend
even when uncertain; flag one-way vs two-way doors so exec attention scales with reversibility;
give cost in time/money/risk rather than engineering units; bad news first; don't hand back
homework, and answer the obvious follow-up in the same message.

**Nothing is blocked now.** EMRG-1a, 2, 4, 5, 6, 7 all run from a cloud session against committed
CSVs.

**Second follow-up — owner rejected the month split; regime segmentation revised; issue #419 filed.**

Owner's correction (they are the domain expert on tape reading, and the data backs them): the
whole summer was chop. The only real thrust was **2026-07-28 → 08-14**, preceded by weakness
**07-14 → 07-28**. A July/August month boundary cuts straight through that thrust, so the month
split I proposed was wrong. **Verified their read independently** with a 10d efficiency ratio
(`abs(net move) / sum(abs(daily moves))` off `perf_day`): thrust segment **ER 0.51** vs 0.14 /
0.22 / 0.14 for the other three segments, and the **six most-trending 10d windows in the entire
sample all fall inside 07-28..08-14**. Eyeball labels and objective measure agree — neither is
fitting the other.

**The consequence reshapes the study:** only **~14 of 55 sessions are trend**. A binary
chop-vs-trend comparison is too lopsided to be worth running. Use the **continuous 10d ER as a
covariate** against the EMRG-2 daily spread instead — all 46 ER-available days contribute and no
bucketing is needed. Recorded in EMRG-1a.

**Filed #419 (P0): scrape all available SPY quote-page columns.** `scripts/collect.py` already
fetches the full SPY quote page (`.snapshot-table2`) and then discards everything outside a
7-entry `SPY_LABEL_MAP`. We have no Price, SMA20/50/200, 52W High/Low, ATR, RSI, Volatility or
volume for SPY — and **this is unrecoverable**, Finviz serves point-in-time only. Fetch cost is
already paid; the fix is widening the parse. Recommended capturing *every* label on the page
rather than another fixed allowlist. Owner approved the ground-truth schema change under
`.claude/rules/data-pipeline.md` on 2026-09-08 — the "compute it where it's consumed" escape
hatch cannot apply to data never captured.

**Third follow-up — EMRG-2/4/7/9 built and run. The headline result is not the one we expected.**

Owner asked for an Opus adviser review before building. Worth it — it found **two real arithmetic
defects** in the design, both fixed before any number was reported:

1. **Count-dependent gain.** `mean(fire) − mean(nonfire)` equals `N/(N−k) × (mean(fire) −
   mean(all))`. With k = 3..16 firing groups over N ≈ 144, that is a 1.02x..1.12x multiplier —
   and **k is itself regime-correlated** (more groups fire in a trending tape), so the complement
   form quietly amplifies exactly the days the regime analysis is about. Now subtracts the full
   cross-sectional mean; `fwd_nonfire_mean` retained for reference.
2. **Compound-then-subtract cross terms.** Differencing simple compounded returns leaves a
   market×spread term that does not cancel, inflating the spread whenever the market rose —
   biased in the same direction as the hypothesis. Now compounds in **log space** and converts
   back only for display.

Both were real; **neither moved the numbers much** (h=10 spread +0.60 either way), which is itself
worth knowing — the result is not an artifact of those bugs.

Adviser's leakage checks came back clean: the forward window starts at `pos+1` so the signal day
(already inside the gate's `perf_week`) is excluded, and `deltas.csv`/`snapshots.csv` have **0
duplicate (date, name) rows**, so last-write-wins already collapsed any pre-close/EOD ambiguity.

**Results (`scripts/analyze_emerging.py`, 54 dates):**

| h | spread (fire − cross-section) | pos% | random control | control pos% |
|---|---|---|---|---|
| 1 | −0.06 | 50% | −0.04 | 48% |
| 3 | +0.19 | 48% | +0.09 | 48% |
| 5 | +0.33 | 54% | −0.09 | 48% |
| 10 | +0.60 | 60% | −0.78 | 33% |

Gradient (excess vs same-day cross-section, by `regime_short_long` quintile) is **cleanly
monotone at h=5 and h=10** (h=10: −0.46 / −0.33 / −0.26 / +0.22 / **+0.87**) and **flat at h=1**
(−0.01 / +0.03 / −0.01 / −0.05 / +0.05).

**THE RESULT THAT MATTERS — fresh triggers are negative; the edge is entirely in stale streaks:**

| h | fresh (first day of fire) | n | stale (day 2+) | n |
|---|---|---|---|---|
| 1 | **−0.21** | 146 | +0.13 | 244 |
| 3 | **−0.49** | 143 | +0.63 | 232 |
| 5 | **−0.57** | 135 | +0.83 | 219 |
| 10 | **−0.19** | 122 | **+1.06** | 180 |

Negative at every horizon for fresh, positive at every horizon for stale. **This inverts how the
bucket is used** — the Picks surface highlights newly-firing groups, and new fires are where the
edge is not. Sign consistency across all four horizons in both cohorts is the notable part; the
magnitudes are not trustworthy at this n.

**Honest limits, per the adviser (do not overstate these numbers):**
- The trustworthy statistic is the **h=1 gradient shape**, pooled over ~7,900 group-days: no
  window overlap, no compounding trap, and monotonicity is a shape claim. It is currently **flat**.
- The **h=10 spread and the spread-vs-efficiency-ratio correlation are presentation-grade only**.
  ER has one high excursion (the 07-28..08-14 thrust), so that correlation is one episode sampled
  14 times, not 46 independent observations. Tracked as EMRG-10 (clustered SEs); until it lands
  the report prints **no p-values, t-stats or Sharpes** by design.
- The random control is not centred on zero at h=10 (−0.78, 33% positive), which is exactly what a
  negative control is for: it says the instrument has real noise at that horizon.

**Adviser recommended cutting EMRG-6 (tag-count).** Kept — it is the owner's own hypothesis, so it
will be reported descriptively and labelled underpowered rather than dropped. Noted in SPRINT.

**Next:** owner review of the fresh-vs-stale result. If it holds up, the obvious follow-on is
whether the Picks surface should be de-emphasising fresh fires — but that is a product change and
needs the owner's call, not an inference from 54 dates.

**Fourth follow-up — fresh/stale binary replaced by a streak dose-response. The finding got stronger.**

Turned EMRG-9's binary split into 4 buckets (`STREAK_BUCKETS` = 1 / 2-3 / 4-5 / 6+) and carried the
efficiency ratio onto every streak row so the table can be re-cut by regime for free.

**Excess return vs same-day cross-section, by consecutive-fire streak:**

| h | day 1 | day 2-3 | day 4-5 | day 6+ |
|---|---|---|---|---|
| 1 | −0.21 | −0.06 | +0.18 | +0.12 |
| 3 | −0.49 | +0.27 | +0.56 | +1.07 |
| 5 | −0.57 | +0.34 | +0.61 | +1.96 |
| 10 | −0.19 | +0.99 | +0.08 | **+2.38** |
| n | 146 | 132 | 64 | 48 |

**Day 1 is negative at all four horizons. Every later bucket is positive at h=3/5/10, and h=3/5/10
rise monotonically into day 6+.** A monotone dose-response is much harder to produce by chance than
the two-way gap it replaced, so this is a strengthening, not just a re-cut.

**Regime split (h=10, efficiency-ratio median 0.28):**

| regime | day 1 | day 2-3 | day 4-5 | day 6+ |
|---|---|---|---|---|
| choppier | −0.54 | +1.92 | −2.01 | +3.38 |
| trendier | −0.54 | +0.87 | +1.93 | +2.96 |

**Day 1 is −0.54 in BOTH regimes — identical.** That is the robustness result that matters: the
first-day penalty is not a chop artifact. The choppier day-4-5 cell (−2.01) is small-n noise;
don't read it.

**Main interpretive risk, tracked as EMRG-11 (do before any product change):** a group reaching
day 6 has by construction kept clearing both floors for six sessions — i.e. it kept performing. So
"streak 6+ outperforms" may be momentum rather than gate edge. It is **not** lookahead (streak
position is knowable on the day, forward window still starts at `pos+1`), so it stays tradeable
either way — but the story changes from "the gate predicts" to "persistence is the signal,
freshness is noise". Also worth checking whether stale-emerging is largely the `leaders` bucket
wearing a different tag. **EMRG-12** is the follow-on: express it as an actual entry rule and
backtest that rule head-to-head.

**Verification:** 24/24 tests in `tests/test_analyze_emerging.py`. Full suite **733 passed, 92
failed — all 92 confirmed `ModuleNotFoundError: No module named 'playwright'`** (the documented
sandbox limitation), zero assertion failures. Note this sandbox also started without `pandas`,
`pytest`, `bs4`, `lxml` or `pytz`; installing them is required before the suite will even collect.

**Fifth follow-up — the owner's pushback produced the session's actual finding, and five rejected framings are now written down.**

The owner pushed back hard on five separate framings, and was right on all five. Full record with
reasoning in **`knowledge/alpha-study-working-agreement.md`** — read it before any future
alpha/signal/backtest work; `CLAUDE.md` now points at it. Summary:

1. **"Wait for more data"** — rejected on better reasoning than the objection: if efficacy is
   regime-dependent, a longer sample spanning regimes averages to something true in no regime.
2. **"Isolate the buckets"** — rejected; overlap is a conviction signal ("firing on more
   cylinders"), the goal is deciding where to look, not a controlled experiment.
3. **"This might just be momentum"** — the worst of the five. **Momentum continuing IS the thesis.**
   Also: returns are measured strictly from the day after the signal, so there is no lookahead —
   the owner spotted this and was right that it settles the concern.
4. **Publication vocabulary** (p-values, "not yet powered", "case study not evidence") —
   *"I'm not submitting this to the Quant Trader Association."*
5. **Elevating h=1** because it is statistically cleanest — *"so are we day trading now?"*
   Correct. Measurement horizons follow the trading horizon; h=1 is not a swing trade. Reporting
   an adviser's statistical preference over the owner's actual holding period was the error.

**Reframing #3 comparatively produced the finding.** Not "is it momentum?" but "does our filter
find momentum better than a simpler filter?" Measured over 54 dates:

| Cut | Groups/day | 10-session excess | Days beating the average group |
|---|---|---|---|
| Deployed gate (`regime > 0.15` AND `rs_score > 0.5`) | ~7 | +0.60pp | 60% |
| Top quintile by `regime_short_long` alone | ~28 | +0.79pp | 73% |
| **Top decile by `regime_short_long` alone** | **~14** | **+1.27pp** | **71%** |

**The `rs_score > 0.5` floor is costing money on every day we have data for.** Twice the excess
return from the simpler, single-variable cut. Tracked as **EMRG-13**, now the highest-value open
task. EMRG-11 closed as mis-framed (do not re-open).

**Also landed:** `exec-brief` gains a mandatory worked-example rule (owner asked twice — every
concept gets concrete numbers, e.g. "Monday, 144 groups, 6 fire, they return +0.7% while the board
returns +1.2%, so the spread is −0.5pp: they made money, just less than buying everything"), a
"making money is the standard, not statistical rigour" section listing the banned framings, and a
rule that real caveats are stated once in plain language and never become the headline.

**Next:** EMRG-13 — sweep the cut-off at 5/10/15/20 names, confirm where the payoff peaks, and
check whether the day-1 penalty survives the simpler cut. Changing `EMERGING_RS_FLOOR` in
`scripts/picks_config.py` is a product change and needs the owner's sign-off first.

**Sixth follow-up — EMRG-13 done, and it turned into a much bigger finding than the question asked.**

Generalised the study into a **rule-comparison harness**: `scripts/analyze_emerging.py` →
**`scripts/analyze_signals.py`**, with a `RULES` registry and `--compare`. Any selection rule is
now scored against any other on identical dates and identical forward windows, so
*"should we drop Accel?"* / *"are Leaders giving us alpha?"* is **one command**, not a new study:

```bash
python3 scripts/analyze_signals.py --compare --horizons 5,10
python3 scripts/analyze_signals.py --compare leaders,top14_regime
```

Deployed buckets (`emerging`, `leaders`, `accel`, `rs_new_high`) import their floors from
`picks_config.py` so they track the live selector. Single-variable top-N baselines
(`top{5,10,14,20,28}_regime`, `_momentum`, `_mom_confirmed`, `_rs_confirmed`) are included on
purpose: **a multi-condition screen has to beat "rank on one column, take the top N" to justify
itself.** Without that baseline the emerging gate looked fine in isolation.

**Result — excess vs the day's average industry group, 10 sessions forward, 54 dates:**

| Rule | Picks/day | All | Thrust | Chop | Hit |
|---|---|---|---|---|---|
| `top5_regime` | 5 | **+1.72** | — | — | 54% |
| `top10_regime` | 10 | **+1.64** | +3.35 | +0.94 | 73% |
| `top14_regime` | 14 | +1.30 | +2.43 | +0.84 | 73% |
| `emerging` (deployed) | 7 | +0.60 | +0.79 | +0.51 | 60% |
| `accel` (deployed) | 18 | **−1.02** | −2.26 | −0.40 | 36% |
| `rs_new_high` (deployed) | 8 | **−1.36** | −3.43 | −0.39 | 41% |
| `leaders` (deployed) | 11 | **−2.00** | −1.56 | −2.16 | 31% |
| `top10_momentum` | 10 | **−2.69** | −2.06 | −2.93 | 25% |

**Three of the four deployed buckets lose money versus simply holding the average industry group
— in BOTH the thrust segment and the chop segment, so it is not a regime artifact.** Leaders is
the worst performer and holds the most slots (11 of the 27-name daily budget). Only
`regime_short_long` cuts are positive, and they are positive in both tapes.

`momentum_score`-ranked cuts are strongly negative — high-momentum groups mean-reverted over 10
sessions across this sample.

**Honest caveats (state once, don't bury the finding):** 54 dates with only 14 trending; and the
deployed buckets were scored *without* their slot caps and cross-bucket priority, so this measures
the rules rather than the exact 27-name list the selector emits. Neither flips any sign; both
affect how hard to lean.

**Tracked as EMRG-14 — a product decision, blocked on the owner's explicit sign-off.** Rebalancing
`picks_config.py` toward `regime_short_long` is not something to do off a measurement alone.

**Docs generalised so this doesn't get re-derived:** `knowledge/alpha-study-working-agreement.md`
gains a **Playbook** section (the one-command recipe, the two mandatory rules — always include a
single-variable baseline, always split by regime — and the full results table).
`CLAUDE.md` points at it from the communication-style section, so a future session asked
"are Leaders giving us alpha?" lands on the method and the prior results before writing any code.

---

## 2026-09-11 — AI-WALLET-PWA: render spend.json at the bottom of the AI tab

**Status: safe to close.** Follow-up to 2026-09-10's AI-WALLET-CORE (backend spend accounting)
— this closes the PWA half deferred there (see that entry below).

**What landed (branch `claude/ai-spend-controls-render-bpyfrk`):**
- `docs/index.html`: `SPEND_URL` (`${BASE}/ai/spend.json`), `state.spendData`, `loadSpend()`
  (fetched alongside the other `loadAndRender()` calls, best-effort — never blocks the render),
  and `spendSectionHtml()` — a small card rendered at the bottom of `renderAI()`'s output in
  **all three** of its exit branches (`_noData`, "AI analysis not yet available", and the normal
  briefing-cards path), since the spend card is account-wide, not tied to whichever AI date is
  being browsed. Shows month-to-date $ vs. `SPEND_SOFT_BUDGET_USD` with a color-coded bar
  (emerald/amber/red), run counts, last-run model/outcome/cost, and an "Updated Xh ago" caption.
  Going over budget shows red + an explicit "a display ceiling only, nothing is blocked" note,
  matching `SPEND_SOFT_BUDGET_USD`'s own doc contract (scripts/CLAUDE.md, root CLAUDE.md § AI
  spend controls) — it was never meant to be an enforcement mechanism. A missing/failed
  `spend.json` fetch (repo hasn't run `generate_ai.py` since AI-WALLET landed, or a network
  hiccup) silently omits the section — never breaks the rest of the AI tab.
- Release triplet in the same PR: `docs/releases.json` (`2026.09.11`, tag `feature`, tab `ai`)
  + `docs/sw.js` (`CACHE` v99→v100).
- `docs/CLAUDE.md` new § "AI tab — spend card"; README.md § AI spend controls updated to note
  the render now exists.
- **4 new Playwright tests** (`tests/test_pwa_ai_spend.py`, added to the CI `--ignore=` list
  per `.claude/rules/branch-commit-discipline.md`): normal render (all fields present), the
  over-budget red-warning state, silent omission on a 404, and rendering inside the "AI analysis
  not yet available" empty state (using the small `tests/fixtures/ai/*.csv` fixtures to force a
  controlled fallback date with no AI JSON). All 4 pass.

**Real-browser verification, done in this cloud session (the thing 2026-09-10 flagged as
needing "a real-browser check not reliable in a cloud session"):** installed `playwright==1.44.0`
+ pytest fresh (not preinstalled here), used the pre-installed `/opt/pw-browsers/chromium-1194`
via the documented symlink trick
(`knowledge/investigations/playwright-cloud-session-testing.md`) to run the committed test suite
headlessly, AND — beyond what that doc's harness does — fetched the **real** `cdn.tailwindcss.com`
script via `curl` (reachable from the shell even though not from Chromium directly, per that
doc's Root Cause 2) and served it through `page.route()` instead of the usual empty-comment
stub, so the visual (not just DOM-text) rendering could actually be screenshotted and eyeballed:
confirmed card styling, budget-bar color states (green under-budget / red over-budget), and
layout consistency with the rest of the AI tab's cards. Screenshots were scratch-only, not
committed.

**Next:** `AI-WALLET-CONVICTION` (remove Conviction from the `pulse` call) is the one remaining
item from the 2026-09-10 AI-WALLET backlog — still open, not touched this session.

---

## 2026-09-24 — Pre-Power of 3 MA-bunching band tightened to 1.5x ATR

**Status: safe to close.** Small, self-contained constant change requested by the owner.

**What landed (branch `claude/pre-power-of-3-atr-threshold-jdkalv`):**
- `POWER_OF_3_ATR_MULT` in `docs/index.html` lowered from `2.0` to `1.5` (the "Pre-Power of 3"
  MA-bunching chip fires when price/20MA/50MA all fit inside `POWER_OF_3_ATR_MULT`×ATR). Updated
  the triple-documented comment/README/`docs/CLAUDE.md` copies and the two affected test
  docstrings in `tests/test_pwa_picks_atr_earnings.py` (assertions themselves were unaffected —
  the ANET fixture's span (~5.6) stays under the new 1.5×ATR (~12.6) threshold).
- Release triplet: `docs/releases.json` (`2026.09.24`, tag `improvement`, tab `picks`) +
  `docs/sw.js` (`CACHE` v101→v102).
- `.session/SPRINT.md` Done entry `POWER3-THRESH-1` with the measured impact.

**Impact analysis (requested by owner), computed against the live `data/picks/picks_latest.csv`
(459 rows with valid Price/ATR/SMA20/SMA50) using a standalone script — not committed, one-off
verification:**
- At the old 2.0x band: 231/459 rows (50.3%) flagged as bunched.
- At the new 1.5x band: 150/459 rows (32.7%) flagged — **81 fewer flagged rows** (~35% relative
  drop from the 2.0x count).
- Also measured a 1.0x band for comparison (not shipped): 66/459 rows (14.4%) flagged — a further
  84-row drop from 1.5x, i.e. cuts the flagged pool by more than half again.
- Median span/ATR ratio among the previously-flagged (2.0x) rows was ~1.25, so most of the 2.0x
  pool sits comfortably under 1.5x too, but a real ~35% slice (spans between 1.5x and 2.0x ATR)
  drops out.

**Verification:** `python3 -m pytest tests/test_pwa_picks_atr_earnings.py -q -k power_of_3` — 2
passed (used the documented Playwright-in-cloud symlink workaround for the Chromium
headless-shell revision mismatch, cleaned up afterward — session-local `/opt` edit, not
committed). Full non-Playwright suite (783 tests) passes; the ~29 pre-existing failures
(`test_collect_benchmark.py`, `test_generate_ai.py`) are unrelated environment/mocking gaps in
this sandbox, not caused by this change. `tests/test_guide_releases.py` passes against the new
`releases.json` entry.

**No pipeline/schema change** — this is a pure client-side PWA display constant, computed at
render time from already-scraped Price/ATR/SMA20/SMA50, never a stored CSV column.

**Next steps:** none — this was a one-shot config tweak. If the owner wants to revisit the 1.0x
alternative later, the comparison numbers above are already captured in the SPRINT.md entry.

---

## 2026-09-04 — Inline "+ Watch" quick-add (Picks / Morning-picks / Lookup / Watchlist edit-level)

**Status: safe to close** — implemented, functionally verified with 6 new Playwright tests
(headless Chromium via the revision-symlink harness) plus the full non-Playwright suite (746)
and the existing watchlist/manual-entry/picks-hod/morning Playwright suites (42), all green,
no regressions. Release surface updated in the same PR.

**What the owner asked for:** easier ways to add a ticker to the watchlist — one-click entry
points across the app that expand inline instead of jumping to the Positions tab. Talked
through candidate spots first (no impl) before building: confirmed scope was Picks tab rows,
Morning tab's Picks-subtab cards, and the Lookup tab's ticker result (every spot that already
shows a TradingView chart), plus fixing the Watchlist-subtab's "Edit level" kebab, which had
the exact same jump-away problem. Positions-tab position cards were explicitly scoped out
(ticker's already a live trade there — low value).

**Design, confirmed with the owner before building:** the existing `state.watchAdd` /
`watchAddHtml()` / `watchAddApi()` (Positions-tab-only collapsible) already did ticker+optional
level submission — the gap was only that it was mounted in one place and other call sites
(`watchEditLevel`) navigated away via `switchTab('positions')` instead of expanding in place.
Generalized it into `quickWatchButtonHtml()`/`quickWatchPanelHtml()`, mountable anywhere via a
`mountKey` (namespaced per call site: `qw_pick_<key>`, `qw_morning_<ticker>`,
`qw_lookup_<symbol>`, `qw_watch_<ticker>`), DOM-patched by id on open/close/save (same
discipline as `__togglePickChart`/`__toggleMorningChart` — no full re-render, no lost focus).

**Owner-specified interaction (asked directly, confirmed before building):** tapping "+ Watch"
on an unwatched ticker fires the add immediately (`watchAddApi({ticker})`) — the tap alone
persists it, no second tap required. The panel then opens showing a receipt plus the optional
level-of-interest form (Above/Below/20MA/50MA, same as the existing form); setting a level is a
second, independent POST to the same upsert-by-ticker endpoint. An already-watched ticker's
button instead reads "✓ Watching" and opens straight into the level editor (seeded from the
existing entry), with zero re-POST until Save. Signed-out tap shows an inline sign-in nudge, no
add attempted. Unlike the Positions-tab form's free-text ticker field (which debounces an FMP
resolve lookup), every quick-watch mount is handed an already-known ticker — no resolve call
and no ticker input in this UI, per the owner's own observation that it's "clear which company
it is" at all three new spots.

**Technical note:** Picks and Lookup never previously triggered `loadWatchlist()` (only
Morning/Positions tab renders did), so a signed-in user landing on Picks would have seen
"+ Watch" on every row even for already-watched tickers. Added `ensureWatchlistLoaded()`
(deduped via `state.watchlistLoading`), called once per `renderPicks()` pass and once when the
Lookup ticker card renders — Morning needed no change, its batch loader already fetches
`watchlistData`.

**Release surface (hard rule, same PR):** `docs/releases.json` `2026.09.04` entry prepended,
`current` bumped; `docs/sw.js` `CACHE` bumped `v96` → `v97`.

**Next steps:** none outstanding — PR opened, ready for review.

---


## 2026-09-04 — Chart-toggle tap-target UX proposals + mock

**Status: safe to close** — design-only, no code shipped, nothing blocking.

**What landed:** Owner flagged the `Show chart ▾`/`Hide chart ▲` toggle on Lookup, Picks, Morning,
and Positions as a hard-to-hit mobile tap target (confirmed: `text-[0.65rem] px-2 py-1` pill,
roughly 34×24pt — under Apple's 44×44pt HIG minimum, tucked in one card corner). Proposed and
mocked five alternatives at real card scale (336pt width) using a live Picks row (`GH 86 ·
Guardant Health`) as content:
1. **Padded button** — same visible pill, bigger invisible hit-slop.
2. **Whole-row tap** — entire ticker header toggles the chart (Positions already half-does this
   on the ticker text alone).
3. **Drawer handle** — full-width strip replaces the corner pill.
4. **Live sparkline** — always-on mini chart doubles as the tap target.
5. **Edge rails** — the owner's original idea: tall tap strips down the card's left/right margins.

Each mock is interactive (tap to expand/collapse for real) with a dashed amber "redline" overlay
showing the actual tap-zone size, plus pros/cons. Recommended pairing: ship **02 (whole row)** as
the default everywhere charts appear, keep a padded chevron (01-style) as the visual "there's more
here" cue riding along for free.

**Where it lives:** Published as an Artifact for the owner to review (interactive, themed) — link
is in-conversation, not repeated here since Artifact URLs aren't durable across sessions. Source
committed to `planning/mocks/chart-toggle-redlines.html` per CLAUDE.md § Deliver mocks/visuals as
Artifacts (durable record). Tracked as `CHART-TAP-1` in `.session/SPRINT.md` Backlog — nothing
implemented yet, blocked on the owner's pick among the five.

**Next steps:** Owner picks an option (or a different pairing) → implement across all 4 surfaces
(`docs/index.html`) in one PR, add/update Playwright coverage per surface touched, ship the usual
release triplet (`releases.json` + `sw.js` cache bump) since this is user-facing.

---


## 2026-09-04 — Fix: watchlist stuck on "Pending read" for tickers that also qualify as Focus picks

**Status: safe to close — investigated, fixed, tested, PR to open.** Owner report with two
screenshots: several watchlist tickers (ELV, HUM, GH) added ~a week earlier were still showing
"PENDING READ" / "Reference bar captured — first live read after the next scheduled check.",
and lacked the full card (Volatility & setup, ATR-from-LoD, etc.) that other watch tickers
(SPCX, BAX) had. Owner asked for a full investigation first, no fix, "don't bear load on
unconfirmed assumptions."

**Investigation (evidence-based, not inferred).** Ruled out the two previously-fixed failure
modes in this area (`WS5-8b-OPS` missing secrets; `WS-POSITIONS-STATUS` no_quote/
awaiting_first_read copy) since neither matched: the private `/watchlist` feed showed real
`prior_high`/`prior_low` (a bar exists) and the TTL was decrementing normally (`tickWatchlist()`
only decrements when a bar exists), so `has_history` was clearly `True` server-side. Read the
actual committed `data/picks/sessions/morning.csv` directly (ground truth, not assumption) and
found the real root cause: `collect_morning.py`'s `union_watch_levels()` — when a watch ticker
ALSO qualifies as a Focus pick that day — keeps the Focus pick's row and never writes a second
`list_category='watchlist'`-tagged row for that ticker/date (by design, for scrape-count
purposes: "the watch dup contributes nothing"). ELV/HUM/GH had all started also qualifying as
Focus picks (`accel`/`leaders` buckets) — GH had been a recurring pick since before it was even
added to the watchlist, so its watch card had likely NEVER shown a real status.
`docs/index.html`'s watch-card lookup (`findPub`/`pub`, 2 call sites) filtered strictly on
`m.list_category === 'watchlist'`, found nothing on those days, and fell into the
`awaitingFirstRead` fallback — even though the exact same `pick_status` engine had computed a
real classification, just filed under a different bucket tag. Confirmed with grep evidence
against the CSV (GH: never once tagged `watchlist`, always `leaders`/`rs_new_high`/`all_green`;
ELV/HUM: correctly `watchlist`-tagged 8/27–9/1, then flipped to `accel` from 9/2 onward and
stuck since).

**Options presented, owner chose A.** (A) Client-side: relax the watch-pub lookup to accept any
row for the ticker (fallback after preferring an exact `'watchlist'` tag) — the lookup is
always called for one already-known ticker, so this can't cross-match an unrelated ticker's
row. (B) Backend: a new `is_watchlist` flag column, orthogonal to `list_category`. Rejected B
because `data/picks/sessions/*.csv` is a ground-truth CSV under
`.claude/rules/data-pipeline.md`'s schema-change rule (owner sign-off + a written
can't-be-a-pure-function justification required before building) and the fix genuinely doesn't
need a new column — same "compute at render time, don't persist a config/attribution-dependent
fact" precedent as the `power_of_3`/`VOLATILITY_FLOOR_PCT` sessions.

**Shipped:** new shared `findWatchPub(ticker)` helper in `docs/index.html` (replaces 3
duplicated inline `list_category === 'watchlist'` filters: `renderWatchlistSection`'s active +
expired card maps, and `__toggleWatchGauge`), with an in-code comment naming why the fallback
exists so a future cleanup doesn't revert it back to the strict filter. `docs/CLAUDE.md` §
Watchlist merge-model bullet updated to describe the new lookup and the collision it works
around. New regression test `tests/test_pwa_watchlist.py::
test_watch_card_finds_real_status_under_a_picks_bucket_tag` — verified it actually fails
pre-fix (`git stash` on `docs/index.html` reproduces the exact reported symptom: "PENDING READ"
pill + "Reference bar captured…" copy) and passes post-fix. Release triplet: `releases.json`
`2026.09.04.2` (fix, tab morning) + `current` bumped; `sw.js` `finviz-v98` → `v99`.

**Verified:** `test_pwa_watchlist.py` 10/10 (new test included), `test_pwa_morning.py` +
`test_pwa_quick_watch.py` 20/20 (unaffected — different render paths), full non-Playwright
suite 746 passed, `test_guide_releases.py` 5/5 (release-surface sync). Playwright run via the
documented revision-symlink harness (`chromium-1194` → `chromium-1117`, cleaned up after).

**Next steps:** open the PR. Not addressed (out of scope, no separate tracked item needed —
the fix is complete as scoped): the underlying `union_watch_levels()` collision behavior
itself is unchanged and intentional (attribution still correctly favors the picks bucket for
that CSV's own purposes); this fix only restores the PWA's ability to find the real status
regardless of which bucket won.

---


## 2026-09-03 — Picks tab: group tap opens quick detail sheet + reason chips on group headers

**Status: safe to close** — implemented, verified functionally with a Playwright fixture-intercept
smoke test (headless Chromium, both changes confirmed rendering correctly, screenshots taken),
release surface updated in the same PR. Non-Playwright pytest suite green (797 passed — the 75
"failed" in a raw pytest run are the known sandbox-only Chromium revision mismatch documented in
`knowledge/investigations/playwright-cloud-session-testing.md` Root cause 1, not a regression).

**Two small UX asks from the owner (screenshots of the live PWA):**
1. Tapping a group name on the Picks tab (`data-pick-group-lookup` — both the All view's group
   headers and the Focus view's per-row group subtitle share this one click handler) used to
   `switchTab('lookup')` + `doGroupLookup()`, navigating away entirely. It now calls
   `openGroupPeek(name, 'industries', true)` instead — the same slide-up sheet the AI tab's
   inline group-name chips (`groupChipHtml()`) already open, reusing `groupPerfCard()` so there's
   only one renderer to keep in sync with the full Lookup tab. `openGroupPeek()` gained a third
   `expanded` param (default `false`, preserving the AI tab's existing compact-card behavior) so
   Picks can land the reader straight on the full breakdown (`_peekExpanded = true`) since they
   already picked this exact group — no second tap needed. "Full lookup ↗" inside the sheet still
   reaches the full Lookup tab for anyone who wants more than the peek.
2. Each group header in the Picks tab's All view now shows the same reason chips
   (Leaders/Emerging/Accel/RS New High/All Green, `CATEGORY_LABEL`/`CATEGORY_CHIP_CLS`) the
   Lookup tab's `renderLookupStage2()` already shows — built from a `groupCatMap` (group →
   Set of categories) derived from the same `catMap` the All view already groups by, so a group
   qualifying under several buckets today isn't only visible in the one category section it
   happens to render under.

**Release surface (hard rule, same PR):** `docs/releases.json` `2026.09.03` entry prepended,
`current` bumped; `docs/sw.js` `CACHE` bumped `v94` → `v95`.

**Next steps:** none outstanding — PR opened, ready for review.

---


## 2026-09-03 — Morning tab: sort, launch-ready filter, bucket collapse + mini-nav

**Status: safe to close** — implemented, verified functionally with a headless-Chromium
Playwright smoke run (executable_path workaround for this sandbox's Chromium revision mismatch
— see `knowledge/investigations/playwright-cloud-session-testing.md`), 5 new committed
Playwright tests added and passing (14/14 in `tests/test_pwa_morning.py`), non-Playwright
pytest suite green (746 passed), release surface updated in the same PR.

**Owner ask:** the Morning tab's picks-confirmation list only ever sorted by status bucket then
ticker A–Z — with most cards landing in the same "Setting up" bucket on a typical day, it read
as "just alphabetical." Worked through several rounds of design discussion (sort options, Focus
score reuse-vs-recompute, Launch-ready filter interaction, bucket-navigation options) before
building.

**What shipped** (`renderMorning()` and helpers in `docs/index.html`; full design writeup in
`docs/CLAUDE.md` § Morning tab):
1. **Sort pills** (`state.morningSort`): A–Z / **Focus score (default)** / ATR from LoD / Rel
   volume. Status-bucket grouping (Triggered → ... → No quote) is a constant — every sort mode
   only reorders *within* a bucket, via one shared null-safe comparator
   (`sortMorningEntries()`).
2. **Rel volume's Bucket/Global scope switch** (`state.morningSortScope`) — a conditional
   control that only appears when Rel volume is the active sort, rather than a permanent 5th
   pill, given how much chrome already stacks above the first card. Global flattens every
   status bucket into one cross-sectional "what's most active right now" list.
3. **Focus score chip + sort share ONE computation.** Pulled the candidate-pool derivation +
   `computeFocusScores()` call out of `ws4FocusScore()` into `focusScoreMapForPool()`, computed
   once per render into `_morningFocusMap`. The new card chip, the `'focus'` sort branch, and
   the existing trade-ticket footnote (`ws4TicketHtml`) all now read that one map — a future
   Focus-formula change updates all three for free instead of risking silent disagreement.
4. **Launch-ready filter** (`state.morningLaunchFilter`): All / Coiled / Extended / Overhead,
   on the same `computeLaunchReady()` label already shown as a card chip — independent axis
   from sort. Empties-to-zero shows filter-specific copy, not the generic no-picks-today state.
5. **Bucket collapse + sticky mini-nav** (`state.morningCollapsed`, a `Set`): each bucket header
   is a collapse toggle with a live count; the mini-nav (only rendered with >1 bucket) jumps to
   any bucket and **force-expands it first** if collapsed, so a jump never lands on an empty
   collapsed section. Starts fully expanded (no default-collapsed density change) — kept
   conservative since that wasn't explicitly asked for beyond "can we do both."

**Test-suite fallout from the new permanent "ATR from LoD" sort-pill label:** two existing
`test_pwa_morning.py` assertions counted exact occurrences of the literal string "ATR from
LoD" in the rendered HTML; the new sort pill (deliberately reusing that exact on-card copy
rather than inventing a different label) adds one more permanent occurrence per render. Updated
both expected counts (5→6, 2→3) with an inline comment explaining why — a real, expected
consequence of shipping the feature, not a bug.

**Pre-existing, unrelated finding (not fixed here, flagged as a separate task):**
`tests/test_pwa_positions.py` never stubs `**/sessions/pre_close_latest.csv` the way every
other Morning-adjacent test file does — 4 of its tests hang for the full 30s timeout in this
network-restricted sandbox (confirmed reproducible against the pre-change baseline via `git
stash`, so unrelated to this PR). Presumably invisible in CI/local dev with real network access
(an unstubbed request just resolves instead of hanging), per Root cause 2 in
`knowledge/investigations/playwright-cloud-session-testing.md`.

**Release surface (hard rule, same PR):** `docs/releases.json` `2026.09.03.1` entry prepended,
`current` bumped; `docs/sw.js` `CACHE` bumped `v95` → `v96`.

**Next steps:** none outstanding — PR opened, ready for review. Optional follow-up (not
blocking): add the missing pre-close stub to `test_pwa_positions.py`, and/or revisit whether
non-actionable buckets (Setting up/Invalidated/Failed breakout/No quote) should default-collapse
now that the toggle exists — deferred since it wasn't explicitly requested.

---


## 2026-09-02 — Volatility floor gate: hide near-dead stocks from Picks/Focus/Morning

**Status: safe to close — implemented, tested (740 non-PW + 5/5 new volatility-gate PWA green,
verified no regression in Focus/Morning/Lookup/methodology suites), PR to open.** Follow-up to
the B-5 "Pre-Power of 3" session above: owner spotted APGE (a buyout-frozen biotech) showing a
false "Coiled 2.8x" chip in the Volatility & setup section — its MAs and price were only
bunched because the stock barely moves at all (Vol W 0.07%, ATR/Price 0.26%), not because it's
a genuine coil.

**Investigation before building:** owner asked for a histogram of the live picks pool's
Volatility W % and ATR/Price % (published as an Artifact) before locking a threshold. Result:
both distributions are bimodal with a real gap between ~0.5% and ~1.2% — a 1.0% floor sits
exactly in that gap, catching only 5 tickers today (APGE, CRNX, OGN, TECH — all read as
halted/frozen biotech/spin-off names — plus STRC, which turned out to not even be a common
stock: "Strategy Inc - VR PRF PERPETUAL Series A", a perpetual preferred). Going to 1.5% would
have started cutting legitimate low-vol mega-caps (Novartis, JNJ, ADP, Shell, Enterprise
Products) that are just boring, not dead. Validated the choice wasn't an eyeball guess.

**Decision (owner, locked in-session):** `VOLATILITY_FLOOR_PCT = 1.0`. Gate fires on
`Volatility W % < 1.0 OR ATR/Price % < 1.0` (either trips it — both already-scraped columns,
no new CSV data). Hides the row from Picks (`passesPicksBaseFilter`), Focus (`isFocusEligible`
— duplicated at the predicate level since 2 of 3 call sites don't also call
`passesPicksBaseFilter`), and the Morning tab's picks-confirmation read (`renderMorning`'s
non-watchlist filter). Missing data (NaN) passes through — this only excludes what's
positively measured as too quiet, never an unknown. **Exempt: the user's own watchlist**
(explicit intent — those tickers ride the same morning scrape but the exclusion filter is
only applied to `list_category !== 'watchlist'` rows) **and a direct Lookup ticker search**
(explicit intent — shown with a new amber "Low volatility" warning chip in
`tickerContextHtml` instead of being hidden).

**Why client-side, not scrape-time (owner asked, both options presented):** `Volatility W`,
`Volatility M`, `ATR`, `Price` are already scraped/stored in picks.csv/picks_latest.csv and
morning.csv/morning_latest.csv — nothing new to collect. `.claude/rules/data-pipeline.md`
treats those CSVs as append-only, irreplaceable ground truth; a scrape-time drop would make a
wrongly-excluded (or later-retuned-threshold) row unrecoverable. Every existing per-stock
exclusion in this codebase (`passesPicksBaseFilter`'s market-cap/MA filter, `isFocusEligible`'s
liquidity gate, the Ariel match filter's own ATR%-band precedent) is already a client-side view
filter, not a scrape-time drop — followed that precedent.

**Shipped:** `VOLATILITY_FLOOR_PCT` constant + `atrPctOfPrice()`/`passesVolatilityFloor()`
helpers in `docs/index.html`, wired into `passesPicksBaseFilter`/`isFocusEligible`/
`renderMorning`, Lookup warning chip in `tickerContextHtml`/`findTickerPickInfo`.
`display_methodology.json` v6 (base_filter + focus_dq `volatility_floor` block).
`tests/test_picks_methodology.py` updated (v6 current, v5 preserved, 2 new sync tests).
New `tests/test_pwa_volatility_gate.py` (5 tests: Picks-All exclusion, Focus exclusion,
OR-logic via ATR-alone, Morning-card exclusion, Lookup warning-chip-not-hidden) — added to the
CI Playwright `--ignore=` list. README § Configurable parameters + `docs/CLAUDE.md` § PWA
display thresholds updated. Release surface: `releases.json` 2026.09.02.3 + `sw.js`
finviz-v93→v94, same PR per the hard rule.

**Not done / explicitly deferred:** no warning chip added to the Watchlist card itself (its
existing "Volatility & setup" section already shows raw Vol W/ATR values, so the data is
visible without a new badge) — flagged as an assumption in the PR description in case the
owner wants the same amber chip there too.

**Next steps:** open the PR, watch CI, then resume B-5b (the full undercut→reclaim Power-of-3
trigger) from the prior session's notes above, unless the owner redirects.

---


# Session Notes Archive

> Older session entries moved here periodically by a human reviewer. Not auto-loaded.
> Newest entries at the top.


---
