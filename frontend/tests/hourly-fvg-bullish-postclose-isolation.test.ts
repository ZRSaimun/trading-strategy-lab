import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpoint,studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic BID fixture: verifies causal isolation, not broker fills or returns.
const H=3600;
const source={
 datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
 volumeType:'unverified' as const,volumeVerified:false,
};
test('bullish completed first touch cannot be rewritten by a later unclosed candle',()=>{
 const bars:Bar[]=Array.from({length:21},(_,i)=>({
  time:i*H,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
 }));
 bars.push(
  {time:21*H,open:102,high:105,low:101,close:104,volume:10,observed_minutes:60},
  {time:22*H,open:104,high:106,low:103,close:105,volume:10,observed_minutes:60},
  {time:23*H,open:104,high:105,low:100.5,close:104,volume:999,observed_minutes:60},
 );
 const baseline=studyHourlyFvgMidpointAsOf(bars,source,24*H);
 const observed=baseline.observations.find(x=>x.direction==='BULLISH'&&x.formationClosedAt===23*H);
 assert.ok(observed);
 assert.equal(observed.firstTouchOutcome,'TOUCH');
 assert.equal(observed.firstTouchClosedAt,24*H);
 assert.equal(observed.volumeEvidenceReason,'SOURCE_UNVERIFIED');
 assert.equal(observed.gates.verifiedVolume,'INSUFFICIENT_DATA');
 assert.equal(observed.eligibleForLiveTrading,false);
 const future={time:24*H} as Bar;
 let reads=0;
 for(const field of ['open','high','low','close','volume','observed_minutes'] as const)
  Object.defineProperty(future,field,{enumerable:true,get(){
   reads++;throw Error('future unclosed candle must not be inspected');
  }});
 assert.deepEqual(studyHourlyFvgMidpointAsOf([...bars,future],source,24*H),baseline);
 assert.deepEqual(studyHourlyFvgMidpoint(bars,source),baseline);
 assert.equal(reads,0);
});
