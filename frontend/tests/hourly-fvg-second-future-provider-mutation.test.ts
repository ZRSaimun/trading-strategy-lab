import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// The second future timestamp must not retroactively relabel the provider.
test('second future timestamp provider mutation fails before third timestamp and market fields', () => {
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
        if (index === 1) source.provider = 'unverified-future-provider';
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


test('stable provider across multiple unrevealed timestamps is accepted without future payload reads', () => {
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
  const result = studyHourlyFvgMidpointAsOf([...completed, ...future], source, 2 * H);
  assert.deepEqual(reads, [1, 1, 1]);
  assert.equal(payloadReads, 0);
  assert.equal(result.source.provider, 'fixture-provider');
  assert.equal(result.coverage.observedBars, 2);
});

test('first future timestamp provider mutation is rejected before later timestamps or payloads', () => {
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
        if (index === 0) source.provider = 'late-provider';
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

test('last future timestamp provider mutation is rejected without future market reads', () => {
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
        if (index === 2) source.provider = 'late-last-provider';
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
  assert.deepEqual(reads, [1, 1, 1]);
  assert.equal(payloadReads, 0);
});

test('future timestamp cannot erase provider identity before market payload inspection', () => {
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
        if (index === 0) source.provider = '';
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

test('future timestamp cannot null out provider identity through runtime type bypass', () => {
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
  let futureTimestampReads = 0;
  let futurePayloadReads = 0;
  const future = [3 * H, 4 * H].map((time, index) =>
    Object.defineProperties({}, {
      time: {enumerable: true, get: () => {
        futureTimestampReads++;
        if (index === 0) (source as unknown as {provider: unknown}).provider = null;
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
  assert.equal(futureTimestampReads, 1);
  assert.equal(futurePayloadReads, 0);
});
