import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

test('future timestamp cannot retroactively promote unverified volume to verified evidence', () => {
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
  const timestampReads = [0, 0];
  let futurePayloadReads = 0;
  const future = [3 * H, 4 * H].map((time, index) =>
    Object.defineProperties({}, {
      time: {enumerable: true, get: () => {
        timestampReads[index]++;
        if (index === 0) source.volumeVerified = true;
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
  assert.deepEqual(timestampReads, [1, 0]);
  assert.equal(futurePayloadReads, 0);
});


test('future timestamp cannot silently revoke verified completed-prefix volume', () => {
  const H = 3600;
  const source: FvgSource = {
    datasetId: 'a'.repeat(64), archiveSha256: 'b'.repeat(64),
    instrument: 'SYNTHETIC_GOLD', provider: 'fixture-provider',
    priceSide: 'bid', volumeType: 'tick', volumeVerified: true,
  };
  const completed: Bar[] = [0, H].map(time => ({
    time, open: 100, high: 101, low: 99, close: 100,
    volume: 100, observed_minutes: 60,
  }));
  const timestampReads = [0, 0];
  let futurePayloadReads = 0;
  const future = [3 * H, 4 * H].map((time, index) =>
    Object.defineProperties({}, {
      time: {enumerable: true, get: () => {
        timestampReads[index]++;
        if (index === 0) source.volumeVerified = false;
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
  assert.deepEqual(timestampReads, [1, 0]);
  assert.equal(futurePayloadReads, 0);
});
