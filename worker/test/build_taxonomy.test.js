import { describe, it, expect } from 'vitest';
import { parseCsv, buildTaxonomy, extractSnapshotNames, buildEtfOverrides } from '../scripts/build_taxonomy.js';

describe('parseCsv', () => {
  it('parses simple rows', () => {
    const rows = parseCsv('a,b,c\n1,2,3\n');
    expect(rows).toEqual([['a', 'b', 'c'], ['1', '2', '3']]);
  });

  it('handles quoted fields containing commas', () => {
    const rows = parseCsv('name,sector\n"Paper, Lumber & Forest Products",Basic Materials\n');
    expect(rows[1][0]).toBe('Paper, Lumber & Forest Products');
    expect(rows[1][1]).toBe('Basic Materials');
  });

  it('handles escaped double quotes', () => {
    const rows = parseCsv('x\n"a ""b"" c"\n');
    expect(rows[1][0]).toBe('a "b" c');
  });
});

describe('buildTaxonomy', () => {
  const rows = parseCsv(
    'fmp_industry,fmp_sector,finviz_industry,finviz_sector,confidence,note\n' +
      'Consumer Electronics,Technology,Consumer Electronics,Technology,1.0,exact\n' +
      'Solar,Energy,Solar,Technology,0.9,cross_sector\n' +
      'Oil & Gas,Energy,Oil & Gas E&P,Energy,1.0,exact\n' +
      'Oil Services,Energy,Oil & Gas Equipment,Energy,1.0,exact\n' +
      'Credit Services,Financial Services,Credit Services,Financial,1.0,exact\n',
  );

  it('builds an industries map keyed by fmp_industry', () => {
    const t = buildTaxonomy(rows);
    expect(t.industries['Consumer Electronics']).toEqual({
      finviz_industry: 'Consumer Electronics',
      finviz_sector: 'Technology',
      confidence: 1,
    });
  });

  it('picks the dominant finviz_sector per fmp_sector (ignores cross-sector outliers)', () => {
    const t = buildTaxonomy(rows);
    // Energy appears 3× → Energy (2) beats Technology (1, the Solar outlier)
    expect(t.sectors['Energy']).toBe('Energy');
  });

  it('maps Financial Services → Financial', () => {
    const t = buildTaxonomy(rows);
    expect(t.sectors['Financial Services']).toBe('Financial');
  });

  it('defaults non-numeric confidence to 0', () => {
    const r = parseCsv('fmp_industry,fmp_sector,finviz_industry,finviz_sector,confidence,note\nX,Y,Z,W,,note\n');
    const t = buildTaxonomy(r);
    expect(t.industries['X'].confidence).toBe(0);
  });
});

describe('extractSnapshotNames', () => {
  const snapshotCsv =
    'date,collected_at,group_type,name,stocks\n' +
    '2026-06-09,2026-06-09T06:19:08Z,sector,Technology,100\n' +
    '2026-06-09,2026-06-09T06:19:08Z,sector,Energy,50\n';

  it('extracts unique name values from snapshot CSV', () => {
    const names = extractSnapshotNames(snapshotCsv);
    expect(names.has('Technology')).toBe(true);
    expect(names.has('Energy')).toBe(true);
    expect(names.size).toBe(2);
  });

  it('returns empty set for header-only CSV', () => {
    expect(extractSnapshotNames('date,name\n').size).toBe(0);
  });

  it('returns empty set when name column is absent', () => {
    expect(extractSnapshotNames('date,ticker\n2026-06-09,AAPL\n').size).toBe(0);
  });
});

describe('buildEtfOverrides', () => {
  const industries = new Set(['Semiconductors', 'Gold', 'Airlines']);
  const sectors = new Set(['Technology', 'Basic Materials', 'Industrials', 'Energy']);

  const etfCsv =
    'ticker,finviz_industry,finviz_sector,etf_name,kind,note\n' +
    'SMH,Semiconductors,Technology,VanEck Semiconductor ETF,thematic,semis\n' +
    'GDX,Gold,Basic Materials,VanEck Gold Miners ETF,thematic,gold\n' +
    'JETS,Airlines,Industrials,U.S. Global Jets ETF,thematic,airlines\n' +
    'XLE,,Energy,Energy SPDR,sector,energy sector\n' +
    'SPY,,,SPDR S&P 500,diversified,broad market\n';

  it('builds an overrides map keyed by uppercased ticker', () => {
    const { overrides, errors } = buildEtfOverrides(parseCsv(etfCsv), industries, sectors);
    expect(errors).toHaveLength(0);
    expect(overrides['SMH']).toEqual({ finviz_industry: 'Semiconductors', finviz_sector: 'Technology', kind: 'thematic' });
  });

  it('sector kind has blank finviz_industry', () => {
    const { overrides } = buildEtfOverrides(parseCsv(etfCsv), industries, sectors);
    expect(overrides['XLE'].finviz_industry).toBe('');
    expect(overrides['XLE'].finviz_sector).toBe('Energy');
    expect(overrides['XLE'].kind).toBe('sector');
  });

  it('diversified kind has both fields blank', () => {
    const { overrides } = buildEtfOverrides(parseCsv(etfCsv), industries, sectors);
    expect(overrides['SPY'].finviz_industry).toBe('');
    expect(overrides['SPY'].finviz_sector).toBe('');
    expect(overrides['SPY'].kind).toBe('diversified');
  });

  it('returns validation error for unknown finviz_industry', () => {
    const badCsv =
      'ticker,finviz_industry,finviz_sector,etf_name,kind,note\n' +
      'BOGUS,Copper Miners,Basic Materials,Test ETF,thematic,test\n';
    const { errors } = buildEtfOverrides(parseCsv(badCsv), industries, sectors);
    expect(errors.length).toBeGreaterThan(0);
    expect(errors[0]).toContain('"Copper Miners"');
  });

  it('returns validation error for unknown finviz_sector', () => {
    const badCsv =
      'ticker,finviz_industry,finviz_sector,etf_name,kind,note\n' +
      'BOGUS,,Bogus Sector,Test ETF,sector,test\n';
    const { errors } = buildEtfOverrides(parseCsv(badCsv), industries, sectors);
    expect(errors.length).toBeGreaterThan(0);
    expect(errors[0]).toContain('"Bogus Sector"');
  });

  it('skips rows with blank ticker', () => {
    const csvWithBlank =
      'ticker,finviz_industry,finviz_sector,etf_name,kind,note\n' +
      ',Semiconductors,Technology,Missing Ticker ETF,thematic,\n' +
      'SMH,Semiconductors,Technology,VanEck Semiconductor ETF,thematic,semis\n';
    const { overrides } = buildEtfOverrides(parseCsv(csvWithBlank), industries, sectors);
    expect(Object.keys(overrides)).toEqual(['SMH']);
  });
});
