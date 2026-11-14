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

test('large synthetic first-touch volume cannot override unverified source provenance',()=>{
 const bars:Bar[]=Array.from({length:20},(_,i)=>({
  time:i*H,open:99,high:100,low:98,close:99,volume:10,observed_minutes:60,
 }));
 bars.push(
  {time:20*H,open:99,high:100,low:98,close:99,volume:10,observed_minutes:60},
  {time:21*H,open:101,high:104,low:100,close:103,volume:10,observed_minutes:60},
  {time:22*H,open:103,high:105,low:102,close:104,volume:10,observed_minutes:60},
  {time:23*H,open:103,high:104,low:100.5,close:103.5,volume:1000000,observed_minutes:60},
 );
 const full=studyHourlyFvgMidpoint(bars,source);
 const asOf=studyHourlyFvgMidpointAsOf(bars,source,24*H);
 assert.deepEqual(asOf,full,'all 24 hourly candles are completed at the decision boundary');
 const touched=full.observations.find(x=>x.formationClosedAt===23*H);
 assert.ok(touched,'the synthetic three-hour gap must form');
 assert.equal(touched.firstTouchOutcome,'TOUCH');
 assert.equal(touched.volumeEvidenceReason,'SOURCE_UNVERIFIED');
 assert.equal(touched.gates.verifiedVolume,'INSUFFICIENT_DATA');
 assert.notEqual(touched.gates.strictCandidate,'PASS');
 assert.equal(touched.eligibleForLiveTrading,false);
});


test('unverified future volume cannot influence a completed-prefix first-touch decision',()=>{
 const completed:Bar[]=Array.from({length:20},(_,i)=>({
  time:i*H,open:99,high:100,low:98,close:99,volume:10,observed_minutes:60,
 }));
 completed.push(
  {time:20*H,open:99,high:100,low:98,close:99,volume:10,observed_minutes:60},
  {time:21*H,open:101,high:104,low:100,close:103,volume:10,observed_minutes:60},
  {time:22*H,open:103,high:105,low:102,close:104,volume:10,observed_minutes:60},
  {time:23*H,open:103,high:104,low:100.5,close:103.5,volume:1000000,observed_minutes:60},
 );
 let futureVolumeReads=0;
 const future={time:24*H,open:103,high:105,low:99,close:100,observed_minutes:60} as Bar;
 Object.defineProperty(future,'volume',{enumerable:true,get(){
  futureVolumeReads++;
  throw new Error('future unclosed hourly volume must not be read');
 }});
 const expected=studyHourlyFvgMidpoint(completed,source);
 const actual=studyHourlyFvgMidpointAsOf([...completed,future],source,24*H);
 assert.deepEqual(actual,expected);
 assert.equal(futureVolumeReads,0);
 const touched=actual.observations.find(x=>x.formationClosedAt===23*H);
 assert.ok(touched);
 assert.equal(touched.volumeEvidenceReason,'SOURCE_UNVERIFIED');
 assert.equal(touched.gates.verifiedVolume,'INSUFFICIENT_DATA');
 assert.equal(touched.eligibleForLiveTrading,false);
});

test('unverified first-touch volume cannot backfill a still-open first-touch hour',()=>{
 const completed:Bar[]=Array.from({length:20},(_,i)=>({
  time:i*H,open:99,high:100,low:98,close:99,volume:10,observed_minutes:60,
 }));
 completed.push(
  {time:20*H,open:99,high:100,low:98,close:99,volume:10,observed_minutes:60},
  {time:21*H,open:101,high:104,low:100,close:103,volume:10,observed_minutes:60},
  {time:22*H,open:103,high:105,low:102,close:104,volume:10,observed_minutes:60},
 );
 const pending={time:23*H,open:103,high:104,low:100.5,close:103.5,observed_minutes:60} as Bar;
 let futureReads=0;
 Object.defineProperty(pending,'volume',{enumerable:true,get(){
  futureReads++;
  throw new Error('still-open first-touch volume is not available');
 }});
 const asOf=studyHourlyFvgMidpointAsOf([...completed,pending],source,23*H);
 const prefix=studyHourlyFvgMidpoint(completed,source);
 assert.deepEqual(asOf,prefix,'the still-open first-touch candle cannot create a completed touch');
 assert.equal(futureReads,0);
 assert.equal(asOf.observations.filter(x=>x.firstTouchOutcome==='TOUCH').length,0);
});


test('bearish first-touch volume spike also remains unverified and paper-only',()=>{
 const bars:Bar[]=Array.from({length:20},(_,i)=>({
  time:i*H,open:101,high:102,low:100,close:101,volume:10,observed_minutes:60,
 }));
 bars.push(
  {time:20*H,open:101,high:102,low:100,close:101,volume:10,observed_minutes:60},
  {time:21*H,open:99,high:100,low:96,close:97,volume:10,observed_minutes:60},
  {time:22*H,open:97,high:98,low:95,close:96,volume:10,observed_minutes:60},
  {time:23*H,open:97,high:99.5,low:96,close:97,volume:1000000,observed_minutes:60},
 );
 const full=studyHourlyFvgMidpoint(bars,source);
 const asOf=studyHourlyFvgMidpointAsOf(bars,source,24*H);
 assert.deepEqual(asOf,full);
 const touched=full.observations.find(x=>x.formationClosedAt===23*H && x.direction==='BEARISH');
 assert.ok(touched,'the bearish synthetic gap must form');
 assert.equal(touched.firstTouchOutcome,'TOUCH');
 assert.equal(touched.volumeEvidenceReason,'SOURCE_UNVERIFIED');
 assert.equal(touched.gates.verifiedVolume,'INSUFFICIENT_DATA');
 assert.notEqual(touched.gates.strictCandidate,'PASS');
 assert.equal(touched.eligibleForLiveTrading,false);
});
