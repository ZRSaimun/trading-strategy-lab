import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic, BID-only source: this tests a failed archive timestamp read,
// not volume authenticity, broker execution, or strategy profitability.
const H=3600;
const source={
 datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
 volumeType:'unverified' as const,volumeVerified:false,
};

for(const direction of ['BULLISH','BEARISH'] as const){
 test(`a throwing pending ${direction} timestamp cannot be silently omitted`,()=>{
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
  const prefix=studyHourlyFvgMidpointAsOf(bars,source,23*H);
  assert.ok(prefix.observations.length>0);
  let timeReads=0;
  let futureMarketReads=0;
  const forbidden=():never=>{futureMarketReads++;throw Error('future market field read');};
  const pending={
   get time(){timeReads++;throw Error('unreadable future timestamp');},
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},
   get observed_minutes(){return forbidden();},
  } as unknown as Bar;
  assert.throws(
   ()=>studyHourlyFvgMidpointAsOf([...bars,pending],source,23*H),
   /unreadable future timestamp|timestamp|invalid/i,
  );
  assert.equal(timeReads,1);
  assert.equal(futureMarketReads,0);
 });
}

test('a failed first pending timestamp cannot inspect a later pending candle',()=>{
 const H=3600;
 const bars:Bar[]=Array.from({length:23},(_,i)=>({
  time:i*H,open:100,high:101,low:99,close:100,
  volume:10,observed_minutes:60,
 }));
 let firstTimeReads=0,laterReads=0,marketReads=0;
 const forbidden=():never=>{marketReads++;throw Error('future market field read');};
 const first={
  get time(){firstTimeReads++;throw Error('unreadable first pending timestamp');},
  get open(){return forbidden();},get high(){return forbidden();},
  get low(){return forbidden();},get close(){return forbidden();},
  get volume(){return forbidden();},get observed_minutes(){return forbidden();},
 } as unknown as Bar;
 const later={
  get time(){laterReads++;throw Error('later pending timestamp inspected');},
  get open(){laterReads++;throw Error('later pending open inspected');},
  get high(){laterReads++;throw Error('later pending high inspected');},
  get low(){laterReads++;throw Error('later pending low inspected');},
  get close(){laterReads++;throw Error('later pending close inspected');},
  get volume(){laterReads++;throw Error('later pending volume inspected');},
  get observed_minutes(){laterReads++;throw Error('later pending coverage inspected');},
 } as unknown as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([...bars,first,later],source,23*H),
  /unreadable first pending timestamp|timestamp|invalid/i,
 );
 assert.equal(firstTimeReads,1);
 assert.equal(marketReads,0,'first pending market fields remain unread');
 assert.equal(laterReads,0,'later pending getters must not execute after failure');
});
