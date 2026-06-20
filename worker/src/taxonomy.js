/**
 * taxonomy.js — runtime FMP→Finviz taxonomy lookup.
 *
 * taxonomy_map.json and etf_overrides.json are generated from
 * data/taxonomy_map.csv and data/etf_overrides.csv by scripts/build_taxonomy.js.
 * Re-run that script after editing either CSV.
 */
import taxonomy from './taxonomy_map.json';
import etfOverrides from './etf_overrides.json';

const INDUSTRIES = taxonomy.industries || {};
const SECTORS = taxonomy.sectors || {};

/**
 * Map an FMP industry name to its Finviz industry/sector + confidence.
 * Unknown industry → finviz_industry "" so front-ends test for empty string.
 */
export function lookupTaxonomy(fmpIndustry) {
  const hit = fmpIndustry ? INDUSTRIES[fmpIndustry] : null;
  if (hit) {
    return {
      finviz_industry: hit.finviz_industry || '',
      finviz_sector: hit.finviz_sector || '',
      confidence: typeof hit.confidence === 'number' ? hit.confidence : 0,
    };
  }
  return { finviz_industry: '', finviz_sector: '', confidence: 0 };
}

/**
 * Fallback: map an FMP sector name to its Finviz sector. Used when the industry
 * isn't in the map but we can still show the sector card (graceful degradation).
 */
export function lookupSector(fmpSector) {
  return (fmpSector && SECTORS[fmpSector]) || '';
}

/**
 * Look up a curated ETF override by ticker symbol (uppercased).
 * Returns {finviz_industry, finviz_sector, kind} on hit, null on miss.
 * The override layer sits above FMP taxonomy — curated values win.
 * Source: data/etf_overrides.csv (rebuilt by scripts/build_taxonomy.js).
 */
export function lookupEtf(symbol) {
  const hit = symbol ? etfOverrides[symbol.toUpperCase()] : null;
  return hit || null;
}
