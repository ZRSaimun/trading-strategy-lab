import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic BID-only research: an absent hour is unknown, not a no-touch bar.
const H=3600;
const source={
 datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
 volumeType:'unverified' as const,volumeVerified:false,
};
test('missing first eligible hour censors bearish midpoint touch despite later observed wick',()=>{
 const bars:Bar[]=Array.from({length:21},(_,i)=>({
  time:i*H,open:101,high:102,low:100,close:101,volume:10,observed_minutes:60,
 }));
 bars.push(
  {time:21*H,open:99,high:100,low:96,close:97,volume:10,observed_minutes:60},
  {time:22*H,open:97,high:98,low:95,close:96,volume:10,observed_minutes:60},
 );
 const before=studyHourlyFvgMidpointAsOf(bars,source,23*H);
 const formation=before.observations.find(x=>x.direction==='BEARISH'&&x.formationClosedAt===23*H);
 assert.ok(formation);
 assert.equal(formation.firstTouchOutcome,'INCOMPLETE_WINDOW');
 assert.equal(formation.firstTouchCensorReason,'RIGHT_CENSORED');
 // Hour 23 is missing. The later hour 24 crosses the bearish midpoint,
 // but its observed wick cannot establish the FIRST eligible touch.
 const later:Bar={time:24*H,open:97,high:99.5,low:96,close:97,volume:999,observed_minutes:60};
 const after=studyHourlyFvgMidpointAsOf([...bars,later],source,25*H);
 const observation=after.observations.find(x=>x.direction==='BEARISH'&&x.formationClosedAt===23*H);
 assert.ok(observation);
 assert.equal(observation.firstTouchOutcome,'INCOMPLETE_WINDOW');
 assert.equal(observation.firstTouchCensorReason,'MISSING_HOUR');
 assert.equal(observation.firstTouchCensorMissingHourSlots,1);
 assert.equal(observation.firstTouchCensorObservedAt,25*H);
 assert.equal(observation.firstTouchClosedAt,null);
 assert.equal(observation.gates.midpointTouch,'INSUFFICIENT_DATA');
 assert.equal(observation.gates.verifiedVolume,'INSUFFICIENT_DATA');
 assert.equal(observation.eligibleForLiveTrading,false);
});

test('two missing bearish first-touch hours cannot be certified by a later closed wick',()=>{
 const bars:Bar[]=Array.from({length:21},(_,i)=>({
  time:i*H,open:101,high:102,low:100,close:101,volume:10,observed_minutes:60,
 }));
 bars.push(
  {time:21*H,open:99,high:100,low:96,close:97,volume:10,observed_minutes:60},
  {time:22*H,open:97,high:98,low:95,close:96,volume:10,observed_minutes:60},
  {time:25*H,open:97,high:99.5,low:96,close:97,volume:999,observed_minutes:60},
 );
 const result=studyHourlyFvgMidpointAsOf(bars,source,26*H);
 const observation=result.observations.find(x=>x.direction==='BEARISH'&&x.formationClosedAt===23*H);
 assert.ok(observation);
 assert.equal(observation.firstTouchOutcome,'INCOMPLETE_WINDOW');
 assert.equal(observation.firstTouchCensorReason,'MISSING_HOUR');
 assert.equal(observation.firstTouchCensorMissingHourSlots,2);
 assert.equal(observation.firstTouchCensorObservedAt,26*H);
 assert.equal(observation.firstTouchClosedAt,null);
 assert.equal(observation.gates.midpointTouch,'INSUFFICIENT_DATA');
 assert.equal(observation.eligibleForLiveTrading,false);
});
