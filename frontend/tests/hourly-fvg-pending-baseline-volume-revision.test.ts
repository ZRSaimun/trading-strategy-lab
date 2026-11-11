import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// A pending row must not silently revise numeric completed-bar volume evidence.
const H=3600;
for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending ${direction} timestamp cannot revise completed prior-20 numeric volume`,()=>{
  const source={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
   instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
   volumeType:'unverified' as const,volumeVerified:false};
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
    bars[10].volume=11;
    return 23*H;
   },
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},get observed_minutes(){return forbidden();},
  } as unknown as Bar);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H),
   /Hourly research completed candle field changed during snapshot/);
  assert.equal(timestampReads,1);
  assert.equal(futureMarketReads,0);
 });
}

// A completed prior-20 minute-coverage receipt cannot be revised by a
// future, unclosed candle's timestamp getter, even if OHLC stays unchanged.
for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending ${direction} timestamp cannot revise completed prior-20 minute coverage`,()=>{
  const source={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
   instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
   volumeType:'unverified' as const,volumeVerified:false};
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
    bars[10].observed_minutes=59;
    return 23*H;
   },
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},get observed_minutes(){return forbidden();},
  } as unknown as Bar);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H),
   /Hourly research completed candle field changed during snapshot/);
  assert.equal(timestampReads,1);
  assert.equal(futureMarketReads,0);
 });
}

// A pending candle must not retroactively rewrite completed price evidence.
// Test both directions; no future market accessor may be evaluated.
for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending ${direction} timestamp cannot revise completed prior-20 closing price`,()=>{
  const source={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
   instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
   volumeType:'unverified' as const,volumeVerified:false};
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
  assert.ok(studyHourlyFvgMidpointAsOf(bars,source,23*H).observations.length>0);
  let timestampReads=0,futureMarketReads=0;
  const forbidden=():never=>{futureMarketReads++;throw Error('future market read');};
  bars.push({
   get time(){
    timestampReads++;
    bars[10].close=100.5;
    return 23*H;
   },
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},get observed_minutes(){return forbidden();},
  } as unknown as Bar);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H),
   /Hourly research completed candle field changed during snapshot/);
  assert.equal(timestampReads,1);
  assert.equal(futureMarketReads,0);
 });
}

// A pending hour cannot retroactively shift a completed baseline timestamp.
// Timestamp continuity is part of the causal prior-20 evidence boundary.
for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending ${direction} timestamp cannot revise completed prior-20 time`,()=>{
  const source={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
   instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
   volumeType:'unverified' as const,volumeVerified:false};
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
  assert.ok(studyHourlyFvgMidpointAsOf(bars,source,23*H).observations.length>0);
  let timestampReads=0,futureMarketReads=0;
  const forbidden=():never=>{futureMarketReads++;throw Error('future market read');};
  bars.push({
   get time(){timestampReads++;bars[10].time=10*H+1;return 23*H;},
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


// An unclosed future hour must not rewrite the remaining completed OHLC
// evidence fields. Closing price and timestamp have separate regressions.
for (const direction of ['BULLISH', 'BEARISH'] as const) {
 for (const field of ['open', 'high', 'low'] as const) {
  test(`pending ${direction} timestamp cannot revise completed prior-20 ${field}`, () => {
   const source={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
    instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
    volumeType:'unverified' as const,volumeVerified:false};
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
   assert.ok(studyHourlyFvgMidpointAsOf(bars,source,23*H).observations.length>0);
   let timestampReads=0,futureMarketReads=0;
   const forbidden=():never=>{futureMarketReads++;throw Error('future market read');};
   bars.push({
    get time(){
     timestampReads++;
     bars[10][field]=({open:100.5,high:102,low:98.5})[field];
     return 23*H;
    },
    get open(){return forbidden();},get high(){return forbidden();},
    get low(){return forbidden();},get close(){return forbidden();},
    get volume(){return forbidden();},get observed_minutes(){return forbidden();},
   } as unknown as Bar);
   assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H),
    /Hourly research completed candle field changed during snapshot/);
   assert.equal(timestampReads,1);
   assert.equal(futureMarketReads,0);
  });
 }
}
