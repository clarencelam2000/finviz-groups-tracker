# Planning

This is the navigation index for `planning/` — the place a cold session or a new engineer
starts to find out where something lives and what state it's in. It does **not** replace
reading the docs themselves; each entry below is a one-line pointer, not a summary of the
design. Statuses are **Live** (describes the current system or in-flight work), **Shipped**
(the work landed; the doc is now a historical record, possibly with residual backlog items
tracked in `.session/SPRINT.md`), or **Superseded** (a later doc replaced it — kept for
history, not for current design). When in doubt about a doc's real-world status, check
`.session/SPRINT.md` and the live code before trusting the doc's own header — plan-doc status
lines drift out of date faster than the code they describe.

## Where things live

| Content type | Location |
|---|---|
| Designs, briefs, implementation plans | `planning/` (this directory) |
| UI mocks (HTML, open in a browser) | `planning/mocks/` |
| Accepted decisions + rejected alternatives (ADRs) | `knowledge/decisions/` |
| Research logs, post-mortems, methodology audits | `knowledge/investigations/` |
| Task board (backlog / ready / in progress / done) | `.session/SPRINT.md` |
| Last 4 sessions' notes (older in `.session/archive/`) | `.session/session-notes.md` |
| Project rules (git workflow, data-pipeline conventions) | `.claude/rules/` |
| Tracked work not yet on the sprint board | GitHub issues |

Subdirectory `CLAUDE.md` files (`scripts/CLAUDE.md`, `docs/CLAUDE.md`, `worker/CLAUDE.md`,
`worker-positions/CLAUDE.md`) only auto-load when a session touches files in that directory —
for cross-cutting work (e.g. a scripts change that also affects the PWA), proactively `Read`
the other directory's `CLAUDE.md` too.

When a plan is fully executed and the PR merged, it's fine to leave it in `planning/` marked
Shipped (this index tracks that); promote it to an ADR in `knowledge/decisions/` only if it
represents a decision worth recording with its rejected alternatives, not for every shipped
feature doc.

## Active workstreams

### AI / LLM

| File | What it's for |
|---|---|
| `ai-llm-integration-proposal.md` | **Start here for the AI workstream.** Proposal for LLM integration across Picks/Morning/Positions and at top level. **Design gate; no code shipped.** Established by live recon that `generate_ai.py` today sees only sector/industry data — zero picks/morning/positions/watchlist awareness. Owner decisions locked in §6 (12-row table, 2026-09-06 — do not re-ask): build **Morning first** (P0→P2), ≤10-min latency to screen, actionable+changed rows only, honesty chip dropped, counter-evidence is a **required** field, numbers come from **slot filling** (the model never writes one), feed context **broadly** but require field citation. Note §0 carries a **self-correction**: an earlier draft called the picks alpha "negative at every horizon" and that was overstated — under a proper estimator three of four horizons straddle zero and the result flips sign across sample halves. Do not re-quote the raw `--report` table without reading §0 and `knowledge/investigations/picks-alpha-2026-09-05-significance-audit.md`. |
| `ai-evidence-pack-schema.md` | The evidence-pack contract (`meta`/`fields`/`context`/`notes`), pack granularity per statement target, the model output contract (`text`+`slots`+`cites`+`confidence`), the four mechanical validation rules + digit lexicon, fail-closed/retry-once behaviour and the structured-output spike go/no-go, and `data/ai/pack_schema.json` as the shared Python↔JS registry. **Reviewed and locked 2026-09-06** (§6 decisions, §8 test plan). Blocks every AI-NEXT phase. |
| `ai-next-user-stories.md` | User stories + acceptance criteria per `AI-NEXT-*` SPRINT task, written from the owner's own usage (Morning-first, phone, 10:10/15:35 ET). A task is Done only when its AC pass. Includes the definition-of-ready for pickup. |
| `ai-tab-daily-note.md` | Current AI-tab architecture: a freeform daily-note markdown blob per group instead of forced-JSON-schema cards. Approved, in progress. Supersedes `ai-architecture-revamp.md` and `ai-tab-improvements.md` (see Superseded table). |
| `PLAN_smart_regeneration_pydantic.md` | Phase 1 (smart regeneration + `--force-ai` flag) is shipped and live in `scripts/generate_ai.py`. Phase 2 (Pydantic schema enrichment — `additionalProperties: false`, few-shot examples) is specced but blocked/backlog (`PLAN-2` in SPRINT). |

