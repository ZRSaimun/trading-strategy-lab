import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic archive-integrity tests; no authenticated prices or volume.
const H=3600;
const source={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
 volumeType:'unverified' as const,volumeVerified:false};

for(const direction of ['BULLISH','BEARISH'] as const){
 for(const field of ['time','open','high','low','close','volume','observed_minutes'] as const){
  test(`pending timestamp cannot freeze completed ${direction} ${field} field`,()=>{
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
   const completed=bars[12];
   const value=completed[field];
   let timeReads=0,marketReads=0;
   const forbidden=():never=>{marketReads++;throw Error('future market field read');};
   bars.push({
    get time(){
     timeReads++;
     Object.defineProperty(completed,field,{
      value,writable:false,enumerable:true,configurable:false,
     });
     return 23*H;
    },
    get open(){return forbidden();},get high(){return forbidden();},
    get low(){return forbidden();},get close(){return forbidden();},
    get volume(){return forbidden();},
    get observed_minutes(){return forbidden();},
   } as unknown as Bar);
   // The timestamp has an earlier, more specific declaration-snapshot guard.
   // Both rejection paths are fail-closed; only non-time fields use the general guard.
   const rejection=field==='time'
    ? /FVG as-of timestamp field changed during declaration snapshot/
    : /Hourly research completed candle field changed during snapshot/;
   assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H),rejection);
   assert.equal(timeReads,1);
   assert.equal(marketReads,0);
   assert.equal(completed[field],value);
   const descriptor=Object.getOwnPropertyDescriptor(completed,field);
   assert.equal(descriptor?.configurable,false);
   assert.equal(descriptor?.writable,false);
  });
 }
}

 
// Formation rows must receive the same descriptor protection as prior-20
// baseline rows. These are completed candles, not pending confirmation data.
for (const direction of ['BULLISH','BEARISH'] as const) {
 for (const formationIndex of [21,22] as const) {
  for (const field of ['time','volume','observed_minutes'] as const) {
  test(`pending timestamp cannot seal completed ${direction} formation row ${formationIndex} ${field}`,()=>{
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
   const completed=bars[formationIndex];
   const originalValue=completed[field];
   let timeReads=0,marketReads=0;
   const forbidden=():never=>{marketReads++;throw Error('future market field read');};
   bars.push({
    get time(){
     timeReads++;
     Object.defineProperty(completed,field,{
      value:originalValue,writable:false,enumerable:true,configurable:false,
     });
     return 23*H;
    },
    get open(){return forbidden();},get high(){return forbidden();},
    get low(){return forbidden();},get close(){return forbidden();},
    get volume(){return forbidden();},get observed_minutes(){return forbidden();},
   } as unknown as Bar);
   assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H),
    field==='time' ? /FVG as-of timestamp field changed during declaration snapshot/ : /Hourly research completed candle field changed during snapshot/);
   assert.equal(timeReads,1);
   assert.equal(marketReads,0);
   assert.equal(completed[field],originalValue);
   assert.equal(Object.getOwnPropertyDescriptor(completed,field)?.configurable,false);
  });
  }
 }
}
