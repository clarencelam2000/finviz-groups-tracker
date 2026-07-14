# ADR-009: Curated-first ETF classification — manual overrides over automated aggregation

**Date**: 2026-06-20
**Status**: Accepted

> **Renumbered 2026-07-10** — originally published as ADR-005, colliding with
> `ADR-005-spy-relative-strength.md` (both dated 2026-06-20). Historical references to
> "ADR-005 (ETF)" in SPRINT.md Done entries and session-note archives mean this document.

## Context

The Lookup tab uses FMP `stable/profile` to classify a ticker by its Finviz sector and
industry. For ETFs, FMP returns the *legal entity* classification (Asset Management /
Financial Services) rather than the *economic exposure* the ETF provides. The result:
COPX (copper miners ETF) and ITA (aerospace & defense ETF) both resolve to
"Financial / Asset Management" — a confidently wrong answer that undermines the rotation
map's credibility.

Two automated approaches were evaluated to fix this at scale:

| Option | Coverage | Cost | Accuracy | Decision |
|--------|----------|------|----------|----------|
| **Curated override list** | Top ~30–50 ETFs | $0, no new vendor | Hand-verified, deterministic | **Accepted — ship now** |
| Finnhub `/etf/holdings` aggregation | Any US ETF | Free API, new vendor | Probabilistic (majority vote can misclassify mixed funds) | Demand-gated fast-follow |
| FMP ETF sector-weightings | Broad sector only | Free? (unverified) | Too coarse (Basic Materials, not Copper) | Rejected |
| FMP holdings | Any ETF | Paid (Ultimate tier ~$200/mo) | Good | Rejected — fails free-tier constraint |

The `isEtf` signal from FMP `stable/profile` was validated live on 2026-06-20: all 19
seed ETFs (COPX, ITA, XLE, XLF, SPY, QQQ, SMH, SOXX, XBI, IBB, GDX, GDXJ, URA, TAN,
JETS, XOP, OIH, KRE, KBE) returned `isEtf: true`. It is a reliable gate.

## Decision

**Curated-first, two-layer architecture:**

1. **Control plane (this ADR):** `data/etf_overrides.csv` — hand-verified, deterministic
   ticker→group mappings. Applied when `isEtf: true` and ticker is in the map. Wins over
   any automated result. Never replaced by Phase 2 — manual overrides always take
   precedence.

2. **Scale plane (Phase 2, demand-gated):** Finnhub `/etf/holdings` — automated, broader
   coverage for long-tail ETFs not in the curated map. Added only when lookup logs show
   demand for unlisted ETFs.

Three `kind` buckets:
- **`thematic`** — single-industry theme (COPX→Copper, ITA→Aerospace & Defense, etc.)
- **`sector`** — spans all industries in one sector (XLE→Energy, XLK→Technology, etc.)
- **`diversified`** — broad market (SPY, QQQ, VTI, DIA, IWM); no single rotation group

Validation at build time: every `finviz_industry` / `finviz_sector` in the override CSV
is asserted against live snapshot CSVs, so typos (e.g. "Aerospace and Defense") fail the
build with a clear message rather than silently linking to a non-existent group.

## Alternatives considered

**FMP sector-weightings endpoint:** Returns the broad sector allocation (e.g. Basic
Materials 85%, Technology 10%) for ETFs. Rejected because the result is a sector
distribution, not a single Finviz industry, and for thematic ETFs the industry is what
matters (Copper, not Basic Materials). Coarse enough to be misleading for the use case.

**FMP holdings (paid tier):** Would enable automated resolution for any ETF.
Rejected — fails the free-tier constraint (Ultimate tier, ~$200/month). The curated
list solves the high-demand head of the distribution at $0.

**Finnhub holdings aggregation (Phase 2):** Top-N holdings → per-holding industry lookup
→ majority vote → Finviz group. Viable for the long tail. Deferred: the curated list is
likely sufficient until lookup logs reveal unlisted-ETF demand.

## Consequences

- **Coverage:** ~31 seed ETFs (15 thematic + 11 sector SPDRs + 5 diversified) — covers
  the most-searched ETFs in the thematic/sector rotation context.
- **Maintenance:** Adding a new ETF requires a one-line CSV edit + `npm run deploy`.
  The build validates the name against snapshots, so errors surface before deploy.
- **KV cache caveat:** ETF entries cached before deploy keep the old wrong value until
  30-day TTL. Post-deploy cache bust script documented in `worker/README.md`.
- **Phase 2 readiness:** `classification_source` field distinguishes override vs. taxonomy
  results, so front-ends and analytics can tell curated from inferred.
- **Leveraged/inverse ETFs** (SOXL, TQQQ, etc.) are out of scope for now. Add as
  `thematic` pointing at the underlying industry only if lookup logs show demand.

## Phase 2 design note (Finnhub holdings aggregation)

When long-tail ETF demand justifies it:
1. On ETF cache miss with no curated override, call Finnhub free `/api/v1/etf/holdings`
   (US only, top-N constituents returned).
2. For each holding, run through the existing `/lookup` cached worker call to get its
   Finviz industry.
3. Majority-vote the results (weighted by portfolio %) to a single Finviz group.
4. Cache the result keyed by ETF ticker, 30-day TTL (same as existing cache).
5. Curated overrides in `data/etf_overrides.csv` remain the precedence layer — manual
   beats inferred.
6. New secret: `FINNHUB_API_KEY` via `wrangler secret put`.

Caveats: mixed-sector ETFs (e.g. a "Clean Energy" fund that spans Technology and
Utilities) may vote to the wrong dominant industry. The curated list handles these edge
cases definitively.
