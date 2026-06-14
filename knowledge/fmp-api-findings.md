# FMP API findings (TICKER-0 taxonomy session, 2026-06-14)

Verified live against a free-tier FMP API key while building `data/taxonomy_map.csv`.

## ⚠️ Critical for Phase 2 (TICKER-1 Worker): the plan's endpoint is dead

`planning/PLAN_ticker_lookup.md` specifies `GET /api/v3/profile/{symbol}`. **That legacy
endpoint no longer works for newer free keys** — FMP migrated to a `/stable/` API.

| Endpoint | Result with free key |
|---|---|
| `https://financialmodelingprep.com/stable/profile?symbol=AAPL&apikey=KEY` | **200 ✅ use this** |
| `https://financialmodelingprep.com/api/v3/profile/AAPL?apikey=KEY` | 401 Invalid API KEY (legacy) |
| `https://financialmodelingprep.com/api/v4/...` | 403 Legacy Endpoint |
| `https://financialmodelingprep.com/stable/available-sectors` | 402 Payment Required (paid only) |
| `https://financialmodelingprep.com/stable/available-industries` | 402 Payment Required (paid only) |
| `https://financialmodelingprep.com/stable/profile-bulk` | 402 Payment Required (paid only) |

**Action for the Worker:** call `stable/profile?symbol={SYM}&apikey={KEY}`. Query param is
`symbol=`, not a path segment. Unknown ticker → returns `[]` (same as before).

### Field-name changes in the `stable/profile` response (vs. the plan's schema)

The plan assumed v3 field names. The `stable/profile` object differs:

| Plan / v3 field | `stable/profile` field | Notes |
|---|---|---|
| `mktCap` | `marketCap` | raw integer (AAPL ≈ 4.27e12). Worker must `/1e9` for `market_cap_b`. |
| `image` = `.../image-stock/AAPL.png` | `image` = `https://images.financialmodelingprep.com/symbol/AAPL.png` | host + path changed |
| `exchangeShortName` | `exchange` | e.g. `"NASDAQ"`. `exchangeFullName` also present. |
| — | `isAdr`, `isFund` | new booleans alongside `isEtf` |
| `sector`, `industry`, `companyName`, `description`, `ceo`, `website`, `country`, `ipoDate`, `isEtf`, `isActivelyTrading` | same names | unchanged |

Update the Worker's field extraction and the response-schema doc in Phase 2 accordingly.

## Rate limits

- Free tier hit **HTTP 429** after ~240 `stable/profile` calls in one session. Daily cap is
  real and lower than the "250/day" the plan assumes is comfortable. The 30-day KV cache makes
  this a non-issue at runtime (one call per ticker per 30 days), but bulk taxonomy-refresh
  fetches must be chunked across days or kept under ~200 calls.

## FMP vs Finviz taxonomy (basis for `data/taxonomy_map.csv`)

Sampled 242 profiles → **129 unique FMP industries** across all 11 sectors. Evidence saved to
`data/fmp_sample_profiles.json`.

**Sectors:** identical 11 names **except** FMP `Financial Services` = Finviz `Financial`.
One industry crosses sectors: FMP files **Solar** under `Energy`; Finviz tracks it under
`Technology` (`taxonomy_map.csv` uses Finviz's `Technology` so the sector card joins correctly).

**Industry naming patterns** (FMP → Finviz):
- Prefix style: `Financial - Credit Services` → `Credit Services`; `Medical - Devices` →
  `Medical Devices`; `Industrial - Machinery` → `Specialty Industrial Machinery`;
  `Chemicals - Specialty` → `Specialty Chemicals`; `Auto - Manufacturers` → `Auto Manufacturers`.
- Utilities: FMP `Regulated Electric` → Finviz `Utilities - Regulated Electric`.
- Telecom: FMP `Telecommunications Services` → Finviz `Telecom Services`.

**FMP is coarser than Finviz in 12 places** — these Finviz industries have NO distinct FMP
source and are therefore unreachable by the map (expected, not a bug):
`Airports & Air Services`, `Broadcasting`, `Business Equipment & Supplies`, `Coking Coal`,
`Gambling`, `Internet Retail`, `Other Precious Metals & Mining`, `Paper & Paper Products`,
`Pollution & Treatment Controls`, `Scientific & Technical Instruments`,
`Semiconductor Equipment & Materials`, `Textile Manufacturing`.
E.g. FMP `Coal` covers both Coking+Thermal; FMP `Semiconductors` includes equipment makers
(AMAT); FMP `Entertainment` includes broadcasters (FOXA, NXST); FMP `Specialty Retail`
includes internet retail (AMZN). The map picks the dominant Finviz target and marks these rows
`combined`/`ambiguous`/`broadened` with confidence < 0.8.

**12 low-confidence rows (< 0.8) flagged for periodic re-verification:** see `note` column
values `ambiguous`, `combined`, `broadened`. Plus 4 `not_in_sample` supplemental rows
(`Financial - Conglomerates`, `Insurance - Specialty`, `Real Estate - Development`,
`Shell Companies`) added from domain knowledge — harmless if FMP never emits them; verify on
next refresh.

## How to refresh the taxonomy

`available-industries` is paid-only, so the full FMP list can't be pulled directly on free tier.
Re-sample profiles instead: fetch `stable/profile?symbol=...` for a broad ticker basket
(see the throwaway used this session), dedupe `(sector, industry)`, and diff against the map.
Keep total calls under ~200/day to avoid the 429 cap.
