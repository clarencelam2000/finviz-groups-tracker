#!/usr/bin/env node
/**
 * build_taxonomy.js — convert data/taxonomy_map.csv → worker/src/taxonomy_map.json
 *                     and data/etf_overrides.csv → worker/src/etf_overrides.json
 *
 * The CSVs are the human-reviewed sources of truth.
 * The Worker imports the generated JSONs at runtime for O(1) lookups, so this
 * must be re-run whenever either CSV changes:
 *
 *   node scripts/build_taxonomy.js                 # default paths
 *   node scripts/build_taxonomy.js IN.csv OUT.json # explicit paths (taxonomy only)
 *
 * Taxonomy output shape:
 *   {
 *     "industries": { "<fmp_industry>": { finviz_industry, finviz_sector, confidence } },
 *     "sectors":    { "<fmp_sector>": "<finviz_sector>" }   // dominant mapping per FMP sector
 *   }
 *
 * ETF overrides output shape (keyed by uppercased ticker):
 *   { "COPX": { finviz_industry, finviz_sector, kind }, ... }
 *
 * Validation: every non-blank finviz_industry / finviz_sector in etf_overrides.csv
 * must exist verbatim in data/{industries,sectors}/snapshots.csv. The build exits
 * non-zero with a clear message on any unknown name, preventing silent typos.
 *
 * The sectors map is a fallback so an unmapped industry still resolves its sector
 * card. It uses the *most common* finviz_sector per fmp_sector, so cross-sector
 * outliers (e.g. FMP files Solar under Energy but Finviz tracks it under Technology)
 * don't corrupt the bulk Energy→Energy mapping.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));

const inPath = resolve(__dirname, process.argv[2] || '../../data/taxonomy_map.csv');
const outPath = resolve(__dirname, process.argv[3] || '../src/taxonomy_map.json');

// ETF override paths are always at fixed locations (not overridable via argv)
const etfOverridesInPath = resolve(__dirname, '../../data/etf_overrides.csv');
const etfOverridesOutPath = resolve(__dirname, '../src/etf_overrides.json');
const industriesSnapshotPath = resolve(__dirname, '../../data/industries/snapshots.csv');
const sectorsSnapshotPath = resolve(__dirname, '../../data/sectors/snapshots.csv');

/** Minimal RFC-4180 CSV parser (handles quoted fields with commas). */
export function parseCsv(text) {
  const rows = [];
  let field = '';
  let row = [];
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; } else { inQuotes = false; }
      } else {
        field += c;
      }
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ',') {
      row.push(field); field = '';
    } else if (c === '\n') {
      row.push(field); field = '';
      rows.push(row); row = [];
    } else if (c === '\r') {
      // ignore; handled by \n
    } else {
      field += c;
    }
  }
  if (field.length > 0 || row.length > 0) { row.push(field); rows.push(row); }
  return rows.filter((r) => r.length > 1 || (r.length === 1 && r[0] !== ''));
}

/** Build the {industries, sectors} taxonomy object from parsed CSV rows. */
export function buildTaxonomy(rows) {
  const header = rows[0];
  const idx = Object.fromEntries(header.map((h, i) => [h.trim(), i]));
  const industries = {};
  const sectorCounts = {}; // fmp_sector -> { finviz_sector: count }

  for (let i = 1; i < rows.length; i++) {
    const r = rows[i];
    const fmpIndustry = (r[idx.fmp_industry] || '').trim();
    const fmpSector = (r[idx.fmp_sector] || '').trim();
    const finvizIndustry = (r[idx.finviz_industry] || '').trim();
    const finvizSector = (r[idx.finviz_sector] || '').trim();
    const confidence = parseFloat(r[idx.confidence]);
    if (!fmpIndustry) continue;

    industries[fmpIndustry] = {
      finviz_industry: finvizIndustry,
      finviz_sector: finvizSector,
      confidence: Number.isFinite(confidence) ? confidence : 0,
    };

    if (fmpSector && finvizSector) {
      sectorCounts[fmpSector] = sectorCounts[fmpSector] || {};
      sectorCounts[fmpSector][finvizSector] = (sectorCounts[fmpSector][finvizSector] || 0) + 1;
    }
  }

  const sectors = {};
  for (const [fmpSector, counts] of Object.entries(sectorCounts)) {
    // pick the most common finviz_sector for this fmp_sector
    sectors[fmpSector] = Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];
  }

  return { industries, sectors };
}

