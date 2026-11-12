import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// A pending timestamp accessor must not rewrite a completed timestamp's
// signed-zero representation, even though ordinary === considers them equal.
const H=3600;
const source={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
 volumeType:'unverified' as const,volumeVerified:false};
for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending ${direction} hour cannot change completed time 0 to -0`,()=>{
  const bars:Bar[]=Array.from({length:21},(_,i)=>({
   time:i*H,open:100,high:101,low:99,close:100,
   volume:10,observed_minutes:60,
  }));
  bars.push(...(direction==='BULLISH'?[
   {time:21*H,open:102,high:105,low:101,close:104,volume:10,observed_minutes:60},
   {time:22*H,open:104,high:106,low:103,close:105,volume:10,observed_minutes:60},
  ]:[
   {time:21*H,open:99,high:100,low:96,close:97,volume:10,observed_minutes:60},
   {time:22*H,open:97,high:98,low:95,close:96,volume:10,observed_minutes:60},
  ]));
  assert.ok(studyHourlyFvgMidpointAsOf(bars,source,23*H).observations.length>0);
  let timestampReads=0,futureMarketReads=0;
  const forbidden=():never=>{futureMarketReads++;throw Error('future market read');};
  bars.push({
   get time(){
    timestampReads++;
    bars[0].time=-0;
    return 23*H;
   },
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},get observed_minutes(){return forbidden();},
  } as unknown as Bar);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H),
   /FVG as-of timestamp field changed during declaration snapshot/);
  assert.equal(timestampReads,1);
  assert.equal(futureMarketReads,0);
 });
}

// A benign pending timestamp accessor must not be mistaken for a historical
// mutation merely because it is an accessor. Only its timestamp is eligible.
for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending ${direction} timestamp-only accessor preserves completed-prefix results`,()=>{
  const bars:Bar[]=Array.from({length:21},(_,i)=>({
   time:i*H,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
  }));
  bars.push(...(direction==='BULLISH'?[
   {time:21*H,open:102,high:105,low:101,close:104,volume:10,observed_minutes:60},
   {time:22*H,open:104,high:106,low:103,close:105,volume:10,observed_minutes:60},
  ]:[
   {time:21*H,open:99,high:100,low:96,close:97,volume:10,observed_minutes:60},
   {time:22*H,open:97,high:98,low:95,close:96,volume:10,observed_minutes:60},
  ]));
  const expected=studyHourlyFvgMidpointAsOf(bars,source,23*H);
  assert.ok(expected.observations.length>0);
  let timestampReads=0,futureMarketReads=0;
  const forbidden=():never=>{futureMarketReads++;throw Error('future market read');};
  bars.push({
   get time(){timestampReads++;return 23*H;},
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},get observed_minutes(){return forbidden();},
  } as unknown as Bar);
  const actual=studyHourlyFvgMidpointAsOf(bars,source,23*H);
  assert.deepEqual(actual,expected);
  assert.equal(timestampReads,1);
  assert.equal(futureMarketReads,0);
 });
}


// Rejecting a mutated archive must not permanently poison a caller's ability
// to re-run a corrected completed-prefix snapshot (no implicit global cache).
test('corrected completed timestamp can be studied after signed-zero rejection',()=>{
 const bars:Bar[]=Array.from({length:21},(_,i)=>({
  time:i*H,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
 }));
 bars.push(
  {time:21*H,open:102,high:105,low:101,close:104,volume:10,observed_minutes:60},
  {time:22*H,open:104,high:106,low:103,close:105,volume:10,observed_minutes:60},
 );
 const expected=studyHourlyFvgMidpointAsOf(bars,source,23*H);
 assert.ok(expected.observations.length>0);
 let reads=0;
 const pending:Bar={
  get time(){reads++;bars[0].time=-0;return 23*H;},
  get open(){throw Error('future OHLC read');},
  get high(){throw Error('future OHLC read');},
  get low(){throw Error('future OHLC read');},
  get close(){throw Error('future OHLC read');},
  get volume(){throw Error('future volume read');},
  get observed_minutes(){throw Error('future coverage read');},
 } as unknown as Bar;
 bars.push(pending);
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H),
  /FVG as-of timestamp field changed during declaration snapshot/);
 assert.equal(reads,1);
 bars[0].time=0;
 bars.pop();
 assert.deepEqual(studyHourlyFvgMidpointAsOf(bars,source,23*H),expected);
});
