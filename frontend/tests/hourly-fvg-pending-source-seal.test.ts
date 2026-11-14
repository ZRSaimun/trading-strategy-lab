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

for(const field of ['datasetId','archiveSha256','instrument','provider',
 'priceSide','volumeType','volumeVerified'] as const){
 test(`pending timestamp cannot replace own source identity ${field} with inherited prototype evidence`,()=>{
  const source:FvgSource={
   datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
   instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
   volumeType:'unverified',volumeVerified:false,
  };
  const original=source[field];
  const bars:Bar[]=Array.from({length:23},(_,i)=>({
   time:i*H,open:100,high:101,low:99,close:100,
   volume:10,observed_minutes:60,
  }));
  let timestampReads=0,marketReads=0;
  const forbidden=():never=>{marketReads++;throw Error('future market field read');};
  bars.push({
   get time(){
    timestampReads++;
    const inherited=Object.create(null) as Record<string,unknown>;
    Object.defineProperty(inherited,field,{value:original,enumerable:true});
    Object.setPrototypeOf(source,inherited);
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
  assert.equal(source[field],original);
 });
}

for(const field of ['datasetId','archiveSha256','instrument','provider',
 'priceSide','volumeType','volumeVerified'] as const){
 test(`pending timestamp cannot replace source identity ${field} with a same-value accessor`,()=>{
  const source:FvgSource={
   datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
   instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
   volumeType:'unverified',volumeVerified:false,
  };
  const original=source[field];
  const bars:Bar[]=Array.from({length:23},(_,i)=>({
   time:i*H,open:100,high:101,low:99,close:100,
   volume:10,observed_minutes:60,
  }));
  let timestampReads=0,marketReads=0,sourceGetterReads=0;
  const forbidden=():never=>{marketReads++;throw Error('future market field read');};
  bars.push({
   get time(){
    timestampReads++;
    Object.defineProperty(source,field,{
     enumerable:true,configurable:true,
     get(){sourceGetterReads++;return original;},
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
  assert.equal(sourceGetterReads,0,'descriptor comparison must not invoke replacement accessor');
 });
}

test('unchanged source declaration permits pending timestamp without reading pending market fields',()=>{
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
 const forbidden=():never=>{marketReads++;throw Error('pending market field read');};
 bars.push({
  get time(){timestampReads++;return 23*H;},
  get open(){return forbidden();},get high(){return forbidden();},
  get low(){return forbidden();},get close(){return forbidden();},
  get volume(){return forbidden();},
  get observed_minutes(){return forbidden();},
 } as unknown as Bar);
 assert.doesNotThrow(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H));
 assert.equal(timestampReads,1);
 assert.equal(marketReads,0);
});


test('unchanged declaration skips strictly future pending hour without touching its market fields',()=>{
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
  get time(){timestampReads++;return 24*H;},
  get open(){return forbidden();},get high(){return forbidden();},
  get low(){return forbidden();},get close(){return forbidden();},
  get volume(){return forbidden();},
  get observed_minutes(){return forbidden();},
 } as unknown as Bar);
 assert.doesNotThrow(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H));
 assert.equal(timestampReads,1);
 assert.equal(marketReads,0);
});

test('strictly future timestamp cannot rewrite completed-prefix source identity',()=>{
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
  get time(){timestampReads++;source.datasetId='c'.repeat(64);return 24*H;},
  get open(){return forbidden();},get high(){return forbidden();},
  get low(){return forbidden();},get close(){return forbidden();},
  get volume(){return forbidden();},
  get observed_minutes(){return forbidden();},
 } as unknown as Bar);
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H),
  /FVG source declaration field changed during declaration snapshot/);
 assert.equal(timestampReads,1);
 assert.equal(marketReads,0);
});


test('throwing future timestamp getter cannot cause future market field reads',()=>{
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
  get time():number{timestampReads++;throw Error('synthetic timestamp unavailable');},
  get open(){return forbidden();},get high(){return forbidden();},
  get low(){return forbidden();},get close(){return forbidden();},
  get volume(){return forbidden();},
  get observed_minutes(){return forbidden();},
 } as unknown as Bar);
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H),
  /synthetic timestamp unavailable/);
 assert.equal(timestampReads,1);
 assert.equal(marketReads,0);
});

test('non-finite future timestamp fails closed without reading future market evidence',()=>{
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
  get time(){timestampReads++;return Number.NaN;},
  get open(){return forbidden();},get high(){return forbidden();},
  get low(){return forbidden();},get close(){return forbidden();},
  get volume(){return forbidden();},
  get observed_minutes(){return forbidden();},
 } as unknown as Bar);
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H));
 assert.equal(timestampReads,1);
 assert.equal(marketReads,0);
});

for(const invalidTime of [Number.POSITIVE_INFINITY,Number.NEGATIVE_INFINITY] as const){
 test(`infinite future timestamp ${invalidTime} fails closed before market evidence access`,()=>{
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
   get time(){timestampReads++;return invalidTime;},
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},
   get observed_minutes(){return forbidden();},
  } as unknown as Bar);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H));
  assert.equal(timestampReads,1);
  assert.equal(marketReads,0);
 });
}


for(const malformedTime of [null,'86400000'] as const){
 test(`non-numeric pending timestamp ${String(malformedTime)} cannot coerce into closed-bar evidence`,()=>{
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
   get time(){timestampReads++;return malformedTime as unknown as number;},
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},
   get observed_minutes(){return forbidden();},
  } as unknown as Bar);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H));
  assert.equal(timestampReads,1);
  assert.equal(marketReads,0);
 });
}

for(const malformedTime of [false,true,undefined] as const){
 test(`boolean or missing pending timestamp ${String(malformedTime)} fails closed without coercion`,()=>{
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
   get time(){timestampReads++;return malformedTime as unknown as number;},
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},
   get observed_minutes(){return forbidden();},
  } as unknown as Bar);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H));
  assert.equal(timestampReads,1);
  assert.equal(marketReads,0);
 });
}

for (const malformedTime of [23n * BigInt(H), Symbol('future-hour')] as const) {
 test(`non-JSON pending timestamp ${String(malformedTime)} fails closed before future market reads`,()=>{
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
   get time(){timestampReads++;return malformedTime as unknown as number;},
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},
   get observed_minutes(){return forbidden();},
  } as unknown as Bar);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H));
  assert.equal(timestampReads,1);
  assert.equal(marketReads,0);
 });
}
