# Fix ETF Lookups — Curated ETF→Finviz-Group Override Layer

> Status: **Phase 0 + Phase 1 COMPLETE (2026-06-20).** All 1.1–1.9 steps implemented,
> 50 worker tests + 165 Python tests pass. PR open on `claude/trusting-einstein-f1h4bo`.
> Tracked as `ETF-1` in `.session/SPRINT.md`.

## Context (VP-level decision brief)

**Problem.** The Lookup tab returns the wrong group for ETFs. Every ETF — COPX (copper
miners), ITA (aerospace & defense) — resolves to "Financial / Asset Management." Root cause:
our data vendor (FMP `stable/profile`) classifies a fund by its *legal* business (asset
management), not by what it *holds*. The worker faithfully maps that through the taxonomy, so
the wrong answer is structural, not a one-off.

**Why it matters.** Lookup's entire value proposition is "tell me where this ticker sits in
the rotation map." ETFs are the cleanest way users express a thematic rotation view, so
they're over-represented in searches. A wrong answer here isn't a blank — it's *confidently
misleading* (implies COPX is a financials play). It's a credibility hit on a flagship surface.

**Options considered.**

| Option | Coverage | Cost | Time | Verdict |
|---|---|---|---|---|
| Curated override list (ETF→group, maintained by us) | Top ~30–50 searched ETFs | $0, no new vendor | ~1 day | **Recommend now** |
| Holdings aggregation via Finnhub free | Any US ETF | New vendor + engine | ~1 sprint | Fast-follow |
| Holdings via FMP | Any ETF | Paid (Ultimate tier) | — | Rejected — fails free-tier constraint |
| FMP ETF sector-weightings | Broad sector only (Basic Materials, not Copper) | Free? | — | Rejected — too coarse for thematic ETFs |

**Recommendation.** Ship the curated layer now; sequence Finnhub as a fast-follow only if
usage justifies it.

**The strategic point.** These aren't either/or. The curated list is the **control plane** —
deterministic, hand-verified, ours. Finnhub is the **scale plane** — automated, broad, but
probabilistic (a holdings vote can misclassify mixed funds). In every mature classifier the
manual override sits *on top of* the automated engine and wins. So the work we do today is
permanent infrastructure, not a stopgap we throw away when Finnhub lands.

**Cost / risk.** Zero incremental vendor spend. Risk is bounded to coverage gaps — an
unlisted ETF falls back to today's behavior (no regression). We already log every lookup, so
curation is data-driven from real demand rather than guesswork.

**Roadmap.** Phase 1 (now): curated overrides, fixes the ETFs users actually search.
Phase 2 (demand-gated): Finnhub holdings aggregation for the long tail, with curated
overrides retained as the precedence layer.

---

## Current architecture (what we're changing)

- **PWA** `docs/index.html`: Lookup tab UI (`§ tab-lookup` ~L212–227), `lookupTicker()`
  (~L1485), `renderLookup()` (~L1982–2046), `doLookup()` (~L2048). Calls the worker at
  `WORKER_URL` (~L260).
- **Worker** `worker/src/index.js`: `handleLookup()` (L73) → KV cache (30-day TTL, keyed by
  uppercased ticker) → on miss `fetchProfile()` (L121). `fetchProfile` calls FMP
  `stable/profile?symbol=&apikey=` (L16/L128), then at **L164–166** does
  `lookupTaxonomy(p.industry)` and builds the response (L171–193). `p.isEtf` is captured at
  L187 but **never used to alter classification** — that's the gap.
- **Taxonomy** `worker/src/taxonomy.js`: `lookupTaxonomy()` / `lookupSector()` over
  `taxonomy_map.json`, generated from `data/taxonomy_map.csv` by
  `worker/scripts/build_taxonomy.js`.
- **Canonical Finviz group names** live in `data/industries/snapshots.csv` (col 4, ~150
  industries) and `data/sectors/snapshots.csv` (11 sectors). Verified verbatim presence of
  `Copper`, `Aerospace & Defense`, `Semiconductors`, `Biotechnology`, `Gold`, `Uranium`,
  `Solar`, `Airlines`, `Oil & Gas E&P`, `Banks - Regional`.
