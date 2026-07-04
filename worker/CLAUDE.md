# worker/ — Cloudflare Worker (ticker lookup + cache ops)

> Loads only when working in `worker/`. See `worker/README.md` for setup/deploy commands.

## ETF override layer

ETF lookups use a curated override file (`data/etf_overrides.csv`) to correct FMP's
legal-entity classification ("Asset Management") with the actual thematic exposure.

**Source of truth:** `data/etf_overrides.csv` — columns `ticker, finviz_industry,
finviz_sector, etf_name, kind, note`. Three `kind` values:
- `thematic` — single industry (COPX→Copper, ITA→Aerospace & Defense, SMH→Semiconductors…)
- `sector` — sector only, no single industry (XLE→Energy, XLK→Technology… all 11 SPDRs)
- `diversified` — no group (SPY, QQQ, VTI, DIA, IWM; PWA shows an informational card)

**Build step:** `npm run build:taxonomy` (in `worker/`) reads both `taxonomy_map.csv`
and `etf_overrides.csv`, validates all Finviz names against live snapshot CSVs, and
emits `worker/src/taxonomy_map.json` + `worker/src/etf_overrides.json`. Exits non-zero
with a clear message on any unknown group name. If the `Build taxonomy` step fails in
CI (`.github/workflows/deploy-workers.yml`): it is a **data validation error**, not a
code error — an entry in `etf_overrides.csv` references a Finviz group name that
doesn't exist in the snapshot CSVs. Fix: correct the name and re-push.

**Runtime:** `lookupEtf(symbol)` in `taxonomy.js` checks `etf_overrides.json`. Applied
in `index.js` when `isEtf: true`. Response adds `classification_source` ("etf_override"
| "fmp_taxonomy") and `etf_kind` ("thematic" | "sector" | "diversified" | null).

**Post-deploy cache bust:** existing KV entries don't have the new fields until TTL
(30d). Bust manually with `DELETE /cache?t=TICKER` for each seed ETF — see
`worker/README.md` for the one-liner.

**ADR:** `knowledge/decisions/ADR-005-etf-classification-curated-first.md`

## Auto-deploy

`.github/workflows/deploy-workers.yml` triggers on push to the default branch when
`worker/**` or `worker-cron/**` change. Runs `build:taxonomy` + tests before deploying;
two independent jobs (one per worker, `worker/` and `worker-cron/`). Also triggerable
manually via `workflow_dispatch`. **No manual `npm run deploy` needed after merging
worker changes.**

- `wrangler deploy` does **not** touch secrets (`FMP_API_KEY`, `GITHUB_DISPATCH_TOKEN`),
  KV data, or cron expressions unless `wrangler.toml` changes.
- TODO(D1): update `branches:` in the workflow to `[main]` when the default branch is
  renamed; also update `DISPATCH_REF` in `worker-cron/wrangler.toml` at the same time.
