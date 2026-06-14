import { describe, it, expect } from 'vitest';
import { parseCsv, buildTaxonomy } from '../scripts/build_taxonomy.js';

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
