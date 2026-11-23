import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// The source archive digest must be fixed before looking beyond the completed prefix.
// A future timestamp getter is allowed to expose only its time, not rewrite provenance.
test('unrevealed timestamp cannot replace completed-prefix archive digest', () => {
  const H = 3600;
  const source: FvgSource = {
    datasetId: 'a'.repeat(64), archiveSha256: 'b'.repeat(64),
    instrument: 'SYNTHETIC_GOLD', provider: 'fixture-provider',
    priceSide: 'bid', volumeType: 'unverified', volumeVerified: false,
  };
  const completed: Bar[] = [0, H].map(time => ({
    time, open: 100, high: 101, low: 99, close: 100,
    volume: null, observed_minutes: 60,
  }));
  let futureTimeReads = 0;
  let secondTimeReads = 0;
  let futureMarketReads = 0;
  const forbidden = Object.fromEntries(
    ['open', 'high', 'low', 'close', 'volume', 'observed_minutes'].map(field => [
      field, {enumerable: true, get: () => {
        futureMarketReads++;
        throw Error('unrevealed ' + field + ' accessed');
      }},
    ]),
  );
  const future = Object.defineProperties({}, {
    time: {enumerable: true, get: () => {
      futureTimeReads++;
      source.archiveSha256 = 'c'.repeat(64);
      return 3 * H;
    }},
    ...forbidden,
  }) as Bar;
  const secondFuture = Object.defineProperties({}, {
    time: {enumerable: true, get: () => {
      secondTimeReads++;
      throw Error('second future timestamp accessed');
    }},
    ...forbidden,
  }) as Bar;
  assert.throws(
    () => studyHourlyFvgMidpointAsOf([...completed, future, secondFuture], source, 2 * H),
    /FVG source declaration field changed during declaration snapshot/,
  );
  assert.equal(futureTimeReads, 1);
  assert.equal(secondTimeReads, 0);
  assert.equal(futureMarketReads, 0);
});
