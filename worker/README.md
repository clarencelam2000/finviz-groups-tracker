# finviz-ticker-lookup (Cloudflare Worker)

Shared backend for the ticker lookup feature (TICKER-1 / Phase 2 of
`planning/PLAN_ticker_lookup.md`). Given a ticker, it returns the company's Finviz
sector/industry classification plus profile metadata, so both the PWA and the
Streamlit dashboard can join it to the performance CSVs.

```
GET /lookup?t=AAPL → { symbol, company_name, finviz_sector, finviz_industry,
                       industry_confidence, market_cap_b, exchange, image, ... }
GET /health        → { status, timestamp, kv_ok }
GET /stats         → { date, fmp_calls_today }
DELETE /cache?t=TICKER → { deleted }
OPTIONS *          → 204 + CORS headers
```

All errors return **HTTP 200** with `{ "error": "..." }` so front-ends branch on the
body, not the status code. Error codes: `ticker_not_found`, `rate_limited`,
`fmp_unavailable`, `fmp_timeout`, `internal_error`, `missing_symbol`.

---

## ⚠️ FMP endpoint note (important)

The plan originally specified `GET /api/v3/profile/{symbol}`. **That legacy endpoint
returns 401 for newer free keys** — FMP migrated to a `/stable/` API. This Worker calls
**`stable/profile?symbol={SYM}&apikey={KEY}`** with the post-migration field names
(`marketCap` raw int → `/1e9`, `exchange`, new `image` host, `isAdr`/`isFund`). Full
detail in `knowledge/fmp-api-findings.md`.

---

## Files

| Path | Purpose |
|------|---------|
| `src/index.js` | Worker handler: routing, KV cache, FMP fetch, response shaping |
| `src/taxonomy.js` | Runtime FMP→Finviz lookup (`lookupTaxonomy`, `lookupSector`) |
| `src/taxonomy_map.json` | Generated map (industries + sector fallback). **Do not hand-edit.** |
| `scripts/build_taxonomy.js` | Regenerates `taxonomy_map.json` from `../data/taxonomy_map.csv` |
| `test/*.test.js` | Vitest unit tests (no network, no real KV) |
| `wrangler.toml` | Worker + KV binding config |

