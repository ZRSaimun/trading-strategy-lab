import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// A future timestamp must not rewrite the dataset identity of the revealed prefix.
test('unrevealed timestamp cannot replace completed-prefix dataset identity', () => {
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
  let firstReads = 0, secondReads = 0, futureFields = 0;
  const forbidden = Object.fromEntries(
    ['open', 'high', 'low', 'close', 'volume', 'observed_minutes'].map(field => [
      field, {enumerable: true, get: () => {
        futureFields++;
        throw Error('unrevealed ' + field + ' accessed');
      }},
    ]),
  );
  const future = Object.defineProperties({}, {
    time: {enumerable: true, get: () => {
      firstReads++;
      source.datasetId = 'c'.repeat(64);
      return 3 * H;
    }},
    ...forbidden,
  }) as Bar;
  const second = Object.defineProperties({}, {
    time: {enumerable: true, get: () => {
      secondReads++;
      throw Error('second future timestamp accessed');
    }},
    ...forbidden,
  }) as Bar;
  assert.throws(
    () => studyHourlyFvgMidpointAsOf([...completed, future, second], source, 2 * H),
    /FVG source declaration field changed during declaration snapshot/,
  );
  assert.equal(firstReads, 1);
  assert.equal(secondReads, 0);
  assert.equal(futureFields, 0);
});


test('unrevealed timestamps leave a stable completed-prefix dataset identity valid', () => {
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
  let futureMarketReads = 0;
  const future = Object.defineProperties({}, {
    time: {enumerable: true, get: () => {
      futureTimeReads++;
      return 3 * H;
    }},
    ...Object.fromEntries(
      ['open', 'high', 'low', 'close', 'volume', 'observed_minutes'].map(field => [
        field, {enumerable: true, get: () => {
          futureMarketReads++;
          throw Error('unrevealed ' + field + ' accessed');
        }},
      ]),
    ),
  }) as Bar;
  const result = studyHourlyFvgMidpointAsOf([...completed, future], source, 2 * H);
  assert.equal(result.source.datasetId, 'a'.repeat(64));
  assert.equal(result.coverage.observedBars, 2);
  assert.equal(futureTimeReads, 1);
  assert.equal(futureMarketReads, 0);
});

// Multiple unrevealed timestamps may be inspected for chronology, but their
// market payloads must remain inaccessible and must not alter source identity.
test('two stable future timestamps preserve source and hide both market payloads', () => {
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
  const reads = [0, 0];
  let marketReads = 0;
  const future = [3 * H, 4 * H].map((time, index) => Object.defineProperties({}, {
    time: {enumerable: true, get: () => { reads[index]++; return time; }},
    ...Object.fromEntries(['open', 'high', 'low', 'close', 'volume', 'observed_minutes'].map(field => [
      field, {enumerable: true, get: () => {
        marketReads++;
        throw Error('unrevealed ' + field + ' accessed');
      }},
    ])),
  }) as Bar);
  const result = studyHourlyFvgMidpointAsOf([...completed, ...future], source, 2 * H);
  assert.equal(result.source.datasetId, 'a'.repeat(64));
  assert.equal(result.coverage.observedBars, 2);
  assert.deepEqual(reads, [1, 1]);
  assert.equal(marketReads, 0);
});


test('second unrevealed timestamp cannot mutate dataset identity after a stable first future row', () => {
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
  const reads = [0, 0, 0];
  let marketReads = 0;
  const future = [3 * H, 4 * H, 5 * H].map((time, index) => Object.defineProperties({}, {
    time: {enumerable: true, get: () => {
      reads[index]++;
      if (index === 1) source.datasetId = 'c'.repeat(64);
      return time;
    }},
    ...Object.fromEntries(['open', 'high', 'low', 'close', 'volume', 'observed_minutes'].map(field => [
      field, {enumerable: true, get: () => {
        marketReads++;
        throw Error('unrevealed ' + field + ' accessed');
      }},
    ])),
  }) as Bar);
  assert.throws(
    () => studyHourlyFvgMidpointAsOf([...completed, ...future], source, 2 * H),
    /FVG source declaration field changed during declaration snapshot/,
  );
  assert.deepEqual(reads, [1, 1, 0]);
  assert.equal(marketReads, 0);
});
