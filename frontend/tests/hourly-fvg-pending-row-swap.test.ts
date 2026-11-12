import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic evidence-integrity tests, not authenticated market prices or fills.
const H=3600;
const source={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
 volumeType:'unverified' as const,volumeVerified:false};

for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending timestamp cannot swap completed ${direction} archive row`,()=>{
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
  const original=bars[0];
  let timeReads=0,marketReads=0;
  const forbidden=():never=>{marketReads++;throw Error('future market field read');};
  bars.push({
   get time(){timeReads++;bars[0]={...original};return 23*H;},
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},
   get observed_minutes(){return forbidden();},
  } as unknown as Bar);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H),
   /Hourly research candle row identity changed during snapshot/);
  assert.equal(timeReads,1);
  assert.equal(marketReads,0);
  assert.notStrictEqual(bars[0],original);
  // A rejected invocation must not poison the next independent scan.
  // The caller explicitly restores the original object and drops the pending
  // accessor; the study never claims to repair mutated source evidence.
  const completed=bars.slice(0,-1);
  completed[0]=original;
  const baseline=studyHourlyFvgMidpointAsOf(completed,source,23*H);
  assert.ok(baseline.observations.length>0);
  bars[0]=original;
  bars.pop();
  assert.deepEqual(studyHourlyFvgMidpointAsOf(bars,source,23*H),baseline);
 });
}

// The most recent completed formation bar is equally protected: a future
// timestamp accessor cannot substitute its object even with identical values.
for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending timestamp cannot swap latest completed ${direction} formation row`,()=>{
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
  const original=bars[22];
  let timeReads=0,marketReads=0;
  const forbidden=():never=>{marketReads++;throw Error('future market field read');};
  bars.push({
   get time(){timeReads++;bars[22]={...original};return 23*H;},
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},
   get observed_minutes(){return forbidden();},
  } as unknown as Bar);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H),
   /Hourly research candle row identity changed during snapshot/);
  assert.equal(timeReads,1);
  assert.equal(marketReads,0);
  assert.notStrictEqual(bars[22],original);
 });
}

// A middle completed row can supply the prior-20 median volume baseline.
// Replacing it while the future timestamp is inspected must be detected even
// when its OHLC/volume fields are identical, before future market data is read.
for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending timestamp cannot swap prior-20 ${direction} volume-baseline row`,()=>{
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
  const original=bars[12];
  let timeReads=0,marketReads=0;
  const forbidden=():never=>{marketReads++;throw Error('future market field read');};
  bars.push({
   get time(){timeReads++;bars[12]={...original};return 23*H;},
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},
   get observed_minutes(){return forbidden();},
  } as unknown as Bar);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H),
   /Hourly research candle row identity changed during snapshot/);
  assert.equal(timeReads,1);
  assert.equal(marketReads,0);
  assert.notStrictEqual(bars[12],original);
  // Rebuild a clean reference independently of the hostile pending accessor.
  // Restoration is caller-owned: the scanner does not repair its inputs.
  const repaired=bars.slice(0,-1);
  repaired[12]=original;
  const baseline=studyHourlyFvgMidpointAsOf(repaired,source,23*H);
  assert.ok(baseline.observations.length>0);
  bars[12]=original;
  bars.pop();
  assert.deepEqual(studyHourlyFvgMidpointAsOf(bars,source,23*H),baseline);
 });
}


// A future timestamp accessor must not permute two completed rows. A swap
// preserves array length and every row object/value, but changes chronology.
for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending timestamp cannot permute completed ${direction} archive rows`,()=>{
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
  const first=bars[10],second=bars[11];
  let timeReads=0,marketReads=0;
  const forbidden=():never=>{marketReads++;throw Error('future market field read');};
  bars.push({
   get time(){timeReads++;bars[10]=second;bars[11]=first;return 23*H;},
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},
   get observed_minutes(){return forbidden();},
  } as unknown as Bar);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H),
   /Hourly research candle row identity changed during snapshot/);
  assert.equal(timeReads,1);
  assert.equal(marketReads,0);
  assert.strictEqual(bars[10],second);
  assert.strictEqual(bars[11],first);
 });
}


// A completed archive slot becoming read-only is a representation change
// even if the same candle object and prices remain in place. Do not let an
// unclosed candle's timestamp accessor change the declared archive schema.
for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending timestamp cannot freeze completed ${direction} archive slot`,()=>{
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
  const original=bars[12];
  let timeReads=0,marketReads=0;
  const forbidden=():never=>{marketReads++;throw Error('future market field read');};
  bars.push({
   get time(){
    timeReads++;
    Object.defineProperty(bars,'12',{value:original,writable:false,
     enumerable:true,configurable:true});
    return 23*H;
   },
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},
   get observed_minutes(){return forbidden();},
  } as unknown as Bar);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H),
   /Hourly research candle row identity changed during snapshot/);
  assert.equal(timeReads,1);
  assert.equal(marketReads,0);
  assert.strictEqual(bars[12],original);
  assert.equal(Object.getOwnPropertyDescriptor(bars,'12')?.writable,false);
 });
}


// A pending timestamp accessor cannot conceal an otherwise unchanged completed
// candle by making its indexed slot non-enumerable. Reject before future fields.
for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending timestamp cannot hide completed ${direction} archive slot`,()=>{
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
  const original=bars[12];
  let timeReads=0,marketReads=0;
  const forbidden=():never=>{marketReads++;throw Error('future market field read');};
  bars.push({
   get time(){
    timeReads++;
    Object.defineProperty(bars,'12',{value:original,writable:true,
     enumerable:false,configurable:true});
    return 23*H;
   },
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},
   get observed_minutes(){return forbidden();},
  } as unknown as Bar);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H),
   /Hourly research candle row identity changed during snapshot/);
  assert.equal(timeReads,1);
  assert.equal(marketReads,0);
  assert.strictEqual(bars[12],original);
  assert.equal(Object.getOwnPropertyDescriptor(bars,'12')?.enumerable,false);
 });
}
