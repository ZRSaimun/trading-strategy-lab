import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

test('future timestamp cannot substitute the dataset identity before another future timestamp', () => {
  const H = 3600;
  const source: FvgSource = {
    datasetId: 'a'.repeat(64), archiveSha256: 'b'.repeat(64),
    instrument: 'SYNTHETIC_GOLD', provider: 'fixture-provider',
    priceSide: 'bid', volumeType: 'tick', volumeVerified: false,
  };
  const completed: Bar[] = [0, H].map(time => ({
    time, open: 100, high: 101, low: 99, close: 100,
    volume: 100, observed_minutes: 60,
  }));
  const reads = [0, 0];
  let futurePayloadReads = 0;
  const future = [3, 4].map((hour, index) => Object.defineProperties({}, {
    time: {enumerable: true, get: () => {
      reads[index]++;
      if (index === 0) source.datasetId = 'c'.repeat(64);
      return hour * H;
    }},
    ...Object.fromEntries(['open', 'high', 'low', 'close', 'volume', 'observed_minutes']
      .map(field => [field, {enumerable: true, get: () => {
        futurePayloadReads++;
        throw Error('unrevealed ' + field + ' accessed');
      }}])),
  }) as Bar);
  assert.throws(
    () => studyHourlyFvgMidpointAsOf([...completed, ...future], source, 2 * H),
    /FVG source declaration field changed during declaration snapshot/,
  );
  assert.deepEqual(reads, [1, 0]);
  assert.equal(futurePayloadReads, 0);
});

test('stable dataset identity permits timestamp-only scanning of unrevealed hours', () => {
  const H = 3600;
  const source: FvgSource = {
    datasetId: 'a'.repeat(64), archiveSha256: 'b'.repeat(64),
    instrument: 'SYNTHETIC_GOLD', provider: 'fixture-provider',
    priceSide: 'bid', volumeType: 'tick', volumeVerified: false,
  };
  const completed: Bar[] = [0, H].map(time => ({
    time, open: 100, high: 101, low: 99, close: 100,
    volume: 100, observed_minutes: 60,
  }));
  const reads = [0, 0, 0];
  let futurePayloadReads = 0;
  const future = [3, 4, 5].map((hour, index) => Object.defineProperties({}, {
    time: {enumerable: true, get: () => {
      reads[index]++;
      return hour * H;
    }},
    ...Object.fromEntries(['open', 'high', 'low', 'close', 'volume', 'observed_minutes']
      .map(field => [field, {enumerable: true, get: () => {
        futurePayloadReads++;
        throw Error('unrevealed ' + field + ' accessed');
      }}])),
  }) as Bar);
  assert.doesNotThrow(() => studyHourlyFvgMidpointAsOf([...completed, ...future], source, 2 * H));
  assert.deepEqual(reads, [1, 1, 1]);
  assert.equal(futurePayloadReads, 0);
  assert.equal(source.datasetId, 'a'.repeat(64));
});