- **`isEtf` signal validated (2026-06-20):** Live FMP `stable/profile` responses confirmed
  `isEtf: true` for all 19 planned seed ETFs (COPX, ITA, XLE, XLF, SPY, QQQ, SMH, SOXX,
  XBI, IBB, GDX, GDXJ, URA, TAN, JETS, XOP, OIH, KRE, KBE). The gate `Boolean(p.isEtf)` is
  a reliable signal for this override layer; no fallback to `isFund` is needed.
- **FMP free-tier facts** (`knowledge/fmp-api-findings.md`): only `stable/profile` works;
  `available-industries`/`available-sectors`/`profile-bulk`/holdings are paid (402). Daily
  cap ~240 calls — the 30-day KV cache makes runtime cost ~1 call/ticker/30 days.

---

## Phase 0 — Land this plan (this document), then PAUSE

**Goal:** commit this complete plan into the repo so anyone on the team can pick it up. No
implementation in this phase.

1. Branch `claude/happy-cori-l7023g` from `origin/claude/elegant-babbage-hlxnfy`.
2. Add this document at `planning/PLAN_etf_lookup_overrides.md` (self-contained — a fresh
   reader needs no other context).
3. Add a one-line pointer in `.session/SPRINT.md` Backlog as task `ETF-1`.
4. Commit (`docs: add ETF lookup override plan (ETF-1)`), push, open a PR targeting
   `claude/elegant-babbage-hlxnfy`, mark ready for review, **merge it**.
5. **PAUSE.** Do not start Phase 1 until the team gives the go-ahead.

---

## Phase 1 — Curated override implementation (after Phase 0 merged + go-ahead)

Each numbered item is one focused commit with its test alongside (per
`.claude/rules/branch-commit-discipline.md`).

### 1.1 Source of truth: `data/etf_overrides.csv` (new)
Columns: `ticker, finviz_industry, finviz_sector, etf_name, kind, note`.

Three `kind` buckets (avoid false precision):
- **`thematic`** → exact `finviz_industry` + its `finviz_sector`. Seed set:
  COPX→Copper, ITA→Aerospace & Defense, SMH→Semiconductors, SOXX→Semiconductors,
  XBI→Biotechnology, IBB→Biotechnology, GDX→Gold, GDXJ→Gold, URA→Uranium, TAN→Solar,
  JETS→Airlines, XOP→Oil & Gas E&P, OIH→Oil & Gas Equipment & Services, KRE→Banks - Regional,
  KBE→Banks - Diversified, plus other clear single-industry ETFs as identified.
- **`sector`** → `finviz_sector` only, `finviz_industry` blank (they span industries).
  The 11 sector SPDRs: XLE, XLF, XLI, XLK, XLV, XLP, XLY, XLU, XLB, XLRE, XLC.
- **`diversified`** → both blank (SPY, QQQ, VTI, DIA, IWM). Worker emits a "Broad market ETF"
  signal instead of asserting a group.

All `finviz_*` values **must match Finviz names verbatim** — enforced by 1.2.

### 1.2 Build step: extend `worker/scripts/build_taxonomy.js`
- Read `data/etf_overrides.csv`, emit `worker/src/etf_overrides.json` keyed by uppercased
  ticker: `{ "COPX": {finviz_industry, finviz_sector, kind}, ... }`.
- **Validation pass (critical):** load the canonical group sets from
  `data/industries/snapshots.csv` (col `name`) and `data/sectors/snapshots.csv` (col `name`);
  for every non-blank override value assert membership; **exit non-zero with a clear message**
  on any unknown group. This guarantees overrides link into the rotation map and prevents
  silent typos (e.g. "Aerospace and Defense").
- **Single script, two outputs:** the extended `build_taxonomy.js` emits both
  `taxonomy_map.json` (existing) and `etf_overrides.json` (new) in one run. This keeps
  `npm run build:taxonomy` and `npm run deploy` (`build:taxonomy && wrangler deploy`) intact
  with no changes to `package.json`. Do not introduce a separate `build:overrides` script.
