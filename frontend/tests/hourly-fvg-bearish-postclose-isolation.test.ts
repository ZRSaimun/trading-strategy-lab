import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpoint,studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic BID candles only; this does not estimate fills or returns.
const H=3600;
const source={
 datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
 volumeType:'unverified' as const,volumeVerified:false,
};
test('bearish first-touch disposition is immutable after its completed close',()=>{
 const bars:Bar[]=Array.from({length:21},(_,i)=>({
  time:i*H,open:101,high:102,low:100,close:101,volume:10,observed_minutes:60,
 }));
 bars.push(
  {time:21*H,open:99,high:100,low:96,close:97,volume:10,observed_minutes:60},
  {time:22*H,open:97,high:98,low:95,close:96,volume:10,observed_minutes:60},
  {time:23*H,open:97,high:99.5,low:96,close:97,volume:999,observed_minutes:60},
 );
 const first=studyHourlyFvgMidpointAsOf(bars,source,24*H);
 const observed=first.observations.find(x=>x.direction==='BEARISH'&&x.formationClosedAt===23*H);
 assert.ok(observed);
 assert.equal(observed.firstTouchOutcome,'TOUCH');
 assert.equal(observed.firstTouchClosedAt,24*H);
 assert.equal(observed.volumeEvidenceReason,'SOURCE_UNVERIFIED');
 // Later bars cannot retroactively turn an unknown verified-volume gate into PASS.
 const future={time:24*H} as Bar;
 let futureReads=0;
 for(const field of ['open','high','low','close','volume','observed_minutes'] as const)
  Object.defineProperty(future,field,{enumerable:true,get(){
   futureReads++;throw Error('unclosed future candle field read');
  }});
 const replay=studyHourlyFvgMidpointAsOf([...bars,future],source,24*H);
 assert.deepEqual(replay,first);
 assert.equal(futureReads,0);
 assert.equal(observed.gates.verifiedVolume,'INSUFFICIENT_DATA');
 assert.equal(observed.eligibleForLiveTrading,false);
 assert.deepEqual(first,studyHourlyFvgMidpoint(bars,source));
});
