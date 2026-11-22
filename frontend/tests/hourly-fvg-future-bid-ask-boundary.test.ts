import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

test('future timestamp must not switch BID to ASK or reveal future payload', () => {
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
  let payloadReads = 0;
  const future = [3 * H, 4 * H].map((time, index) =>
    Object.defineProperties({}, {
      time: {enumerable: true, get: () => {
        reads[index]++;
        if (index === 0) Object.assign(source, {priceSide: 'ask'});
        return time;
      }},
      ...Object.fromEntries(['open', 'high', 'low', 'close', 'volume', 'observed_minutes'].map(field => [
        field, {enumerable: true, get: () => {
          payloadReads++;
          throw Error('unrevealed ' + field + ' accessed');
        }},
      ])),
    }) as Bar,
  );
  assert.throws(
    () => studyHourlyFvgMidpointAsOf([...completed, ...future], source, 2 * H),
    /FVG source declaration field changed during declaration snapshot/,
  );
  assert.deepEqual(reads, [1, 0]);
  assert.equal(payloadReads, 0);
});

test('second future timestamp cannot switch BID to ASK or reveal future payload', () => {
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
  let payloadReads = 0;
  const future = [3 * H, 4 * H, 5 * H].map((time, index) =>
    Object.defineProperties({}, {
      time: {enumerable: true, get: () => {
        reads[index]++;
        if (index === 1) Object.assign(source, {priceSide: 'ask'});
        return time;
      }},
      ...Object.fromEntries(['open', 'high', 'low', 'close', 'volume', 'observed_minutes'].map(field => [
        field, {enumerable: true, get: () => {
          payloadReads++;
          throw Error('unrevealed ' + field + ' accessed');
        }},
      ])),
    }) as Bar,
  );
  assert.throws(
    () => studyHourlyFvgMidpointAsOf([...completed, ...future], source, 2 * H),
    /FVG source declaration field changed during declaration snapshot/,
  );
  assert.deepEqual(reads, [1, 1, 0]);
  assert.equal(payloadReads, 0);
});

test('stable BID identity accepts future timestamps without future payload', () => {
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
  let reads = 0;
  let payloadReads = 0;
  const future = [3 * H, 4 * H].map(time => Object.defineProperties({}, {
    time: {enumerable: true, get: () => {reads++; return time;}},
    ...Object.fromEntries(['open', 'high', 'low', 'close', 'volume', 'observed_minutes'].map(field => [
      field, {enumerable: true, get: () => {payloadReads++; throw Error('unrevealed ' + field);}},
    ])),
  }) as Bar);
  assert.doesNotThrow(() => studyHourlyFvgMidpointAsOf([...completed, ...future], source, 2 * H));
  assert.equal(reads, 2);
  assert.equal(payloadReads, 0);
  assert.equal(source.priceSide, 'bid');
});
