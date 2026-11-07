import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpoint,studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

const H=3600;
const source={
 datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
 volumeType:'unverified' as const,volumeVerified:false,
};

test('bearish first midpoint touch is withheld at exact open and admitted only at close',()=>{
 const prefix:Bar[]=Array.from({length:21},(_,i)=>({
  time:i*H,open:101,high:102,low:100,close:101,volume:10,observed_minutes:60,
 }));
 prefix.push(
  {time:21*H,open:99,high:100,low:96,close:97,volume:10,observed_minutes:60},
  {time:22*H,open:97,high:98,low:95,close:96,volume:10,observed_minutes:60},
 );
 const firstTouch:Bar={time:23*H,open:97,high:99.5,low:96,close:97,volume:999,observed_minutes:60};
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([...prefix,firstTouch],source,24*H-1),
  /Invalid UTC hourly as-of close/,
  'an intrahour timestamp must be rejected rather than rounded to a completed close',
 );
 const atOpen=studyHourlyFvgMidpointAsOf([...prefix,firstTouch],source,23*H);
 const expectedPrefix=studyHourlyFvgMidpoint(prefix,source);
 assert.deepEqual(atOpen,expectedPrefix);
 const atClose=studyHourlyFvgMidpointAsOf([...prefix,firstTouch],source,24*H);
 const full=studyHourlyFvgMidpoint([...prefix,firstTouch],source);
 assert.deepEqual(atClose,full);
 const earlier=atOpen.observations.find(x=>x.direction==='BEARISH' && x.formationClosedAt===23*H);
 const matured=atClose.observations.find(x=>x.direction==='BEARISH' && x.formationClosedAt===23*H);
 assert.ok(earlier);
 assert.ok(matured);
 assert.equal(earlier.firstTouchOutcome,'INCOMPLETE_WINDOW');
 assert.equal(earlier.firstTouchClosedAt,null);
 assert.equal(matured.firstTouchClosedAt,24*H);
 assert.equal(matured.gates.verifiedVolume,'INSUFFICIENT_DATA');
 assert.equal(matured.eligibleForLiveTrading,false);
});
