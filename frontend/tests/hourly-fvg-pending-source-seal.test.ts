import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic provenance-integrity regression, not source authentication.
const H=3600;
for(const field of ['datasetId','archiveSha256','instrument','provider',
 'priceSide','volumeType','volumeVerified'] as const){
 for(const variant of [
  {configurable:false,writable:true,enumerable:true},
  {configurable:false,writable:false,enumerable:true},
  {configurable:true,writable:false,enumerable:true},
  {configurable:true,writable:true,enumerable:false},
 ] as const){
 test(`pending timestamp cannot permanently seal source declaration ${field} configurable=${variant.configurable} writable=${variant.writable} enumerable=${variant.enumerable}`,()=>{
  const source:FvgSource={
   datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
   instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
   volumeType:'unverified',volumeVerified:false,
  };
  const bars:Bar[]=Array.from({length:23},(_,i)=>({
   time:i*H,open:100,high:101,low:99,close:100,
   volume:10,observed_minutes:60,
  }));
  const value=source[field];
  let timestampReads=0,marketReads=0;
  const forbidden=():never=>{marketReads++;throw Error('future market field read');};
  bars.push({
   get time(){
    timestampReads++;
    Object.defineProperty(source,field,{
     value,...variant,
    });
    return 23*H;
   },
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},
   get observed_minutes(){return forbidden();},
  } as unknown as Bar);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H),
   /FVG source declaration field changed during declaration snapshot/);
  assert.equal(timestampReads,1);
  assert.equal(marketReads,0);
  assert.equal(source[field],value);
  assert.equal(Object.getOwnPropertyDescriptor(source,field)?.configurable,variant.configurable);
  assert.equal(Object.getOwnPropertyDescriptor(source,field)?.writable,variant.writable);
  assert.equal(Object.getOwnPropertyDescriptor(source,field)?.enumerable,variant.enumerable);
 });
 }
}

for(const field of ['datasetId','archiveSha256','instrument','provider',
 'priceSide','volumeType','volumeVerified'] as const){
 test(`pending timestamp cannot delete source declaration ${field} after completed-prefix snapshot`,()=>{
  const source:FvgSource={
   datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
   instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
   volumeType:'unverified',volumeVerified:false,
  };
  const bars:Bar[]=Array.from({length:23},(_,i)=>({
   time:i*H,open:100,high:101,low:99,close:100,
   volume:10,observed_minutes:60,
  }));
  let timestampReads=0,marketReads=0;
  const forbidden=():never=>{marketReads++;throw Error('future market field read');};
  bars.push({
   get time(){
    timestampReads++;
    assert.equal(Reflect.deleteProperty(source,field),true);
    return 23*H;
   },
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},
   get observed_minutes(){return forbidden();},
  } as unknown as Bar);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H),
   /FVG as-of source declaration schema changed during timestamp scan/);
  assert.equal(timestampReads,1);
  assert.equal(marketReads,0);
  assert.equal(Object.hasOwn(source,field),false);
 });
}

const alternateSourceValues = {
 datasetId:'c'.repeat(64),archiveSha256:'d'.repeat(64),
 instrument:'OTHER_SYNTHETIC',provider:'other-fixture',
 priceSide:'ask',volumeType:'tick',volumeVerified:true,
} as const;
for(const field of Object.keys(alternateSourceValues) as (keyof typeof alternateSourceValues)[]){
 test(`pending timestamp cannot rewrite source declaration value ${field} after completed-prefix snapshot`,()=>{
  const source:FvgSource={
   datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
   instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
   volumeType:'unverified',volumeVerified:false,
  };
  const bars:Bar[]=Array.from({length:23},(_,i)=>({
   time:i*H,open:100,high:101,low:99,close:100,
   volume:10,observed_minutes:60,
  }));
  let timestampReads=0,marketReads=0;
  const forbidden=():never=>{marketReads++;throw Error('future market field read');};
  bars.push({
   get time(){
    timestampReads++;
    // Mutation occurs only after the completed prefix has been snapshotted.
    Object.defineProperty(source,field,{value:alternateSourceValues[field]});
    return 23*H;
   },
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},
   get observed_minutes(){return forbidden();},
  } as unknown as Bar);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H),
   /FVG source declaration field changed during declaration snapshot/);
  assert.equal(timestampReads,1);
  assert.equal(marketReads,0);
  assert.equal(source[field],alternateSourceValues[field]);
 });
}
