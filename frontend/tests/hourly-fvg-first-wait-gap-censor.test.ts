import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic BID prices only: missing hours are not evidence of no touch.
const H=3600;
const source={
 datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
 volumeType:'unverified' as const,volumeVerified:false,
};
test('missing first eligible hour censors bullish midpoint touch rather than skipping ahead',()=>{
 const bars:Bar[]=Array.from({length:21},(_,i)=>({
  time:i*H,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
 }));
 bars.push(
  {time:21*H,open:102,high:105,low:101,close:104,volume:10,observed_minutes:60},
  {time:22*H,open:104,high:106,low:103,close:105,volume:10,observed_minutes:60},
 );
 const formed=studyHourlyFvgMidpointAsOf(bars,source,23*H);
 const initial=formed.observations.find(x=>x.direction==='BULLISH'&&x.formationClosedAt===23*H);
 assert.ok(initial);
 assert.equal(initial.firstTouchOutcome,'INCOMPLETE_WINDOW');
 assert.equal(initial.firstTouchCensorReason,'RIGHT_CENSORED');
 // Hour 23 is missing. Hour 24 would intersect the midpoint, but cannot
 // retroactively become the first eligible touch after an unobserved hour.
 const later:Bar={time:24*H,open:104,high:105,low:100.5,close:104,volume:999,observed_minutes:60};
 const after=studyHourlyFvgMidpointAsOf([...bars,later],source,25*H);
 const observation=after.observations.find(x=>x.direction==='BULLISH'&&x.formationClosedAt===23*H);
 assert.ok(observation);
 assert.equal(observation.firstTouchOutcome,'INCOMPLETE_WINDOW');
 assert.equal(observation.firstTouchCensorReason,'MISSING_HOUR');
 assert.equal(observation.firstTouchCensorMissingHourSlots,1);
 assert.equal(observation.firstTouchCensorObservedAt,25*H);
 assert.equal(observation.firstTouchClosedAt,null);
 assert.equal(observation.gates.midpointTouch,'INSUFFICIENT_DATA');
 assert.equal(observation.eligibleForLiveTrading,false);
});
