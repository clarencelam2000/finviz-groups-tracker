# PLAN: Ticker → Finviz Group Lookup (+ Future: Group → Stocks)

**Status:** Ready for implementation  
**Date authored:** 2026-06-14  
**Target branch:** `claude/elegant-babbage-hlxnfy` (default)  
**Sprint tasks:** TICKER-0 through TICKER-5 in `.session/SPRINT.md`

---

## Problem Statement

The dashboard surfaces Finviz sector/industry group performance (11 sectors, ~144 industries). The missing link: given a stock you're considering, which Finviz group is it in, and how is that group tracking right now?

The workflow this unlocks for swing trading:
1. A sector/industry looks strong in the dashboard
2. You have a stock idea (e.g., AAPL)
3. You look up the ticker → dashboard immediately shows: "Consumer Electronics is rank #3, up 5 spots this week, momentum 0.82 (top 18%)" — without you tabbing between views or mentally cross-referencing

Usage volume: ~20 lookups/day, single user.

---

## Architecture Overview

```
BUILD-TIME (once, offline, re-runnable):
  Finviz industries (data/industries/snapshots.csv, 144 names)
  + FMP company profiles (diverse sample via API)
  → Claude session maps FMP taxonomy → Finviz taxonomy
  → data/taxonomy_map.csv (human-reviewed, committed)

RUNTIME:
  Streamlit (local) ─┐
                     ├─→ CF Worker  GET /lookup?t=AAPL
  PWA (GitHub Pages)─┘       ├─ KV cache hit (30d TTL)? → return JSON
                            ├─ miss → FMP /api/v3/profile/{ticker}
                            │         → apply taxonomy_map
                            │         → write full profile to KV
                            └─ return: {symbol, company_name, finviz_sector,
                                        finviz_industry, industry_confidence,
                                        description, image, exchange,
                                        market_cap_b, fmp_sector, fmp_industry,
                                        cached_at, error}

  Each front-end joins finviz_sector/finviz_industry to performance data it
  already has from the existing Finviz CSVs (loaded separately):
    - Streamlit: load_snapshots / load_deltas from local data/ CSVs
    - PWA: already-fetched state.data.sectors / state.data.industries

  Front-end synthesizes: classification + live performance = trade context card
```

---

## Key Architecture Decisions (rationale)

### 1. Source: FMP (not yfinance or Finviz scraping)
- FMP `/api/v3/profile/{ticker}` is a single fast JSON call; free tier = 250/day
- FMP sector/industry taxonomy is GICS-based, closely matching Finviz's taxonomy — the translation surface is small
- yfinance scrapes Yahoo Finance; Yahoo uses a slightly different taxonomy and the scraper breaks frequently
- Finviz doesn't expose company→group classification via its groups URL

