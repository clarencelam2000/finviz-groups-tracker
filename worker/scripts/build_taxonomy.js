#!/usr/bin/env node
/**
 * build_taxonomy.js — convert data/taxonomy_map.csv → worker/src/taxonomy_map.json
 *
 * The CSV is the human-reviewed source of truth (built in TICKER-0 / PR #66).
 * The Worker imports the generated JSON at runtime for O(1) lookups, so this must
 * be re-run whenever data/taxonomy_map.csv changes:
 *
 *   node scripts/build_taxonomy.js                 # default paths
 *   node scripts/build_taxonomy.js IN.csv OUT.json # explicit paths
 *
 * Output shape:
 *   {
 *     "industries": { "<fmp_industry>": { finviz_industry, finviz_sector, confidence } },
 *     "sectors":    { "<fmp_sector>": "<finviz_sector>" }   // dominant mapping per FMP sector
 *   }
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

// Run only when invoked directly (not when imported by tests).
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const csv = readFileSync(inPath, 'utf8');
  const taxonomy = buildTaxonomy(parseCsv(csv));
  writeFileSync(outPath, JSON.stringify(taxonomy, null, 2) + '\n');
  const ni = Object.keys(taxonomy.industries).length;
  const ns = Object.keys(taxonomy.sectors).length;
  console.log(`Wrote ${outPath}: ${ni} industries, ${ns} sectors`);
}