### Trade lifecycle / WS5

| File | What it's for |
|---|---|
| `trade-lifecycle-engine.md` | The core WS5 design doc — state machine, `advance()` engine, D1 schema, extensibility seams. Actively referenced as workstreams (managing card, watchlist, push notifications) continue to build on it. |
| `watchlist-status-honesty-and-seeding.md` | Watchlist status fixes. The "no_quote vs. never-had-a-bar" honesty fix (`WS-POSITIONS-STATUS`) is merged; the first-bar seeding piece (`WS-POSITIONS-SEED`, PR #368) was owner-approved and built but was awaiting the D1 migration + merge as of last check. |

### Picks & methodology

| File | What it's for |
|---|---|
| `stock-picks-from-leading-groups.md` | The master design doc for the Picks tab (Stage-2 screener pipeline, Focus scoring, HoD toggle). Most phases (3a–3d+) have shipped incrementally; it remains the reference design as new Picks work (Effort A/B below) continues to build on it. |
| `compression-expansion-ideation.md` | Ideation + living task tracker for two ongoing efforts: **Effort A** (card standardization across Picks/Morning/Ticket/Watchlist) and **Effort B** (compression/expansion setup metrics — volatility, range-tightening, volume dry-up, MA-bunching). Actively shipping slice-by-slice as of 2026-09; §12 is the current source of truth for what's built vs. left. |
| `picks-alpha-evaluation.md` | Spec for the picks alpha scoreboard. Part 1 (`scripts/evaluate_picks.py`, group-level scoreboard) is shipped (`PICKS-4`, 2026-07-19). Parts 3/4 (stock-level scoreboard with real OHLC, R-multiple expectancy, `risk_*_pct`→`risk_*_frac` rename) remain blocked/backlog. |

### PWA / UX

| File | What it's for |
|---|---|
| `PLAN_sector_industry_hierarchy.md` | 22-feature roadmap across 5 tiers for sector/industry drill-down. Foundation + Tier 1 (breadth bar, drill-down, rank-within-sector, leaders/laggards) shipped 2026-07-02. The Tier-2 backlog (rotation radar, crowding warnings, breadth gauge, etc.) was flagged by the VP as unapproved/fluffy and has sat dormant since — read the doc's "⚠️ Current State" note before resuming any HIR-* item. |

### Ops & scheduling

| File | What it's for |
|---|---|
| `roadmap-cron-lifecycle.md` | The overarching roadmap connecting cron consolidation (WS1, shipped) to the trade lifecycle engine (WS5, ongoing — see above). Read this for how the individual cron/WS docs fit together; it also records rejected ideas (e.g. intraday persistence tracking) so they aren't re-litigated. |

## Shipped / historical

| File | What shipped |
|---|---|
| `PLAN_decouple_ai_workflow.md` | Split AI generation into its own `generate_ai.yml`, decoupled from `collect.yml` (PR #53). |
| `PLAN_etf_lookup_overrides.md` | Curated ETF→Finviz-group override layer (`data/etf_overrides.csv`), Phase 0+1, 2026-06-20. |
| `PLAN_force_generateai_calls.md` | `--force-ai` flag + workflow input to force AI regeneration, bypassing the completeness cache. |
| `PLAN_relative-strength-benchmark.md` | RS-vs-SPY columns (`rs_*`, `beats_benchmark_*`) and `data/benchmark/snapshots.csv` — all three phases live. |
| `PLAN_ticker_lookup.md` | Ticker → Finviz-group lookup: CF Worker + KV cache, PWA Lookup tab, Streamlit Lookup tab, ops tooling (all TICKER-0..4 done). |
| `ai-capture-and-visibility.md` | `data/ai_run_log.jsonl` capture, `--capture` Tier-2 debug mode in `generate_ai.py`. |
| `ai-quota-exhaustion-fix.md` | Incremental-resume + `DailyQuotaExhaustedError` fixes for Gemini quota exhaustion; carried forward (not redone) by `vertex-ai-migration.md`. |
| `card-lookup-deeplink-rollout.md` | Card-tap → Lookup deep-link, full rollout (2026-06-23). |
| `cf-auto-deploy.md` | `.github/workflows/deploy-workers.yml` — auto-deploy merged Worker code to Cloudflare. |
| `cloudflare-cron-scheduler.md` | Original replacement of GitHub Actions cron with a Cloudflare Cron Trigger (ADR-004); itself later superseded operationally by the single-trigger dispatcher below. |
| `compute-deltas-lookbacks-and-momentum.md` | Config-driven lookback windows (`delta_config.py`) + momentum variant columns; slices 1–5 landed. |
| `cron-consolidation-state-machine.md` | Single-trigger, state-machine cron dispatcher (ADR-010) — the scheduler described in `CLAUDE.md` § Automation today. |
| `lookup-search-enhancements.md` | Lookup search UX: synonyms/fuzzy match, recent/pinned searches, empty-state chips. All ideas complete. |
| `lookup-tab-improvements.md` | Lookup tab Phase 0–2 (moaty metrics, Signal card v2). A handful of ideas (tap-to-jump, AI rotation line, Rank Floor promotion) remain deferred in SPRINT. |
| `picks-hod-price-basis-toggle.md` | HoD ↔ Last price-basis toggle for Picks risk metrics, Phase A + B. |
| `picks-methodology-tracking.md` | `data/picks/display_methodology.json` versioned scoring constants, v1 + v2 (Focus liquidity/earnings haircuts). |
| `start-here-onboarding.md` | "Start Here" intro/onboarding carousel for the PWA (2026-06-21). |
| `vertex-ai-migration.md` | Migrated AI generation from Gemini AI Studio to Vertex AI; live auth chain documented in `CLAUDE.md`. |
| `watchlist-build-brief-8b.md` | Personal watchlist riding the Morning scrape (WS5 §8b) — worker/D1, feed union, and PWA phases (P1–P3) all landed. A few items (fully-private morning store, multi-day reclaim) remain deferred, tracked in SPRINT. |
| `whats-new-and-guide.md` | "What's New" release notes + Guide/Glossary for the PWA — first pass implemented; §8 items (per-tab walkthrough, data-source FAQ) deferred as planned. |
| `ws3b-preclose-surface-spec.md` | The ~15:30 ET pre-close confirmation surface — now the live `preclose_status` cron job (see `CLAUDE.md` § Automation). |
| `ws5-4b-vapid-push-handoff.md` | VAPID push notifications, Tier-1 data-less (PR #346) + RFC 8291 payload encryption core (PR #353). Silent Tier-2 reminders and earnings-approach push remain backlog (#348). |
| `ws5-7-positions-managing-card.md` | Positions managing-card overhaul — state-driven hero, stop-moved banner, cross-device ack (PR #338). |

## Superseded

| File | Superseded by |
|---|---|
| `ai-architecture-revamp.md` | `ai-tab-daily-note.md`. All 6 phases of the forced-JSON-schema architecture shipped, but the approach itself proved unusable in production (raw JSON leaking into the UI) and was replaced by the freeform-note rebuild. Its phase table also cites a stale model name and task count — see issue #406. |
| `ai-tab-improvements.md` | `ai-tab-daily-note.md`. This "8 mobile PWA improvements" plan for the old JSON-card AI tab was never executed (no SPRINT trace) before the tab was rebuilt from scratch. |

## Naming convention

- `PLAN_<slug>.md` — detailed multi-task implementation plans (tasks, subtasks, acceptance criteria)
- `<slug>.md` — shorter scoped design docs or feature briefs

When a plan is fully executed and the PR merged, move it to `knowledge/decisions/` as an ADR-style record of what was decided and why.
