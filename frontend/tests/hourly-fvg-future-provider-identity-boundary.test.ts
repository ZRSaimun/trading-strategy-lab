import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic-only: provider identity is a source declaration, not a verified receipt.
test('future timestamp cannot silently substitute the declared BID provider', () => {
  const H = 3600;
  const source: FvgSource = {
    datasetId: 'a'.repeat(64), archiveSha256: 'b'.repeat(64),
    instrument: 'SYNTHETIC_GOLD', provider: 'fixture-provider-A',
    priceSide: 'bid', volumeType: 'tick', volumeVerified: false,
  };
  const completed: Bar[] = [0, H].map(time => ({
    time, open: 100, high: 101, low: 99, close: 100,
    volume: 100, observed_minutes: 60,
  }));
  const reads = [0, 0];
  let payloadReads = 0;
  const future = [3, 4].map((hour, index) => Object.defineProperties({}, {
    time: {enumerable: true, get: () => {
      reads[index]++;
      if (index === 0) source.provider = 'fixture-provider-B';
      return hour * H;
    }},
    ...Object.fromEntries(['open', 'high', 'low', 'close', 'volume', 'observed_minutes']
      .map(field => [field, {enumerable: true, get: () => {
        payloadReads++;
        throw Error('unrevealed ' + field + ' accessed');
      }}])),
  }) as Bar);
  assert.throws(
    () => studyHourlyFvgMidpointAsOf([...completed, ...future], source, 2 * H),
    /FVG source declaration field changed during declaration snapshot/,
  );
  assert.deepEqual(reads, [1, 0]);
  assert.equal(payloadReads, 0);
  assert.equal(source.provider, 'fixture-provider-B');
});