The source of truth for the taxonomy is **`data/taxonomy_map.csv`** at the repo root
(built in TICKER-0 / PR #66). After editing it, run `npm run build:taxonomy`.

---

## Deployed instance

**Live:** `https://finviz-ticker-lookup.salmonbaby8.workers.dev` (deployed 2026-06-14).
This is the `WORKER_URL` that TICKER-2 (PWA) and TICKER-3 (Streamlit) wire into their
front-ends.

```bash
curl "https://finviz-ticker-lookup.salmonbaby8.workers.dev/health"        # {"status":"ok",...}
curl "https://finviz-ticker-lookup.salmonbaby8.workers.dev/lookup?t=AAPL" # Technology / Consumer Electronics
```

## One-time setup

You do **not** need the interactive `wrangler login` browser popup. Wrangler reads a
scoped **`CLOUDFLARE_API_TOKEN`** (plus `CLOUDFLARE_ACCOUNT_ID`) from the environment and
runs fully headless — this is how the live instance above was deployed, from a Claude Code
web session. Full writeup, including the least-privilege token scopes, is in
`knowledge/cloudflare-headless-deploy.md`.

Two ways to authenticate:

```bash
cd worker
npm install                              # dev deps (vitest, wrangler)

# Option A — headless (CI or Claude Code web): set these in the environment first
#   CLOUDFLARE_API_TOKEN  — "Edit Cloudflare Workers" template (Workers Scripts:Edit,
#                           Workers KV Storage:Edit, Account Settings:Read)
#   CLOUDFLARE_ACCOUNT_ID — from the CF dashboard sidebar
# Option B — local interactive: `npx wrangler login` (opens a browser)

# 1. Create the KV namespace; copy the printed id (already done for the live instance)
npx wrangler kv namespace create LOOKUP_CACHE
#   → put the id into wrangler.toml, replacing REPLACE_WITH_KV_NAMESPACE_ID

# 2. Store your FMP key as a Worker secret (NOT in any file)
echo "$FMP_API_KEY" | npx wrangler secret put FMP_API_KEY   # headless; or omit the pipe to be prompted
```

## Build, test, deploy

```bash
npm test                 # 34 unit tests, all offline
npm run build:taxonomy   # regenerate src/taxonomy_map.json from the CSV
npm run deploy           # builds taxonomy, then `wrangler deploy`
```

After deploy, Wrangler prints your Worker URL
(`https://finviz-ticker-lookup.<your-subdomain>.workers.dev`). Verify:

```bash
curl "https://finviz-ticker-lookup.<your-subdomain>.workers.dev/health"
curl "https://finviz-ticker-lookup.<your-subdomain>.workers.dev/lookup?t=AAPL"
curl "https://finviz-ticker-lookup.<your-subdomain>.workers.dev/lookup?t=FAKEXYZ"
```

Expected: `AAPL` → `Technology` / `Consumer Electronics` (confidence 1.0); a second
`AAPL` call within 30 days returns the cached value (same `cached_at`); `FAKEXYZ` →
`{"error":"ticker_not_found"}`.

Record the Worker URL — TICKER-2 (PWA) and TICKER-3 (Streamlit) need it as their
`WORKER_URL` constant.

---

## Local development

```bash
echo "FMP_API_KEY=your-key" > .dev.vars   # gitignored; used by `wrangler dev`
npx wrangler dev
```

## Response schema (success)

```json
{
  "symbol": "AAPL",
  "company_name": "Apple Inc.",
  "description": "...",
  "image": "https://images.financialmodelingprep.com/symbol/AAPL.png",
  "exchange": "NASDAQ",
  "country": "US",
  "market_cap_b": 3200.5,
  "ceo": "Tim Cook",
  "website": "https://www.apple.com",
  "fmp_sector": "Technology",
  "fmp_industry": "Consumer Electronics",
  "finviz_sector": "Technology",
  "finviz_industry": "Consumer Electronics",
  "industry_confidence": 1.0,
  "is_etf": false,
  "is_adr": false,
  "is_fund": false,
  "cached_at": "2026-06-14T00:00:00.000Z",
  "error": null
}
```

`finviz_industry` is `""` (empty string, not null) when the industry isn't in the map;
in that case `finviz_sector` still resolves via the sector fallback so the sector card
renders.

---

## Operational endpoints (TICKER-4 / Phase 5)

### `GET /stats` — FMP call counter

Returns today's FMP API call count and the current date. Used to monitor cache hit rates and detect when the cache is bypassed unexpectedly.

**Request:**
```bash
curl https://finviz-ticker-lookup.salmonbaby8.workers.dev/stats
```

**Response:**
```json
{
  "date": "2026-06-15",
  "fmp_calls_today": 42
}
```

**Counter details:**
- Incremented on every FMP cache-miss (not on cache hits).
- Stored in KV as `fmp_calls_YYYY-MM-DD` with a 7-day TTL (older keys auto-expire).
- Best-effort: counter failures never propagate to `/lookup` callers.

### `DELETE /cache?t=TICKER` — Manual cache bust

Manually delete a cached ticker entry to force a fresh FMP fetch on the next lookup.

**Request:**
```bash
curl -X DELETE "https://finviz-ticker-lookup.salmonbaby8.workers.dev/cache?t=AAPL"
```

**Response (success):**
```json
{
  "deleted": "AAPL"
}
```

**Response (missing ticker param):**
```json
{
  "error": "missing_symbol"
}
```

**Behavior:**
- Ticker is normalized to uppercase before deletion (e.g., `t=aapl` → deletes `AAPL`).
- Next `/lookup?t=AAPL` call will fetch fresh data from FMP and re-cache it.
- No auth needed for personal deployments; add auth middleware if exposed publicly.