- **Export the validation function** (alongside existing `parseCsv` / `buildTaxonomy`
  exports) so vitest can import it and test the bogus-name exit path with a fixture — not
  via a subprocess call. See §1.6.

### 1.3 Runtime lookup: extend `worker/src/taxonomy.js`
Add `lookupEtf(symbol)` importing `etf_overrides.json`; return
`{finviz_industry, finviz_sector, kind}` for an uppercased ticker hit, else `null`. Mirror
the existing `lookupTaxonomy` style and null-safety.

### 1.4 Worker wiring: `worker/src/index.js` `fetchProfile()` (L164–193)
- After computing `tax`/`finvizSector`, if `Boolean(p.isEtf)`:
  - `const ov = lookupEtf(symbol)`.
  - If `ov` and `kind !== 'diversified'`: set `finviz_industry`/`finviz_sector` from `ov`;
    `classification_source = 'etf_override'`; `etf_kind = ov.kind`.
  - If `ov` and `kind === 'diversified'`: clear `finviz_industry`/`finviz_sector`;
    `classification_source = 'etf_override'`; `etf_kind = 'diversified'`.
  - If no `ov`: leave FMP-derived values; `classification_source = 'fmp_taxonomy'`,
    `etf_kind = null` (today's behavior — no regression).
- Non-ETF path: `classification_source = 'fmp_taxonomy'`, `etf_kind = null`.
- Always keep raw `fmp_sector`/`fmp_industry` for transparency.
- Add `classification_source` + `etf_kind` to the returned object (L172–192).

**Cache caveat:** the response is cached 30 days keyed by ticker. After deploy, already-cached
ETF entries keep the old wrong value until TTL. Bust the seed set post-deploy via
`DELETE /cache?t=...` for each seeded ETF (or accept natural expiry). Document in README.

### 1.5 PWA rendering: `docs/index.html` `renderLookup()` (~L1982–2046)
Three ETF rendering states, determined by `etf_kind` (absent / `null` = not an ETF override):

- **`thematic`** (`finviz_industry` set): render industry + sector cards as normal, plus a
  small badge **"ETF — classified by holdings theme."**
- **`sector`** (`finviz_industry` blank, `finviz_sector` set): render sector card only (no
  industry card — there isn't one); badge reads **"Sector ETF — spans all industries within
  this sector."** Do not render an empty industry slot.
- **`diversified`** (both blank): render **"Broad market ETF — not a single rotation group"**
  instead of any industry/sector card.

Leave non-ETF rendering (`etf_kind` absent or `null`) entirely untouched.

**Backward-compat note for stale KV cache entries:** entries cached before deploy have no
`classification_source` or `etf_kind` fields. Treat absent/`undefined` `classification_source`
as `'fmp_taxonomy'` and absent/`undefined` `etf_kind` as `null`. Stale-cached ETF entries
will silently show no badge (acceptable until TTL); the seed set should be busted post-deploy
(see §1.4 cache caveat).

### 1.6 Tests
- `worker/test/index.test.js`: mock FMP returning `isEtf:true, sector:"Financial Services",
  industry:"Asset Management"` for COPX → assert response `finviz_industry === "Copper"`,
  `finviz_sector === "Basic Materials"`, `classification_source === "etf_override"`. Same for
  ITA → Aerospace & Defense. Assert a non-ETF (AAPL) is unchanged
  (`classification_source === "fmp_taxonomy"`). Assert a `diversified` ETF (SPY) returns empty
  industry + `etf_kind === "diversified"`.
- Build validation: import the exported validation function from `build_taxonomy.js` directly
  in vitest (same pattern as existing `parseCsv`/`buildTaxonomy` imports). Pass a fixture CSV
  with a bogus group name and assert the function throws / returns a non-zero signal. Do NOT
  use a subprocess call (`child_process.execSync`) — it makes the test brittle and slow.
- Run `cd worker && npm test` and root `python3 -m pytest tests/ -q` before each commit.

### 1.7 Docs (same PR as the code)
- `worker/README.md`: document `data/etf_overrides.csv`, the `classification_source`/`etf_kind`
  response fields, the build-validation behavior, and the post-deploy cache-bust note.
- `CLAUDE.md`: add a note in the worker section that ETF lookups apply a curated override
  layer (source `data/etf_overrides.csv`).
- `knowledge/decisions/`: ADR — curated-first vs Finnhub-first; FMP-holdings-paid &
  sector-weighting-too-coarse rejections; two-layer precedence (curated wins over future
  aggregation). Follow `knowledge/README.md` ADR template.
- `knowledge/` (optional): a short design note for the future Finnhub holdings-aggregation
  engine (top-N holdings → per-holding cached industry → majority vote → Finviz group;
  curated overrides take precedence) so Phase 2 starts warm.

### 1.8 PWA release surface (user-facing change — all three together)
- Prepend a `docs/releases.json` `releases[]` entry: `version` (`YYYY.MM.DD`), `date`,
  `title` (e.g. "ETF lookups now show their true sector/industry"), `tag: "fix"`,
  `tab: "lookup"`, user-facing `notes[]`.
- Set top-level `current` to the new `version`.
- Bump `CACHE` in `docs/sw.js` (e.g. `finviz-vN` → `vN+1`).
- No new GUIDE metric. `tests/test_guide_releases.py` asserts
  `current === releases[0].version`.

### 1.9 Session handoff
Update `.session/session-notes.md` (Current Status block), `.session/WORK_LOG.md` (milestone),
`.session/SPRINT.md` (move ETF-1 to Done) — committed into the implementation PR *before*
merge so notes land on the base branch.

---

## Phase 2 — Finnhub holdings aggregation (demand-gated, documented only)

Not built now. When long-tail ETF demand justifies it: integrate Finnhub free
`/etf/holdings` (US), fetch top-N constituents, resolve each holding's Finviz industry via
the existing cached worker lookup, majority-vote to a Finviz group for ETFs **not** in the
curated map. Curated overrides remain the precedence layer (manual beats inferred). New
secret `FINNHUB_API_KEY` via `wrangler secret put`. Captured in the Phase 1 ADR.

---

## Verification (Phase 1)

```bash
# Worker unit tests (offline) + taxonomy/override regen
cd worker && npm install && npm test
npm run build:taxonomy          # regenerates etf_overrides.json; validation must pass
# PWA release/guide invariants
cd .. && python3 -m pytest tests/test_guide_releases.py -q
python3 -m pytest tests/ -q     # full suite
```

Functional PWA test (CLAUDE.md Playwright pattern — serve `docs/`, intercept worker
`/lookup`): mock `/lookup?t=COPX` → assert card renders **Basic Materials › Copper** with the
"ETF — classified by holdings theme" badge; `ITA` → **Industrials › Aerospace & Defense**;
`SPY` → "Broad market ETF" copy; `AAPL` → unchanged.

Post-deploy live check:
```bash
npm run deploy
for t in COPX ITA SMH XBI GDX; do curl -X DELETE ".../cache?t=$t"; done
curl ".../lookup?t=COPX"   # finviz_industry "Copper", classification_source "etf_override"
curl ".../lookup?t=ITA"    # finviz_industry "Aerospace & Defense"
```

## Open questions / assumptions
- **`isEtf` signal: validated.** Live FMP API confirmed `isEtf: true` for all 19 seed ETFs
  on 2026-06-20 (see Current architecture above). Not an open question — proceed with
  `Boolean(p.isEtf)` gate.
- Seed list names ~31 tickers (15 thematic + 11 sector SPDRs + 5 diversified); refine from
  real lookup logs over time. The "~30–50" range in the options table is directional.
- Leveraged/inverse ETFs (SOXL, etc.) are out of the initial seed — add as `thematic`
  pointing at the underlying industry only if demand appears.
- `etf_overrides.json` is bundled into the worker, so updates require a deploy (acceptable;
  same model as `taxonomy_map.json`).
