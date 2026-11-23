import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// A source receipt must not change while scanning timestamps beyond the as-of boundary.
test('future timestamp cannot swap the completed-prefix archive hash', () => {
  const H = 3600;
  const source: FvgSource = {
    datasetId: 'a'.repeat(64), archiveSha256: 'b'.repeat(64),
    instrument: 'SYNTHETIC_GOLD', provider: 'fixture-provider',
    priceSide: 'bid', volumeType: 'unverified', volumeVerified: false,
  };
  const originalHash = source.archiveSha256;
  const completed: Bar[] = [0, H].map(time => ({
    time, open: 100, high: 101, low: 99, close: 100,
    volume: null, observed_minutes: 60,
  }));
  const timestampReads = [0, 0];
  let futurePayloadReads = 0;
  const future = [3 * H, 4 * H].map((time, index) =>
    Object.defineProperties({}, {
      time: {enumerable: true, get: () => {
        timestampReads[index]++;
        if (index === 0) source.archiveSha256 = 'c'.repeat(64);
        return time;
      }},
      ...Object.fromEntries(['open', 'high', 'low', 'close', 'volume', 'observed_minutes'].map(field => [
        field, {enumerable: true, get: () => {
          futurePayloadReads++;
          throw Error('unrevealed ' + field + ' accessed');
        }},
      ])),
    }) as Bar,
  );
  assert.throws(
    () => studyHourlyFvgMidpointAsOf([...completed, ...future], source, 2 * H),
    /FVG source declaration field changed during declaration snapshot/,
  );
  assert.equal(originalHash, 'b'.repeat(64));
  assert.deepEqual(timestampReads, [1, 0]);
  assert.equal(futurePayloadReads, 0);
});

test('second unrevealed timestamp cannot swap the completed-prefix archive hash', () => {
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
  const timestampReads = [0, 0, 0];
  let futurePayloadReads = 0;
  const future = [3 * H, 4 * H, 5 * H].map((time, index) =>
    Object.defineProperties({}, {
      time: {enumerable: true, get: () => {
        timestampReads[index]++;
        if (index === 1) source.archiveSha256 = 'c'.repeat(64);
        return time;
      }},
      ...Object.fromEntries(['open', 'high', 'low', 'close', 'volume', 'observed_minutes'].map(field => [
        field, {enumerable: true, get: () => {
          futurePayloadReads++;
          throw Error('unrevealed ' + field + ' accessed');
        }},
      ])),
    }) as Bar,
  );
  assert.throws(
    () => studyHourlyFvgMidpointAsOf([...completed, ...future], source, 2 * H),
    /FVG source declaration field changed during declaration snapshot/,
  );
  assert.deepEqual(timestampReads, [1, 1, 0]);
  assert.equal(futurePayloadReads, 0);
});

test('third unrevealed timestamp cannot swap the completed-prefix archive hash', () => {
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
  const timestampReads = [0, 0, 0, 0];
  let futurePayloadReads = 0;
  const future = [3 * H, 4 * H, 5 * H, 6 * H].map((time, index) =>
    Object.defineProperties({}, {
      time: {enumerable: true, get: () => {
        timestampReads[index]++;
        if (index === 2) source.archiveSha256 = 'c'.repeat(64);
        return time;
      }},
      ...Object.fromEntries(['open', 'high', 'low', 'close', 'volume', 'observed_minutes'].map(field => [
        field, {enumerable: true, get: () => {
          futurePayloadReads++;
          throw Error('unrevealed ' + field + ' accessed');
        }},
      ])),
    }) as Bar,
  );
  assert.throws(
    () => studyHourlyFvgMidpointAsOf([...completed, ...future], source, 2 * H),
    /FVG source declaration field changed during declaration snapshot/,
  );
  assert.deepEqual(timestampReads, [1, 1, 1, 0]);
  assert.equal(futurePayloadReads, 0);
});


test('stable archive hash permits future timestamp scan without revealing future payload', () => {
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
  const timestampReads = [0, 0, 0, 0];
  let futurePayloadReads = 0;
  const future = [3 * H, 4 * H, 5 * H, 6 * H].map((time, index) =>
    Object.defineProperties({}, {
      time: {enumerable: true, get: () => {
        timestampReads[index]++;
        return time;
      }},
      ...Object.fromEntries(['open', 'high', 'low', 'close', 'volume', 'observed_minutes'].map(field => [
        field, {enumerable: true, get: () => {
          futurePayloadReads++;
          throw Error('unrevealed ' + field + ' accessed');
        }},
      ])),
    }) as Bar,
  );
  assert.doesNotThrow(() =>
    studyHourlyFvgMidpointAsOf([...completed, ...future], source, 2 * H));
  assert.deepEqual(timestampReads, [1, 1, 1, 1]);
  assert.equal(futurePayloadReads, 0);
  assert.equal(source.archiveSha256, 'b'.repeat(64));
});