### 2. Taxonomy translation: static LLM-generated map (not runtime fuzzy matching)
- The FMP → Finviz taxonomy gap is a one-time ~144-item semantic matching job
- Runtime difflib/fuzzy string matching is blind to semantic equivalence (e.g., FMP "Drug Manufacturers — General" ≠ Finviz "Drug Manufacturers - Major" by edit distance, but they're the same group)
- **We generate the map once in a Claude Code session, human-review it, commit it as `data/taxonomy_map.csv`** — runtime lookup is O(1) dict lookup, deterministic, free, auditable
- Drift: Finviz and FMP rarely change their taxonomies. When they do, re-run the session. See TICKER-0 for the process; see Maintenance section for the trigger.

### 3. Shared backend: Cloudflare Worker (not direct FMP calls from each front-end)
- The PWA (`docs/index.html`) is a static GitHub Pages site — it cannot securely hold an API key
- A CF Worker (free tier: 100k requests/day) is the single normalization point; the FMP key lives only as a Wrangler secret
- Both Streamlit and the PWA call the same Worker endpoint, so classification is always consistent
- KV cache means the FMP call happens once per ticker per 30 days

### 4. KV cache TTL: 30 days
- Sector/industry classifications are near-permanent for most companies
- The exception is S&P index rebalancing (quarterly) and rare strategic pivots (e.g., a spinoff changing sector)
- 24 hours is far too aggressive — with 250 FMP calls/day free tier, repeat lookups waste quota
- 30 days is safe: even if TSLA gets reclassified (it happened in 2023), the stale cache resolves within a month
- Manual cache bust: delete the KV key via `wrangler kv key delete` or a `DELETE /cache?t=TICKER` endpoint

### 5. Cache full FMP profile payload
- The FMP `/profile` call returns many stable, useful fields beyond sector/industry
- Caching the full payload costs nothing extra (KV value size is not the constraint)
- Front-ends can optionally display company description, logo, CEO, etc. enriching the lookup result
- Cached fields: symbol, companyName, description, image (logo URL), exchange, country, mktCap, ceo, website, fullTimeEmployees, beta, ipoDate, isEtf, isActivelyTrading, plus our mapped finviz_sector/finviz_industry

### 6. Front-end priority: PWA first, then Streamlit
- The PWA is used ~10× more than the Streamlit dashboard (mobile-first, always accessible)
- Both share the same Worker, so the lookup logic is identical; front-end work is independent

### 7. End-user UX: trade context card, not raw data
- A ticker lookup should reduce mental load, not produce a table the user has to interpret
- The result synthesizes rank, delta, momentum, and perf into a single directional signal
- See "End-User UX Design" section below

---

## FMP API Reference (free tier)

**Profile endpoint** (used by the Worker):
```
GET https://financialmodelingprep.com/api/v3/profile/{symbol}?apikey={KEY}
Response: [{
  symbol, companyName, price, beta, mktCap, description,
  ceo, website, image, exchange, country, fullTimeEmployees,
  sector, industry,          ← FMP taxonomy names
  ipoDate, isEtf, isActivelyTrading, ...
}]
```
- Free tier: 250 calls/day. With 30d KV cache, this supports ~250 unique new tickers/day (never a real constraint for personal use).
- Unknown ticker: returns `[]` (empty array)

**Screener endpoint** (Phase 7 — future):
```
GET https://financialmodelingprep.com/api/v3/stock-screener
  ?sector=Technology&industry=Consumer+Electronics&limit=500&apikey={KEY}
Response: [{symbol, companyName, marketCap, sector, industry, exchange, country, ...}]
```
- Yes, this returns ALL stocks matching the filter (up to `limit`), sorted by market cap if you specify `order=marketCapDesc`. This is confirmed FMP behavior.
- For a sector like Technology, expect 200–500 results. Set `limit=500` for comprehensive coverage.
- Free tier: 1 screener call = 1 API call against the 250/day quota. With 7-day KV caching of screener results, personal use easily fits.

---

## End-User UX Design (trade context card)

The lookup result should answer "is this a good sector/industry context for a long?" in one glance.

**Layout (both PWA and Streamlit):**
```
╔══════════════════════════════════════════════════════════╗
║  Apple Inc. (AAPL)  ·  NASDAQ  ·  $3.2T mkt cap         ║
║  [Logo]  Technology  ›  Consumer Electronics             ║
║  Industry match: 95% confidence                          ║
╠══════════════════════════════════════════════════════════╣
║  INDUSTRY: Consumer Electronics                          ║
║  Rank: #3 of 144   ▲ +5 this week   ▲ +8 vs 30 days    ║
║  Momentum: ████████░░  0.82  (top 18%)                   ║
║  Week: +2.1%   Month: +4.3%   YTD: +12.1%               ║
╠══════════════════════════════════════════════════════════╣
║  SECTOR: Technology                                       ║
║  Rank: #2 of 11    ▲ +1 this week                        ║
║  Momentum: ███████░░░  0.75  (top 27%)                   ║
║  Week: +1.8%   Month: +3.1%   YTD: +9.4%                ║
╠══════════════════════════════════════════════════════════╣
║  ● SIGNAL: FAVORABLE                                     ║
║  Consumer Electronics strengthening (#3, ↑+5 this week). ║
║  Technology sector also strong (#2). Favorable context   ║
║  for a long entry.                                       ║
╚══════════════════════════════════════════════════════════╝
```

**Context signal logic (computed client-side, no LLM):**

```javascript
// score: 0.0 (bearish) to 1.0 (bullish)
function groupScore(deltaRow) {
  if (!deltaRow) return 0.5;
  let s = 0;
  if ((deltaRow.rank_week_delta_7d || 0) > 0) s += 0.3;   // improving rank this week
  if ((deltaRow.momentum_score || 0) > 0.6) s += 0.5;      // top-40% momentum
  if ((deltaRow.perf_week || 0) > 0) s += 0.2;             // positive weekly perf
  return s;
}

function contextSignal(indRow, secRow) {
  const i = groupScore(indRow), s = groupScore(secRow);
  const avg = (i + s) / 2;
  if (avg >= 0.6) return { label: "FAVORABLE", color: "green" };
  if (avg <= 0.3) return { label: "CAUTION",   color: "red" };
  return           { label: "MIXED",     color: "amber" };
}
```

**Graceful degradation:**
- Unknown ticker → "Ticker not found. Verify the symbol is a US-listed stock."
- Industry not in Finviz data → show sector card only; note "industry not separately tracked by Finviz"
- Confidence < 0.5 → show a warning badge "Low confidence match — verify manually"
- Worker down → "Unable to reach lookup service. Try again shortly."
- No perf data in CSVs (very early data days) → show classification only, omit performance cards

---

## Phase 0: Prerequisites (user actions, before any code)

These must be done by the user before implementation can be verified:

1. **FMP API key** — free tier at financialmodelingprep.com. Note: the free tier has 250 calls/day; that's more than enough for personal use with 30d KV caching.

2. **Cloudflare account** — free at cloudflare.com. Need:
   - Account created
   - Wrangler CLI installed locally: `npm install -g wrangler` then `wrangler login`
   - A KV namespace created: `wrangler kv namespace create LOOKUP_CACHE` → note the namespace ID
   - FMP key set as Wrangler secret: `wrangler secret put FMP_API_KEY`

3. **FMP industry/sector list** — to build the taxonomy map (Phase 1), fetch FMP's taxonomy by running profiles on a representative set of stocks:
   ```bash
   # Fetch ~10 diverse profiles to see FMP's sector/industry names
   curl "https://financialmodelingprep.com/api/v3/profile/AAPL,XOM,JPM,JNJ,AMZN,TSLA,BA,GLD,WMT,CVS?apikey=YOUR_KEY" \
     | python3 -c "import json,sys; d=json.load(sys.stdin); [print(f'{x[\"symbol\"]}: {x[\"sector\"]} / {x[\"industry\"]}') for x in d]"
   # Add more tickers from underrepresented sectors as needed
   # Save the full output to data/fmp_sample_profiles.json for the taxonomy session
   ```
   Alternatively: FMP's full industry taxonomy is available in their API docs at financialmodelingprep.com/developer/docs/stock-screener.

---

## Phase 1: Taxonomy Map (Claude Code session, one-time)

**Effort:** S (< 1h in a Claude session)  
**Output:** `data/taxonomy_map.csv` (committed, human-reviewed)  
**No code to write.** This is a Claude-session workflow, not a script.

**Why Claude session instead of a build script:** The taxonomy is ~144 rows of semantic matching. A Claude session can generate the entire map in one go with domain knowledge + verified examples. Taxonomies rarely drift (FMP and Finviz are both GICS-based). A build script adds complexity for a problem that only needs to be solved once.

### Process

In a **new** Claude Code session (keep this plan open; fresh context for the taxonomy work):

**Step 1 — Gather both taxonomies:**
```python
# Claude reads from our existing data
import pandas as pd
finviz_industries = sorted(pd.read_csv('data/industries/snapshots.csv')['name'].unique())
finviz_sectors    = sorted(pd.read_csv('data/sectors/snapshots.csv')['name'].unique())
# Print both lists for Claude to see
```

**Step 2 — Claude generates the mapping:**
Provide Claude the two lists and the FMP sample profiles from Phase 0. Ask Claude to produce a CSV with columns:
- `fmp_industry` — FMP's exact industry name (from their API response)
- `fmp_sector` — FMP's sector for that industry
- `finviz_industry` — closest Finviz industry name (verbatim from our list, or `""` if none maps cleanly)
- `finviz_sector` — corresponding Finviz sector name
- `confidence` — 0.0–1.0 (1.0 = exact match or trivially equivalent, 0.5 = semantic but different words, 0.0 = unmappable)
- `note` — one-word explanation for low confidence or blank industry (e.g., "ETF", "no_match", "macro")

**Step 3 — Human review (mandatory):**
- Spot-check every row with `confidence < 0.8`
- Verify all non-blank `finviz_industry` values are in `data/industries/snapshots.csv`
- Fix obvious errors (e.g., Claude hallucinating a Finviz name that doesn't exist — coerce to `""`)
- Common unmappable FMP categories: ETFs, SPACs, ADRs, foreign-only industries → leave `finviz_industry` blank

**Step 4 — Commit:**
```bash
git add data/taxonomy_map.csv
git commit -m "data: add fmp→finviz industry taxonomy map (144 rows, human-reviewed)"
```

### taxonomy_map.csv format
```
fmp_industry,fmp_sector,finviz_industry,finviz_sector,confidence,note
Drug Manufacturers—General,Healthcare,Drug Manufacturers - Major,Healthcare,0.95,name_variant
Consumer Electronics,Technology,Consumer Electronics,Technology,1.0,exact
Specialty Industrial Machinery,Industrials,Industrial Machinery,Industrials,0.9,shortening
Closed-End Fund - Equity,Financial Services,,Financial Services,0.0,ETF
```

### Acceptance
- All unique FMP industry values we know of are covered
- All non-blank `finviz_industry` values exist verbatim in `data/industries/snapshots.csv`
- No row has confidence > 1.0 or < 0.0
- Unmappable rows have `finviz_industry = ""` and a reason in `note`

---

## Phase 2: Cloudflare Worker

**Effort:** M (1–2h)  
**Prerequisite:** Phase 0 (CF account + KV namespace + FMP key), Phase 1 (taxonomy map)

### Files

```
worker/
  src/
    index.js           ← main Worker handler
    taxonomy.js        ← loads taxonomy_map.json (auto-generated from CSV)
  scripts/
    build_taxonomy.js  ← one-time: node scripts/build_taxonomy.js → src/taxonomy_map.json
  test/
    index.test.js      ← vitest + miniflare tests
  wrangler.toml        ← CF Worker + KV binding config
  package.json         ← wrangler + vitest deps
  README.md            ← deploy instructions
```

### wrangler.toml

```toml
name = "finviz-ticker-lookup"
main = "src/index.js"
compatibility_date = "2024-01-01"

[[kv_namespaces]]
binding = "LOOKUP_CACHE"
id = "YOUR_KV_NAMESPACE_ID"    # from: wrangler kv namespace create LOOKUP_CACHE

[vars]
CACHE_TTL_SECONDS = "2592000"  # 30 days
```

### Worker behavior (src/index.js)

```
GET /lookup?t=AAPL
  1. uppercase(t) → symbol
  2. KV.get(symbol) → hit? parse JSON, return with cache-control
  3. miss: fetch FMP /api/v3/profile/{symbol}?apikey=FMP_API_KEY
  4. empty response (unknown ticker) → {error: "ticker_not_found"}
  5. extract profile[0]: {sector, industry, companyName, description, image,
     exchange, mktCap, ceo, website, country, fullTimeEmployees, beta, ipoDate, isEtf}
  6. apply taxonomy: map (fmp_sector, fmp_industry) → (finviz_sector, finviz_industry, confidence)
  7. build response object (see schema below)
  8. KV.put(symbol, JSON.stringify(response), {expirationTtl: 2592000})
  9. return response

GET /health
  Returns {status: "ok", timestamp: ISO8601, kv_ok: bool (test a KV ping)}

OPTIONS (preflight)
  Returns 200 with CORS headers

All errors → HTTP 200 with {error: "..."} so front-ends can distinguish
  error types without catching HTTP errors
```

### Response schema

```json
{
  "symbol": "AAPL",
  "company_name": "Apple Inc.",
  "description": "Apple Inc. designs, manufactures, and markets...",
  "image": "https://financialmodelingprep.com/image-stock/AAPL.png",
  "exchange": "NASDAQ",
  "country": "US",
  "market_cap_b": 3200.5,
  "ceo": "Tim Cook",
  "website": "https://www.apple.com",
  "fmp_sector": "Technology",
  "fmp_industry": "Consumer Electronics",
  "finviz_sector": "Technology",
  "finviz_industry": "Consumer Electronics",
  "industry_confidence": 0.95,
  "cached_at": "2026-06-14T00:00:00Z",
  "error": null
}
```

On error: `{error: "ticker_not_found" | "fmp_unavailable" | "rate_limited" | "internal_error"}`
On unmapped industry: `finviz_industry: ""` (not null — front-end tests for empty string)

### CORS headers (all responses)

```
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, OPTIONS
Access-Control-Allow-Headers: Content-Type
```

This allows both the GitHub Pages PWA and a local Streamlit-served browser to call the Worker.

### Taxonomy loading

`scripts/build_taxonomy.js`: reads `../../data/taxonomy_map.csv`, outputs `src/taxonomy_map.json`:
```json
{
  "Consumer Electronics": {"finviz_industry": "Consumer Electronics", "finviz_sector": "Technology", "confidence": 1.0},
  "Drug Manufacturers—General": {"finviz_industry": "Drug Manufacturers - Major", "finviz_sector": "Healthcare", "confidence": 0.95},
  ...
}
```
Keyed by `fmp_industry`. Run: `node scripts/build_taxonomy.js` before `wrangler deploy`.

`taxonomy.js`: `export function lookupTaxonomy(fmpIndustry) → {finviz_industry, finviz_sector, confidence}`

### Logging (structured, appears in CF Logs dashboard)

Log one JSON object per request:
```javascript
console.log(JSON.stringify({
  ts: new Date().toISOString(),
  symbol,
  cache_hit: Boolean(cached),
  fmp_called: Boolean(!cached && !error),
  error: error || null,
  latency_ms: Date.now() - start,
}));
```

### FMP error handling

| FMP response | Action |
|---|---|
| `[]` (empty) | Return `{error: "ticker_not_found"}` |
| HTTP 429 | Return `{error: "rate_limited"}`, log with `console.error` |
| HTTP 5xx | Return `{error: "fmp_unavailable"}`, log |
| Timeout (>5s) | Return `{error: "fmp_timeout"}` |
| Unexpected schema | Return `{error: "internal_error"}`, log raw response |

### Tests (vitest + miniflare)

Install: `cd worker && npm install`

Test cases in `test/index.test.js`:
- **Cache hit**: pre-populate KV with a known response → Worker skips FMP, returns cached value
- **Cache miss → FMP call**: mock fetch to FMP → verify KV written, response returned
- **Taxonomy applied**: input FMP industry → verify finviz_industry in response
- **Unknown ticker**: FMP returns `[]` → `{error: "ticker_not_found"}`
- **FMP 429**: mock 429 → `{error: "rate_limited"}`
- **Unmapped industry**: confidence 0.0 in taxonomy → `finviz_industry: ""`
- **CORS**: OPTIONS preflight → 200 with correct headers
- **Health check**: GET /health → `{status: "ok"}`

Run: `npm test`

### Deployment

```bash
# Build taxonomy JSON from CSV
node scripts/build_taxonomy.js

# Set FMP key (one-time)
wrangler secret put FMP_API_KEY

# Deploy
wrangler deploy

# Verify
curl "https://finviz-ticker-lookup.YOUR_SUBDOMAIN.workers.dev/lookup?t=AAPL"
curl "https://finviz-ticker-lookup.YOUR_SUBDOMAIN.workers.dev/health"
```

### Acceptance

- `curl .../lookup?t=AAPL` → Technology / Consumer Electronics, confidence ≥ 0.9
- `curl .../lookup?t=AAPL` (second call, same session) → same response, `cached_at` unchanged (KV hit)
- `curl .../lookup?t=FAKEXYZ` → `{error: "ticker_not_found"}`
- `curl .../health` → `{status: "ok"}`
- Worker unit tests all pass: `npm test`

---

## Phase 3: PWA Lookup Tab (`docs/index.html`)

**Effort:** M (1–2h)  
**Prerequisite:** Phase 2 deployed (need `WORKER_URL`)  
**Priority:** Do this before Streamlit (Phase 4) — PWA is used ~10× more.

### Existing code to understand first

Before editing, read these sections of `docs/index.html` (IIFE at line 186):
- Constants: `REPO`, `BRANCH`, `URLS` (lines ~187–194) — add `WORKER_URL` here
- `state` object (line ~197) — add `lookup: {symbol: null, data: null, loading: false}`
- Tab system: `tab-btn[data-tab]` → `<section id="tab-NAME">` + `switchTab` (lines ~57–64, 1194–1209)
- Render dispatch in `render()` (lines ~1146–1152) — add `if (state.tab === 'lookup') renderLookup()`
- Helpers to reuse: `pf`, `fmtPct`, `perfColor`, `momentumStyle`, `escapeHtml`, `getLatest`
- Existing performance card idiom: look at how `moverCard` or the Strength tab renders a group row — replicate that style
- Event wiring (lines ~1260–1288) — add input listeners here

### Changes

**1. Add `WORKER_URL` constant** (near line 189):
```javascript
const WORKER_URL = 'https://finviz-ticker-lookup.YOUR_SUBDOMAIN.workers.dev';
```

**2. Extend `state`** (near line 197):
```javascript
lookup: { symbol: null, data: null, loading: false, error: null },
```

**3. Add tab button** (after the last existing `<button class="tab-btn">`, in `<nav id="tab-bar">`):
```html
<button class="tab-btn" data-tab="lookup">Lookup</button>
```

**4. Add tab panel** (new `<section>` before closing `</main>`, matching existing section structure):
```html
<section id="tab-lookup" class="tab-panel hidden">
  <div class="search-row">
    <input id="ticker-input" class="search-input" type="text"
           placeholder="Ticker (e.g. AAPL)" autocomplete="off"
           autocapitalize="characters" spellcheck="false">
    <button id="ticker-submit" class="pill-btn">Look up</button>
  </div>
  <div id="lookup-result"></div>
</section>
```

**5. `async function lookupTicker(symbol)`** (new function, near `fetchAIForDate`):
```javascript
async function lookupTicker(symbol) {
  const key = `lk_${symbol}`;
  const cached = sessionStorage.getItem(key);
  if (cached) return JSON.parse(cached);

  const resp = await fetch(`${WORKER_URL}/lookup?t=${encodeURIComponent(symbol)}`);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const data = await resp.json();
  sessionStorage.setItem(key, JSON.stringify(data));
  return data;
}
```

**6. `function renderLookup()`** (new function, near other render* functions):

When `state.lookup.loading` → show spinner  
When `state.lookup.error` → show red error card  
When `state.lookup.data`:
```javascript
function renderLookup() {
  const el = document.getElementById('lookup-result');
  if (!el) return;
  const { data, loading, error } = state.lookup;

  if (loading) { el.innerHTML = '<div class="spinner"></div>'; return; }
  if (!data && !error) { el.innerHTML = '<p class="muted">Enter a ticker above.</p>'; return; }
  if (error || data?.error) {
    const msg = error || data.error;
    el.innerHTML = `<div class="error-card">${escapeHtml(msg)}</div>`;
    return;
  }

  // Header
  const mktCap = data.market_cap_b ? `$${data.market_cap_b.toFixed(0)}B` : '';
  let html = `
    <div class="lookup-header">
      ${data.image ? `<img src="${escapeHtml(data.image)}" class="company-logo" onerror="this.style.display='none'">` : ''}
      <div>
        <div class="company-name">${escapeHtml(data.company_name)} <span class="ticker-badge">${escapeHtml(data.symbol)}</span></div>
        <div class="company-meta">${escapeHtml(data.exchange)} · ${mktCap}</div>
        <div class="classification">
          ${escapeHtml(data.finviz_sector || '?')} › ${escapeHtml(data.finviz_industry || 'N/A')}
          ${data.industry_confidence < 0.5 ? '<span class="low-conf-badge">Low confidence match</span>' : ''}
          ${data.industry_confidence >= 0.5 && data.finviz_industry ? `<span class="conf-pct">${Math.round(data.industry_confidence * 100)}% match</span>` : ''}
        </div>
      </div>
    </div>`;

  // Industry performance card (joined from already-loaded state.data)
  if (data.finviz_industry) {
    html += groupPerfCard(data.finviz_industry, 'industries', 'INDUSTRY');
  }

  // Sector performance card
  if (data.finviz_sector) {
    html += groupPerfCard(data.finviz_sector, 'sectors', 'SECTOR');
  }

  // Context signal
  const indRow = findGroupRow(data.finviz_industry, 'industries');
  const secRow = findGroupRow(data.finviz_sector, 'sectors');
  html += contextSignalCard(indRow, secRow, data.finviz_industry, data.finviz_sector);

  el.innerHTML = html;
}
```

**7. Helper functions:**

```javascript
// Find the latest delta row for a group name
function findGroupRow(name, groupKey) {
  if (!name || !state.data[groupKey]) return null;
  return state.data[groupKey].deltas?.find(r => r.name === name) || null;
}

// Build a performance card for a group (joins snap + delta data)
function groupPerfCard(name, groupKey, label) {
  const delta = findGroupRow(name, groupKey);
  const snap = state.data[groupKey]?.snapshots?.find(r => r.name === name);
  if (!delta && !snap) {
    return `<div class="group-card"><div class="group-card-label">${label}: ${escapeHtml(name)}</div>
      <p class="muted">Performance data not available yet.</p></div>`;
  }
  const n = groupKey === 'industries' ? 144 : 11;
  const rank = delta?.rank_week;
  const rankDelta7d = delta?.rank_week_delta_7d;
  const momentum = delta?.momentum_score;
  const momentumPct = momentum != null ? Math.round((1 - momentum) * 100) : null;
  const perfWeek = snap?.perf_week;
  const perfMonth = snap?.perf_month;
  const perfYtd = snap?.perf_ytd;

  const rankStr = rank ? `#${rank} of ${n}` : '–';
  const deltaStr = rankDelta7d != null ? (rankDelta7d > 0 ? `▲ +${rankDelta7d}` : rankDelta7d < 0 ? `▼ ${rankDelta7d}` : `= 0`) : '';
  const momStr = momentum != null ? `${momentum.toFixed(2)} (top ${momentumPct}%)` : '–';
  const momBar = momentum != null ? `<div class="mom-bar"><div class="mom-fill" style="width:${Math.round(momentum*100)}%"></div></div>` : '';

  return `
    <div class="group-card">
      <div class="group-card-label">${label}: ${escapeHtml(name)}</div>
      <div class="group-stat-row">
        <span class="stat-label">Rank</span>
        <span class="stat-value">${rankStr} ${deltaStr ? `<span class="${rankDelta7d > 0 ? 'up' : 'down'}">${deltaStr} this week</span>` : ''}</span>
      </div>
      <div class="group-stat-row">
        <span class="stat-label">Momentum</span>
        <span class="stat-value">${momBar} ${momStr}</span>
      </div>
      <div class="group-stat-row perf-row">
        <span class="stat-label">Perf</span>
        <span>Week <span class="${perfColor(perfWeek)}">${fmtPct(perfWeek)}</span> &nbsp;
              Month <span class="${perfColor(perfMonth)}">${fmtPct(perfMonth)}</span> &nbsp;
              YTD <span class="${perfColor(perfYtd)}">${fmtPct(perfYtd)}</span></span>
      </div>
    </div>`;
}

// Context signal (see algorithm in UX Design section)
function contextSignalCard(indRow, secRow, indName, secName) {
  function score(r) {
    if (!r) return 0.5;
    let s = 0;
    if ((parseFloat(r.rank_week_delta_7d) || 0) > 0) s += 0.3;
    if ((parseFloat(r.momentum_score) || 0) > 0.6) s += 0.5;
    if ((parseFloat(r.perf_week) || 0) > 0) s += 0.2;
    return s;
  }
  const i = score(indRow), s = score(secRow);
  const avg = (i + s) / 2;
  let label, cls, desc;
  if (avg >= 0.6) {
    label = '● SIGNAL: FAVORABLE'; cls = 'signal-green';
    desc = `${indName || 'Industry'} strengthening. ${secName || 'Sector'} also strong. Favorable context for a long.`;
  } else if (avg <= 0.3) {
    label = '● SIGNAL: CAUTION'; cls = 'signal-red';
    desc = `${indName || 'Industry'} and/or ${secName || 'sector'} showing weakness. Review before entering a long.`;
  } else {
    label = '● SIGNAL: MIXED'; cls = 'signal-amber';
    desc = 'Sector and industry diverging or neutral. Check individual group trends.';
  }
  return `<div class="signal-card ${cls}"><div class="signal-label">${label}</div><div class="signal-desc">${escapeHtml(desc)}</div></div>`;
}
```

**8. Wire events** (near existing wiring section, ~line 1269):
```javascript
const tickerInput = document.getElementById('ticker-input');
const tickerSubmit = document.getElementById('ticker-submit');

async function doLookup() {
  const sym = (tickerInput.value || '').trim().toUpperCase();
  if (!sym) return;
  state.lookup = { symbol: sym, data: null, loading: true, error: null };
  renderLookup();
  try {
    const data = await lookupTicker(sym);
    state.lookup = { symbol: sym, data, loading: false, error: null };
  } catch (e) {
    state.lookup = { symbol: sym, data: null, loading: false, error: e.message };
  }
  renderLookup();
}

tickerSubmit?.addEventListener('click', doLookup);
tickerInput?.addEventListener('keydown', e => { if (e.key === 'Enter') doLookup(); });
```

**9. Update `render()` dispatch** (near line 1146):
```javascript
if (state.tab === 'lookup') renderLookup();
```

**10. CSS additions** — add to the existing `<style>` block:
```css
.lookup-header { display: flex; gap: 12px; align-items: flex-start; margin-bottom: 16px; }
.company-logo { width: 48px; height: 48px; border-radius: 8px; object-fit: contain; }
.company-name { font-size: 1.1rem; font-weight: 600; }
.ticker-badge { background: #334155; padding: 2px 6px; border-radius: 4px; font-size: 0.85rem; }
.company-meta { font-size: 0.8rem; color: #94a3b8; }
.classification { font-size: 0.9rem; margin-top: 4px; }
.conf-pct { color: #94a3b8; font-size: 0.8rem; margin-left: 6px; }
.low-conf-badge { background: #78350f; color: #fde68a; padding: 1px 6px; border-radius: 4px; font-size: 0.75rem; margin-left: 6px; }
.group-card { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 12px; margin-bottom: 12px; }
.group-card-label { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; margin-bottom: 8px; }
.group-stat-row { display: flex; justify-content: space-between; align-items: center; font-size: 0.85rem; margin-bottom: 4px; }
.stat-label { color: #64748b; }
.mom-bar { display: inline-block; width: 80px; height: 6px; background: #334155; border-radius: 3px; vertical-align: middle; }
.mom-fill { height: 100%; background: #22c55e; border-radius: 3px; }
.up { color: #22c55e; }
.down { color: #ef4444; }
.signal-card { border-radius: 8px; padding: 12px 16px; margin-top: 8px; }
.signal-green { background: #14532d; border: 1px solid #22c55e; }
.signal-red { background: #450a0a; border: 1px solid #ef4444; }
.signal-amber { background: #422006; border: 1px solid #f59e0b; }
.signal-label { font-weight: 600; margin-bottom: 4px; }
.signal-desc { font-size: 0.85rem; color: #cbd5e1; }
.error-card { background: #450a0a; border: 1px solid #ef4444; border-radius: 8px; padding: 12px; }
.search-row { display: flex; gap: 8px; margin-bottom: 16px; }
.search-input { flex: 1; background: #1e293b; border: 1px solid #334155; border-radius: 6px;
  padding: 8px 12px; color: #f1f5f9; font-size: 1rem; outline: none; }
.pill-btn { background: #3b82f6; color: white; border: none; border-radius: 6px;
  padding: 8px 16px; cursor: pointer; font-size: 0.9rem; }
```

### Acceptance
- Lookup tab visible in nav
- AAPL → card shows "Apple Inc.", "Technology › Consumer Electronics", 95% confidence
- Industry and sector performance cards show rank, momentum, perf from the CSVs
- Context signal shows FAVORABLE (green card)
- FAKEXYZ → error card "ticker_not_found"
- Worker down (kill Worker) → error card with message
- Enter key triggers lookup
- Second lookup of same ticker is instant (sessionStorage cache)

---

## Phase 4: Streamlit Lookup Tab (`dashboard/app.py`)

**Effort:** M (1–2h)  
**Prerequisite:** Phase 2 deployed

### New file: `dashboard/worker_client.py`

Pure requests wrapper — no streamlit import, so it's unit-testable:
```python
import requests

def lookup_ticker(symbol: str, worker_url: str, timeout: int = 10) -> dict:
    try:
        resp = requests.get(worker_url, params={"t": symbol.upper()}, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        return {"error": "timeout"}
    except requests.exceptions.HTTPError as e:
        return {"error": f"http_{e.response.status_code}"}
    except Exception as e:
        return {"error": str(e)}
```

### Changes to `dashboard/app.py`

**1. Add import and config** (after existing imports, before tab definitions):
```python
import os
from dashboard.worker_client import lookup_ticker

WORKER_URL = (
    st.secrets.get("WORKER_URL", None)
    or os.getenv("WORKER_URL", "https://finviz-ticker-lookup.YOUR_SUBDOMAIN.workers.dev")
)
```

**2. Add `_group_row` pure helper** (before tab block, after `load_deltas`):
```python
def _group_row(name: str, group_type: str, snap_df, delta_df) -> dict | None:
    snap = snap_df[snap_df["name"] == name]
    delta = delta_df[delta_df["name"] == name]
    if snap.empty and delta.empty:
        return None
    row = {}
    if not snap.empty:
        row.update(snap.iloc[0].to_dict())
    if not delta.empty:
        row.update(delta.iloc[0].to_dict())
    return row
```

**3. Add `_render_group_card` helper**:
```python
def _render_group_card(name: str, group_type: str):
    """Render rank/momentum/perf card for a Finviz group name."""
    snap_df = load_snapshots(group_type)
    delta_df = load_deltas(group_type)
    row = _group_row(name, group_type, snap_df, delta_df)
    if row is None:
        st.info(f"No performance data for **{name}** yet.")
        return
    rank = row.get("rank_week")
    n = 11 if group_type == "Sectors" else 144
    delta7 = row.get("rank_week_delta_7d")
    momentum = row.get("momentum_score")
    perf_week = row.get("perf_week")
    perf_month = row.get("perf_month")
    perf_ytd = row.get("perf_ytd")

    col1, col2, col3 = st.columns(3)
    with col1:
        rank_str = f"#{int(rank)} of {n}" if pd.notna(rank) else "–"
        delta_str = f" (▲ +{int(delta7)} this week)" if pd.notna(delta7) and delta7 > 0 \
               else f" (▼ {int(delta7)} this week)" if pd.notna(delta7) and delta7 < 0 else ""
        st.metric("Rank this week", rank_str, delta=delta_str if delta_str else None)
    with col2:
        mom_str = f"{momentum:.2f}" if pd.notna(momentum) else "–"
        pct = f"top {int((1-momentum)*100)}%" if pd.notna(momentum) else ""
        st.metric("Momentum", mom_str, delta=pct)
    with col3:
        perf_str = f"W: {perf_week:+.1f}%  M: {perf_month:+.1f}%  YTD: {perf_ytd:+.1f}%" \
                   if all(pd.notna(v) for v in [perf_week, perf_month, perf_ytd]) else "–"
        st.text(perf_str)
```

**4. Extend tab list** (line ~176):
```python
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "Snapshot", "Top Movers", "Time Series", "Heatmap",
    "Momentum", "Strength", "AI Insights", "Ticker Lookup"
])
```

**5. Tab 8 content** (at the end of the file, inside `with tab8:`):
```python
with tab8:
    st.subheader("Ticker Lookup")
    symbol = st.text_input("Ticker symbol", placeholder="e.g. AAPL", max_chars=10).strip().upper()

    if symbol:
        with st.spinner(f"Looking up {symbol}..."):
            result = lookup_ticker(symbol, WORKER_URL)

        if result.get("error"):
            err = result["error"]
            if err == "ticker_not_found":
                st.warning(f"'{symbol}' not found. Check the ticker is a US-listed stock.")
            elif err in ("timeout", "fmp_unavailable"):
                st.warning("Lookup service unavailable. Try again in a moment.")
            else:
                st.warning(f"Lookup error: {err}")
        else:
            mktcap = f"${result['market_cap_b']:.0f}B" if result.get("market_cap_b") else ""
            st.markdown(f"## {result.get('company_name', symbol)} `{symbol}`")
            st.caption(f"{result.get('exchange', '')} · {mktcap}")
            if result.get("description"):
                with st.expander("Company description"):
                    st.write(result["description"])

            finviz_sector = result.get("finviz_sector")
            finviz_industry = result.get("finviz_industry")
            confidence = result.get("industry_confidence", 0)

            st.markdown(f"**Finviz Classification:** {finviz_sector} › {finviz_industry or '(no industry match)'}")
            if confidence < 0.5 and finviz_industry:
                st.caption(f"⚠️ Low confidence match ({confidence:.0%}) — verify manually")
            elif finviz_industry:
                st.caption(f"Industry match: {confidence:.0%} confidence")

            if finviz_industry:
                st.markdown(f"### Industry: {finviz_industry}")
                _render_group_card(finviz_industry, "Industries")

            if finviz_sector:
                st.markdown(f"### Sector: {finviz_sector}")
                _render_group_card(finviz_sector, "Sectors")
```

### `requirements.txt` additions
```
requests==2.33.1
```
(It's available transitively but a new direct import must be pinned.)

### `requirements-test.txt` additions
```
requests==2.33.1
```

### New file: `tests/test_worker_client.py`
```python
from unittest.mock import MagicMock, patch
import pytest
from dashboard.worker_client import lookup_ticker

def test_success():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"symbol": "AAPL", "finviz_sector": "Technology"}
    mock_resp.raise_for_status.return_value = None
    with patch("dashboard.worker_client.requests.get", return_value=mock_resp) as m:
        result = lookup_ticker("aapl", "https://example.com")
        m.assert_called_once_with("https://example.com", params={"t": "AAPL"}, timeout=10)
    assert result["finviz_sector"] == "Technology"

def test_timeout():
    import requests
    with patch("dashboard.worker_client.requests.get", side_effect=requests.exceptions.Timeout):
        result = lookup_ticker("AAPL", "https://example.com")
    assert result["error"] == "timeout"

def test_http_error():
    import requests
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    with patch("dashboard.worker_client.requests.get",
               side_effect=requests.exceptions.HTTPError(response=mock_resp)):
        result = lookup_ticker("AAPL", "https://example.com")
    assert "http_" in result["error"]
```

Also add test for `_group_row` in a new test function in a conftest fixture or `tests/test_app_helpers.py`:
- Provide a minimal snap_df + delta_df → verify correct row returned
- Name not found → returns None

### Acceptance
- Tab 8 visible in Streamlit
- AAPL → header, classification, industry + sector cards
- Worker down → `st.warning` (no crash)
- `pytest tests/ -v` passes including new tests

---

## Phase 5: Operations / Logging / Monitoring

**Effort:** S (< 1h setup + ongoing monthly checks)  
**Prerequisite:** Phase 2 deployed

This phase is about **knowing when things break before the user notices**.

### CF Worker analytics (no setup required — already on)

CF Workers free plan includes built-in analytics:
- Log in to cloudflare.com → Workers & Pages → finviz-ticker-lookup → Metrics tab
- Tracks: requests/day, error rate, CPU time, subrequest count
- Bookmark this URL; check it monthly or when something feels off

**What to look for:**
- Sudden error rate spike → likely FMP quota exhausted or a CF outage
- Zero requests for weekdays → something is broken (Worker deleted? URL changed?)
- CPU time spike → unusual response payload size

### CF Worker logs (real-time, for debugging)

```bash
wrangler tail  # streams live logs from the Worker to your terminal
```

The structured `console.log` from Phase 2 makes each request readable:
```json
{"ts":"2026-06-14T18:00:00Z","symbol":"AAPL","cache_hit":true,"fmp_called":false,"error":null,"latency_ms":12}
```

Use `wrangler tail --filter-status error` to see only errors.

### FMP quota tracking

The Worker should count FMP calls in a KV counter (daily):
```javascript
// In the Worker, after a successful FMP call (cache miss path only):
const dayKey = `fmp_calls_${new Date().toISOString().slice(0, 10)}`;
const count = parseInt(await LOOKUP_CACHE.get(dayKey) || '0', 10);
await LOOKUP_CACHE.put(dayKey, String(count + 1), { expirationTtl: 86400 * 7 });
```

Add a counter endpoint for visibility:
```
GET /stats → {date, fmp_calls_today, total_kv_entries_approx}
```

Check this weekly for the first month, then monthly. Alert threshold: if `fmp_calls_today > 200`, investigate (something is bypassing the KV cache).

### Health check (automated ping)

Optional but recommended: use a free uptime service (e.g., healthchecks.io, uptimerobot.com) to ping `GET /health` every 10 minutes and alert on failure.

```bash
# Test the health endpoint
curl "https://finviz-ticker-lookup.YOUR_SUBDOMAIN.workers.dev/health"
# Expected: {"status":"ok","timestamp":"2026-06-14T18:00:00Z","kv_ok":true}
```

### Cache management (manual, as-needed)

When you need to bust a specific ticker's cache (e.g., after a known sector reclassification):
```bash
# Delete a specific ticker from KV
wrangler kv key delete --namespace-id YOUR_KV_NS_ID "TSLA"

# List keys to inspect what's cached
wrangler kv key list --namespace-id YOUR_KV_NS_ID
```

Add a `DELETE /cache?t=TICKER` endpoint (optional, admin use only — no auth needed for personal use):
```javascript
if (method === 'DELETE' && pathname === '/cache') {
  const sym = url.searchParams.get('t')?.toUpperCase();
  if (sym) await LOOKUP_CACHE.delete(sym);
  return jsonResponse({deleted: sym});
}
```

### Monthly maintenance checklist (add to SPRINT.md as recurring)

- [ ] Check CF analytics dashboard — error rate < 1%?
- [ ] Check FMP quota: `curl .../stats` — calls/day well below 250?
- [ ] Review any new sectors/industries in FMP (run `curl /profile/NEW_TICKER_IN_NEW_SECTOR`)
- [ ] Verify taxonomy still accurate for a few tickers across different sectors
- [ ] Run `pytest tests/ -v` — still green?

---

## Phase 6: Verification

End-to-end test across all three surfaces. Do this after Phases 1–5 are complete.

### Taxonomy check
```python
import pandas as pd
tm = pd.read_csv('data/taxonomy_map.csv')
finviz_inds = set(pd.read_csv('data/industries/snapshots.csv')['name'].unique())
# All non-blank finviz_industry values must exist in our snapshots
mapped = set(tm[tm['finviz_industry'] != '']['finviz_industry'])
assert mapped.issubset(finviz_inds), f"Unknown Finviz names: {mapped - finviz_inds}"
# confidence in [0,1]
assert (tm['confidence'] >= 0).all() and (tm['confidence'] <= 1).all()
print(f"Taxonomy: {len(tm)} rows, {len(mapped)} mapped, {len(tm)-len(mapped)} unmapped")
```

### Worker cross-check
```bash
# Diverse tickers across sectors
for t in AAPL XOM JPM JNJ AMZN TSLA BA GLD WMT CVS; do
  curl -s "https://finviz-ticker-lookup.YOUR_SUBDOMAIN.workers.dev/lookup?t=$t" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{d[\"symbol\"]}: {d[\"finviz_sector\"]} / {d[\"finviz_industry\"]}')"
done
# Verify: same sector/industry as Finviz groups page manually checked for a few
```

### Front-end parity check
Same ticker in PWA Lookup tab and Streamlit Lookup tab → identical `finviz_sector` and `finviz_industry` (both call the same Worker → same KV entry → same values).

### Performance data joined correctly
- AAPL → Consumer Electronics → industry card shows the same rank/momentum/perf as the Momentum tab's Consumer Electronics row
- Technology → sector card shows same data as the Snapshot tab's Technology sector row

### No secrets committed
```bash
git grep -r "FMP_API_KEY" -- ':!worker/wrangler.toml'  # should match nothing
# wrangler.toml should only contain the binding name, not the value
```

---

## Phase 7 (Future): Sector/Industry → Stocks Screener

**Status:** Designed but NOT started. Implement after Phases 1–6 are stable and used.  
**Why it's architecturally aligned:** The Worker already handles FMP API calls and KV caching. Adding a `/stocks` endpoint reuses the same infrastructure; no new dependencies.

### What this enables

"Consumer Electronics is ranked #3 and trending up — what stocks are in it?"

The Lookup tab (or any group card anywhere in the dashboard) gains a "Show stocks in this group" button that returns the top stocks by market cap.

### FMP screener confirmed

```
GET https://financialmodelingprep.com/api/v3/stock-screener
  ?sector=Technology&industry=Consumer+Electronics
  &limit=100&apikey={KEY}
```

Response: array of `{symbol, companyName, marketCap, sector, industry, exchange, country}`, sorted by market cap descending when `limit` is used. **FMP does return ALL stocks in the group, up to the limit.** This is confirmed FMP behavior on their free tier.

**Note on terminology:** FMP uses their own sector/industry names. To call the screener for a Finviz group, we reverse-lookup the taxonomy map (`finviz_industry` → `fmp_industry`, `finviz_sector` → `fmp_sector`).

### New Worker endpoint

```
GET /stocks?finviz_sector=Technology&finviz_industry=Consumer+Electronics
  → [{symbol, company_name, market_cap_b, exchange, country}] (top 25 by mkt cap)
  → KV cache 7 days (sector composition changes slowly but not as rarely as individual classifications)
  → error: {error: "sector_not_found"} if no taxonomy reverse match
```

### Design

1. **Reverse taxonomy lookup:** `data/taxonomy_map.csv` already has `finviz_sector` and `finviz_industry`. Add a second lookup object in `taxonomy.js` keyed by `finviz_industry → fmp_industry` for the reverse direction.
2. **Screener call:** `fetch(FMP_SCREENER_URL + params)` → parse → top 25 by `marketCap` → store in KV.
3. **PWA integration:** on any group card (industry or sector), add a "▶ Show stocks" toggle that calls `/stocks?...` and renders a compact table below the card.
4. **Streamlit integration:** similar — a button in the tab 8 group card that calls `/stocks?...` and renders with `st.dataframe`.

### KV budget concern
Screener results are larger than profile results. With 144 industries × ~5KB each = ~720KB total KV storage. CF free tier = 1GB. Not a concern.

### FMP quota concern
With 250 calls/day and 7-day KV caching: even if a user browses 10 different sectors/industries per day (unlikely), that's 10 calls/day leaving 240 for ticker lookups. Fine.

---

## Maintenance Tasks

These are **not one-time** — they're recurring operational items. Add to SPRINT.md or your calendar.

### Taxonomy refresh (as-needed, expected ~1×/year)
**Trigger:** FMP renames an industry, or Finviz adds/renames a group, or you notice a ticker being mapped to a wrong Finviz group.

**Process:**
1. Open a new Claude Code session
2. Pull the latest `data/industries/snapshots.csv` (for current Finviz names)
3. Fetch FMP profiles for a few tickers in the changed categories
4. Claude reviews the diff and updates `data/taxonomy_map.csv`
5. Human review + commit + rebuild `worker/src/taxonomy_map.json` + `wrangler deploy`

**Detection:** If you notice AAPL returning a wrong Finviz industry, check:
- `data/taxonomy_map.csv` — is the FMP industry name still current?
- `curl .../lookup?t=AAPL` — what does FMP call it now?

### Worker dependency updates (2×/year)
```bash
cd worker && npm outdated  # check for wrangler and vitest updates
npm update
npm test                   # verify tests still pass
wrangler deploy
```

### FMP API key renewal
FMP free tier keys do not expire but FMP's API may change. If the Worker starts returning `fmp_unavailable` errors, verify with:
```bash
curl "https://financialmodelingprep.com/api/v3/profile/AAPL?apikey=YOUR_KEY"
```
If the API shape changed (new response structure), update the Worker's field extraction.

---

## Key Decisions Log

| Decision | Rationale | Alternatives considered |
|---|---|---|
| Source: FMP | GICS-based taxonomy ≈ Finviz's; single JSON call; reliable free tier | yfinance (brittle, different taxonomy), Yahoo Finance (blocks scraping), Polygon.io (paid) |
| Taxonomy: static LLM-generated CSV | ~144 rows, one-time semantic job; O(1) runtime lookup; auditable | Runtime difflib (blind to semantics), runtime LLM call (latency + cost + non-deterministic) |
| Taxonomy generator: Claude session | Simple, no extra code; taxonomy changes rarely | Build script using Gemini API (adds complexity for a once-a-year task) |
| Backend: CF Worker | Only way to hide FMP key from static PWA; free tier ample for personal use | Direct FMP calls from Streamlit only (leaves PWA without lookup), CORS proxy (less control) |
| KV TTL: 30 days | Sector classifications are near-permanent; 24h wastes FMP quota; 30d is safe even with quarterly index rebalancing | 24h (too short), 7 days (more conservative but unnecessary) |
| Cache full FMP profile | No extra cost; richer result card; future-proofs Phase 7 | Cache only sector/industry (simpler but wastes the FMP call's other data) |
| Front-end priority: PWA first | PWA used ~10× more; both share same Worker, so switching order has no cost | Streamlit first (user preference said otherwise) |
| Context signal: rule-based | Deterministic, instant, no API call; readable formula | LLM-generated signal (latency, cost, non-deterministic for a simple decision) |
| Phase 7 (screener): not started | "Built forward, not walled off" — same Worker infrastructure extends cleanly; don't add scope before the forward direction is validated | Include in initial scope (premature given usage uncertainty) |
