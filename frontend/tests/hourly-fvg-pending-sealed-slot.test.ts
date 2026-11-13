import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic input-integrity regression only; not real market or execution data.
const H=3600;
const source={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
 volumeType:'unverified' as const,volumeVerified:false};

for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending timestamp cannot permanently seal completed ${direction} volume-baseline slot`,()=>{
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
     enumerable:true,configurable:false});
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
  assert.equal(Object.getOwnPropertyDescriptor(bars,'12')?.configurable,false);
 });
}

// An irreversible non-writable descriptor must also fail closed; no automatic repair is possible.
for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending timestamp cannot freeze completed ${direction} volume-baseline slot`,()=>{
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
     enumerable:true,configurable:false});
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
  assert.equal(Object.getOwnPropertyDescriptor(bars,'12')?.configurable,false);
  assert.equal(Object.getOwnPropertyDescriptor(bars,'12')?.writable,false);
 });
}