/**
 * Extract the unique set of `name` values from a snapshots CSV string.
 * Used to build canonical Finviz group name sets for override validation.
 */
export function extractSnapshotNames(csvText) {
  const rows = parseCsv(csvText);
  if (rows.length < 2) return new Set();
  const header = rows[0];
  const nameIdx = header.findIndex((h) => h.trim() === 'name');
  if (nameIdx < 0) return new Set();
  const names = new Set();
  for (let i = 1; i < rows.length; i++) {
    const v = (rows[i][nameIdx] || '').trim();
    if (v) names.add(v);
  }
  return names;
}

/**
 * Build the etf_overrides lookup object from parsed CSV rows.
 * Validates non-blank finviz_industry / finviz_sector values against the
 * canonical Finviz name sets loaded from snapshots CSVs.
 *
 * @param {string[][]} rows — output of parseCsv(etf_overrides.csv)
 * @param {Set<string>} canonicalIndustries — from data/industries/snapshots.csv
 * @param {Set<string>} canonicalSectors — from data/sectors/snapshots.csv
 * @returns {{ overrides: Object, errors: string[] }}
 *
 * `errors` is empty on success. Non-empty means at least one unknown group name
 * was found; callers should exit non-zero and print the errors.
 */
export function buildEtfOverrides(rows, canonicalIndustries, canonicalSectors) {
  const header = rows[0];
  const idx = Object.fromEntries(header.map((h, i) => [h.trim(), i]));
  const overrides = {};
  const errors = [];

  for (let i = 1; i < rows.length; i++) {
    const r = rows[i];
    const ticker = (r[idx.ticker] || '').trim().toUpperCase();
    const finvizIndustry = (r[idx.finviz_industry] || '').trim();
    const finvizSector = (r[idx.finviz_sector] || '').trim();
    const kind = (r[idx.kind] || '').trim();

    if (!ticker || !kind) continue;

    if (finvizIndustry && !canonicalIndustries.has(finvizIndustry)) {
      errors.push(
        `Row ${i + 1} (${ticker}): unknown finviz_industry "${finvizIndustry}" — ` +
        'not found in data/industries/snapshots.csv',
      );
    }
    if (finvizSector && !canonicalSectors.has(finvizSector)) {
      errors.push(
        `Row ${i + 1} (${ticker}): unknown finviz_sector "${finvizSector}" — ` +
        'not found in data/sectors/snapshots.csv',
      );
    }

    overrides[ticker] = { finviz_industry: finvizIndustry, finviz_sector: finvizSector, kind };
  }

  return { overrides, errors };
}

// Run only when invoked directly (not when imported by tests).
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  // Build taxonomy
  const csv = readFileSync(inPath, 'utf8');
  const taxonomy = buildTaxonomy(parseCsv(csv));
  writeFileSync(outPath, JSON.stringify(taxonomy, null, 2) + '\n');
  const ni = Object.keys(taxonomy.industries).length;
  const ns = Object.keys(taxonomy.sectors).length;
  console.log(`Wrote ${outPath}: ${ni} industries, ${ns} sectors`);

  // Build ETF overrides with validation
  const etfCsv = readFileSync(etfOverridesInPath, 'utf8');
  const industriesCsv = readFileSync(industriesSnapshotPath, 'utf8');
  const sectorsCsv = readFileSync(sectorsSnapshotPath, 'utf8');
  const canonicalIndustries = extractSnapshotNames(industriesCsv);
  const canonicalSectors = extractSnapshotNames(sectorsCsv);
  const { overrides, errors } = buildEtfOverrides(parseCsv(etfCsv), canonicalIndustries, canonicalSectors);

  if (errors.length > 0) {
    console.error('ETF override validation FAILED — unknown Finviz group names:');
    errors.forEach((e) => console.error(`  ${e}`));
    process.exit(1);
  }

  writeFileSync(etfOverridesOutPath, JSON.stringify(overrides, null, 2) + '\n');
  console.log(`Wrote ${etfOverridesOutPath}: ${Object.keys(overrides).length} ETF overrides`);
}
