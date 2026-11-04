import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpoint,studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

const H=3600;
const source={
 datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
 volumeType:'unverified' as const,volumeVerified:false,
};
const bars=():Bar[]=>Array.from({length:3},(_,i)=>({
 time:i*H,open:100,high:102,low:98,close:100,volume:0,observed_minutes:60,
}));

test('hourly FVG rejects hidden own-index archive rows in both research paths',()=>{
 for(const index of [0,1,2]){
  const archive=bars();
  Object.defineProperty(archive,index,{
   value:archive[index],enumerable:false,writable:true,configurable:true,
  });
  assert.throws(()=>studyHourlyFvgMidpoint(archive,source),
   /missing or hidden own-index/);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(archive,source,3*H),
   /missing or hidden own-index/);
 }
 const ordinary=bars();
 assert.doesNotThrow(()=>studyHourlyFvgMidpoint(ordinary,source));
 assert.doesNotThrow(()=>studyHourlyFvgMidpointAsOf(ordinary,source,3*H));
});

test('hourly FVG refuses sparse own-index holes even when prototype supplies a candle',()=>{
 for(const index of [0,1,2]){
  const archive=bars();
  const inherited=archive[index];
  delete archive[index];
  const prototype=Object.create(Array.prototype);
  Object.defineProperty(prototype,String(index),{
   value:inherited,enumerable:true,configurable:true,writable:true,
  });
  Object.setPrototypeOf(archive,prototype);
  assert.throws(()=>studyHourlyFvgMidpoint(archive,source),
   /missing or hidden own-index/);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(archive,source,3*H),
   /missing or hidden own-index/);
 }
});

test('hidden hourly archive getter is rejected before executing caller code',()=>{
 for(const index of [0,1,2]){
  const archive=bars();
  let reads=0;
  Object.defineProperty(archive,index,{
   enumerable:false,configurable:true,
   get(){reads++;throw Error('hidden candle getter executed');},
  });
  assert.throws(()=>studyHourlyFvgMidpoint(archive,source),
   /missing or hidden own-index/);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(archive,source,3*H),
   /missing or hidden own-index/);
  assert.equal(reads,0,'hidden archive getters must not run');
 }
});


test('inherited sparse hourly candle getters are never evaluated',()=>{
 for(const index of [0,1,2]){
  const archive=bars();
  delete archive[index];
  let inheritedReads=0;
  const prototype=Object.create(Array.prototype);
  Object.defineProperty(prototype,String(index),{
   enumerable:true,configurable:true,
   get(){inheritedReads++;throw Error('inherited candle getter executed');},
  });
  Object.setPrototypeOf(archive,prototype);
  assert.throws(()=>studyHourlyFvgMidpoint(archive,source),
   /missing or hidden own-index/);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(archive,source,3*H),
   /missing or hidden own-index/);
  assert.equal(inheritedReads,0,'inherited sparse getters must not run');
 }
});

test('as-of FVG rejects enumerable indexed getters before any row or future timestamp read',()=>{
 for(const index of [0,1,2]){
  const archive=bars();
  const original=archive[index];
  let rowReads=0;
  Object.defineProperty(archive,index,{
   enumerable:true,configurable:true,
   get(){rowReads++;return original;},
  });
  assert.throws(()=>studyHourlyFvgMidpointAsOf(archive,source,3*H),
   /own data-property candle slots/);
  assert.equal(rowReads,0,'as-of must not invoke indexed row getters');
  // Full-history research intentionally retains single-snapshot accessor support.
  assert.doesNotThrow(()=>studyHourlyFvgMidpoint(archive,source));
 }
 const ordinary=bars();
 assert.doesNotThrow(()=>studyHourlyFvgMidpointAsOf(ordinary,source,3*H));
});

test('as-of rejects indexed accessors before touching future timestamp getters',()=>{
 const archive=bars();
 let indexedReads=0;
 let futureTimeReads=0;
 const original=archive[0];
 Object.defineProperty(archive,0,{
  enumerable:true,configurable:true,
  get(){indexedReads++;return original;},
 });
 Object.defineProperty(archive[2],'time',{
  enumerable:true,configurable:true,
  get(){futureTimeReads++;throw Error('future timestamp unexpectedly read');},
 });
 assert.throws(()=>studyHourlyFvgMidpointAsOf(archive,source,2*H),
  /own data-property candle slots/);
 assert.equal(indexedReads,0,'indexed accessor must not execute');
 assert.equal(futureTimeReads,0,'future timestamp must remain unread on preflight rejection');
});


test('hourly FVG rejects hidden archive-level metadata without evaluating its getter',()=>{
 for(const asOf of [false,true]){
  const archive=bars();
  let metadataReads=0;
  Object.defineProperty(archive,'brokerAskSnapshot',{
   enumerable:false,configurable:true,
   get(){metadataReads++;throw Error('hidden ASK metadata was evaluated');},
  });
  assert.throws(()=>asOf?
   studyHourlyFvgMidpointAsOf(archive,source,3*H):
   studyHourlyFvgMidpoint(archive,source),
   /Unexpected FVG archive array metadata/);
  assert.equal(metadataReads,0,'undeclared broker metadata must never execute');
 }
 const ordinary=bars();
 assert.doesNotThrow(()=>studyHourlyFvgMidpoint(ordinary,source));
 assert.doesNotThrow(()=>studyHourlyFvgMidpointAsOf(ordinary,source,3*H));
});

test('hourly FVG rejects symbol-keyed archive receipts without invoking getters',()=>{
 for(const asOf of [false,true]){
  const archive=bars();
  const receipt=Symbol('unverified broker ASK receipt');
  let reads=0;
  Object.defineProperty(archive,receipt,{
   enumerable:true,configurable:true,
   get(){reads++;throw Error('symbol receipt getter executed');},
  });
  assert.throws(()=>asOf?
   studyHourlyFvgMidpointAsOf(archive,source,3*H):
   studyHourlyFvgMidpoint(archive,source),
   /Unexpected FVG archive array metadata/);
  assert.equal(reads,0,'symbol-keyed undeclared evidence must never execute');
 }
});

test('non-enumerable symbol-keyed FVG archive metadata is rejected without executing getters',()=>{
 for(const asOf of [false,true]){
  const archive=bars();
  let reads=0;
  Object.defineProperty(archive,Symbol('unverified hidden ASK receipt'),{
   enumerable:false,configurable:true,
   get(){reads++;throw Error('hidden symbol getter executed');},
  });
  assert.throws(()=>asOf?
   studyHourlyFvgMidpointAsOf(archive,source,3*H):
   studyHourlyFvgMidpoint(archive,source),
   /Unexpected FVG archive array metadata/);
  assert.equal(reads,0,'hidden symbol-keyed evidence must never be evaluated');
 }
});

test('own archive iterator overrides are undeclared evidence and never executed',()=>{
 for(const asOf of [false,true]){
  const archive=bars();
  let reads=0;
  Object.defineProperty(archive,Symbol.iterator,{
   enumerable:false,configurable:true,
   get(){reads++;throw Error('untrusted iterator getter executed');},
  });
  assert.throws(()=>asOf?
   studyHourlyFvgMidpointAsOf(archive,source,3*H):
   studyHourlyFvgMidpoint(archive,source),
   /Unexpected FVG archive array metadata/);
  assert.equal(reads,0,'own iterator getter must not execute');
 }
 const ordinary=bars();
 assert.doesNotThrow(()=>studyHourlyFvgMidpoint(ordinary,source));
 assert.doesNotThrow(()=>studyHourlyFvgMidpointAsOf(ordinary,source,3*H));
});
