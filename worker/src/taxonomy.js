/**
 * taxonomy.js — runtime FMP→Finviz taxonomy lookup.
 *
 * taxonomy_map.json is generated from data/taxonomy_map.csv by
 * scripts/build_taxonomy.js. Re-run that script after editing the CSV.
 */
import taxonomy from './taxonomy_map.json';

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
