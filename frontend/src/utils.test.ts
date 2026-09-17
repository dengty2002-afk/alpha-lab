import { describe, expect, it } from 'vitest';
import {
  comparisonSignature,
  csv,
  format,
  parseCalendar,
  parseInstruments,
  parseNumberList,
  provenanceSignature,
  validateSplits,
} from './utils';
describe('research input boundaries', () => {
  it('requires explicit valid trading dates and accepts JSON or newline calendars', () => {
    expect(parseCalendar('["2025-01-03","2025-01-02"]')).toEqual(['2025-01-02', '2025-01-03']);
    expect(parseCalendar('2025-01-02\n2025-01-03')).toEqual(['2025-01-02', '2025-01-03']);
    expect(() => parseCalendar('')).toThrow();
    expect(() => parseCalendar('2025-02-31')).toThrow();
  });
  it('compares economic factor definitions independent of entity metadata and flags universe rules', () => {
    const base = { snapshotId: 'one', factors: [{ name: 'a', expression: '$close', direction: 1 }] };
    expect(comparisonSignature(base)).toBe(
      comparisonSignature({
        ...base,
        factors: [
          {
            id: 'new-id',
            version: 2,
            direction: 1,
            expression: '$close',
            name: 'a',
            description: 'new description',
          },
        ],
      }),
    );
    expect(comparisonSignature(base)).not.toBe(comparisonSignature({ ...base, minUniverse: 30 }));
    expect(comparisonSignature(base)).toBe(comparisonSignature({ ...base, annualization: 252 }));
    expect(comparisonSignature(base)).not.toBe(comparisonSignature({ ...base, annualization: 250 }));
  });
  it('distinguishes actual data, research code and plugin versions in report comparison', () => {
    const base = { dataHash: 'data', sourceCodeHash: 'source', plugins: { hash: 'plugins' } };
    expect(provenanceSignature(base)).toBe(provenanceSignature({ ...base, configHash: 'different-model' }));
    expect(provenanceSignature(base)).not.toBe(provenanceSignature({ ...base, dataHash: 'other-data' }));
    expect(provenanceSignature(base)).not.toBe(
      provenanceSignature({ ...base, sourceCodeHash: 'other-code' }),
    );
    expect(provenanceSignature(base)).not.toBe(
      provenanceSignature({ ...base, plugins: { hash: 'other-plugins' } }),
    );
  });
  it('keeps ratios and correlations numeric while formatting returns and fractions as percentages', () => {
    expect(format(1.2, 'ratio')).toBe('1.2');
    expect(format(0.1, 'correlation')).toBe('0.1');
    expect(format(0.1, 'return')).toBe('10.00%');
    expect(format(0.2, 'fraction')).toBe('20.00%');
    expect(format(0.1, 'percent')).toBe('10.00%');
  });
  it('deduplicates instrument input across Chinese punctuation and newlines', () =>
    expect(parseInstruments('sh.600000，sz.000001\nsh.600000')).toEqual(['sh.600000', 'sz.000001']));
  it('rejects nonnumeric costs and preserves zero cost', () => {
    expect(parseNumberList('0, 5,10')).toEqual([0, 5, 10]);
    expect(() => parseNumberList('10,x')).toThrow();
  });
  it('rejects overlapping temporal partitions', () =>
    expect(
      validateSplits({
        trainStart: '2021-01-01',
        trainEnd: '2024-01-01',
        validStart: '2024-01-01',
        validEnd: '2024-12-31',
        testStart: '2025-01-01',
        testEnd: '2025-12-31',
      }),
    ).toContain('不能重叠'));
  it('leaves invalid statistics empty rather than showing zero', () => {
    expect(format(null)).toBe('—');
    expect(format(NaN)).toBe('—');
    expect(format(0, '%')).toBe('0.00%');
  });
  it('escapes CSV values and spreadsheet formulas', () =>
    expect(csv([{ name: '=1+1', note: 'a"b' }])).toContain('"\'=1+1","a""b"'));
});
