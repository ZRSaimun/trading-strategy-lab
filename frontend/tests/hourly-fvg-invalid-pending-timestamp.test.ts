import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic archive integrity only: no broker quotes, volume receipt or fills.
const H=3600;
const source={
 datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
 volumeType:'unverified' as const,volumeVerified:false,
};
for(const direction of ['BULLISH','BEARISH'] as const){
 for(const invalidTime of [NaN,Infinity,-Infinity,23.5*H,24*H+1,-0]){
  test(`pending ${direction} malformed timestamp ${String(invalidTime)} fails closed`,()=>{
   const bullish=direction==='BULLISH';
   const bars:Bar[]=Array.from({length:21},(_,i)=>({
    time:i*H,open:100,high:101,low:99,close:100,
    volume:10,observed_minutes:60,
   }));
   bars.push(...(bullish?[
    {time:21*H,open:102,high:105,low:101,close:104,volume:10,observed_minutes:60},
    {time:22*H,open:104,high:106,low:103,close:105,volume:10,observed_minutes:60},
   ]:[
    {time:21*H,open:99,high:100,low:96,close:97,volume:10,observed_minutes:60},
    {time:22*H,open:97,high:98,low:95,close:96,volume:10,observed_minutes:60},
   ]));
   assert.ok(studyHourlyFvgMidpointAsOf(bars,source,23*H).observations.length>0);
   let futureMarketReads=0;
   const forbidden=():never=>{futureMarketReads++;throw Error('future OHLC/volume read');};
   const pending={
    time:invalidTime,
    get open(){return forbidden();},get high(){return forbidden();},
    get low(){return forbidden();},get close(){return forbidden();},
    get volume(){return forbidden();},get observed_minutes(){return forbidden();},
   } as unknown as Bar;
   assert.throws(
    ()=>studyHourlyFvgMidpointAsOf([...bars,pending],source,23*H),
    /Invalid or unordered hourly as-of input timestamp/,
   );
   assert.equal(futureMarketReads,0);
  });
 }
}
