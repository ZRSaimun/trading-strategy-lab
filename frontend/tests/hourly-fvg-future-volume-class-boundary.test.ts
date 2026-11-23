import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// A future-only timestamp getter must not rewrite the completed-prefix volume class.
test('future timestamp cannot replace tick-volume provenance with exchange volume', () => {
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
  let firstTimestampReads = 0;
  let secondTimestampReads = 0;
  let futurePayloadReads = 0;
  const forbidden = Object.fromEntries(
    ['open', 'high', 'low', 'close', 'volume', 'observed_minutes'].map(field => [
      field, {enumerable: true, get: () => {
        futurePayloadReads++;
        throw Error('unrevealed ' + field + ' accessed');
      }},
    ]),
  );
  const first = Object.defineProperties({}, {
    time: {enumerable: true, get: () => {
      firstTimestampReads++;
      Object.assign(source, {volumeType: 'exchange'});
      return 3 * H;
    }},
    ...forbidden,
  }) as Bar;
  const second = Object.defineProperties({}, {
    time: {enumerable: true, get: () => {
      secondTimestampReads++;
      return 4 * H;
    }},
    ...forbidden,
  }) as Bar;
  assert.throws(
    () => studyHourlyFvgMidpointAsOf([...completed, first, second], source, 2 * H),
    /FVG source declaration field changed during declaration snapshot/,
  );
  assert.equal(firstTimestampReads, 1);
  assert.equal(secondTimestampReads, 0);
  assert.equal(futurePayloadReads, 0);
});


test('future timestamp cannot downgrade exchange-volume provenance to tick volume', () => {
  const H = 3600;
  const source: FvgSource = {
    datasetId: 'a'.repeat(64), archiveSha256: 'b'.repeat(64),
    instrument: 'SYNTHETIC_GOLD', provider: 'fixture-provider',
    priceSide: 'bid', volumeType: 'exchange', volumeVerified: false,
  };
  const completed: Bar[] = [0, H].map(time => ({
    time, open: 100, high: 101, low: 99, close: 100,
    volume: 100, observed_minutes: 60,
  }));
  let firstTimestampReads = 0;
  let secondTimestampReads = 0;
  let futurePayloadReads = 0;
  const forbidden = Object.fromEntries(
    ['open', 'high', 'low', 'close', 'volume', 'observed_minutes'].map(field => [
      field, {enumerable: true, get: () => {
        futurePayloadReads++;
        throw Error('unrevealed ' + field + ' accessed');
      }},
    ]),
  );
  const first = Object.defineProperties({}, {
    time: {enumerable: true, get: () => {
      firstTimestampReads++;
      Object.assign(source, {volumeType: 'tick'});
      return 3 * H;
    }},
    ...forbidden,
  }) as Bar;
  const second = Object.defineProperties({}, {
    time: {enumerable: true, get: () => {
      secondTimestampReads++;
      return 4 * H;
    }},
    ...forbidden,
  }) as Bar;
  assert.throws(
    () => studyHourlyFvgMidpointAsOf([...completed, first, second], source, 2 * H),
    /FVG source declaration field changed during declaration snapshot/,
  );
  assert.equal(firstTimestampReads, 1);
  assert.equal(secondTimestampReads, 0);
  assert.equal(futurePayloadReads, 0);
});


test('stable exchange-volume class permits timestamp-only future scanning', () => {
  const H = 3600;
  const source: FvgSource = {
    datasetId: 'a'.repeat(64), archiveSha256: 'b'.repeat(64),
    instrument: 'SYNTHETIC_GOLD', provider: 'fixture-provider',
    priceSide: 'bid', volumeType: 'exchange', volumeVerified: false,
  };
  const completed: Bar[] = [0, H].map(time => ({
    time, open: 100, high: 101, low: 99, close: 100,
    volume: 100, observed_minutes: 60,
  }));
  const reads = [0, 0, 0];
  let payloadReads = 0;
  const future = [3, 4, 5].map((hour, i) => Object.defineProperties({}, {
    time: {enumerable: true, get: () => { reads[i]++; return hour * H; }},
    ...Object.fromEntries(['open', 'high', 'low', 'close', 'volume', 'observed_minutes']
      .map(field => [field, {enumerable: true, get: () => {
        payloadReads++;
        throw Error('unrevealed ' + field + ' accessed');
      }}])),
  }) as Bar);
  assert.doesNotThrow(() => studyHourlyFvgMidpointAsOf([...completed, ...future], source, 2 * H));
  assert.deepEqual(reads, [1, 1, 1]);
  assert.equal(payloadReads, 0);
});


test('second future timestamp cannot promote tick volume to exchange volume', () => {
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
  let payloadReads = 0;
  const future = [3, 4, 5].map((hour, i) => Object.defineProperties({}, {
    time: {enumerable: true, get: () => {
      reads[i]++;
      if (i === 1) source.volumeType = 'exchange';
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
  assert.deepEqual(reads, [1, 1, 0]);
  assert.equal(payloadReads, 0);
});


test('second future timestamp cannot downgrade exchange volume to tick volume', () => {
  const H = 3600;
  const source: FvgSource = {
    datasetId: 'a'.repeat(64), archiveSha256: 'b'.repeat(64),
    instrument: 'SYNTHETIC_GOLD', provider: 'fixture-provider',
    priceSide: 'bid', volumeType: 'exchange', volumeVerified: false,
  };
  const completed: Bar[] = [0, H].map(time => ({
    time, open: 100, high: 101, low: 99, close: 100,
    volume: 100, observed_minutes: 60,
  }));
  const reads = [0, 0, 0];
  let payloadReads = 0;
  const future = [3, 4, 5].map((hour, i) => Object.defineProperties({}, {
    time: {enumerable: true, get: () => {
      reads[i]++;
      if (i === 1) source.volumeType = 'tick';
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
  assert.deepEqual(reads, [1, 1, 0]);
  assert.equal(payloadReads, 0);
});
