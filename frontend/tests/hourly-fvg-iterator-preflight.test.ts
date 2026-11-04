import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

const H=3600;
const source={
 datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
 volumeType:'unverified' as const,volumeVerified:false,
};

// A caller-supplied iterator must not be a way to inspect unrevealed evidence.
test('as-of archive iterator preflight precedes future timestamp access',()=>{
 const bars:Bar[]=Array.from({length:3},(_,i)=>({
  time:i*H,open:100,high:102,low:98,close:100,volume:0,observed_minutes:60,
 }));
 let iteratorReads=0;
 let futureTimeReads=0;
 Object.defineProperty(bars,Symbol.iterator,{
  configurable:true,
  get(){iteratorReads++;throw Error('iterator getter executed');},
 });
 Object.defineProperty(bars[2],'time',{
  configurable:true,enumerable:true,
  get(){futureTimeReads++;throw Error('unrevealed future timestamp read');},
 });
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,2*H),
  /Unexpected FVG archive array metadata/);
 assert.equal(iteratorReads,0);
 assert.equal(futureTimeReads,0);
});


// An own data-valued iterator is equally undeclared archive metadata, even
// when it is non-enumerable (the default for defineProperty).
test('full and as-of studies reject a non-enumerable data-valued iterator',async()=>{
 const {studyHourlyFvgMidpoint}=await import('../lib/hourly-fvg-midpoint-study.ts');
 const bars:Bar[]=Array.from({length:3},(_,i)=>({
  time:i*H,open:100,high:102,low:98,close:100,volume:0,observed_minutes:60,
 }));
 let iteratorCalls=0;
 let futureTimeReads=0;
 Object.defineProperty(bars[2],'time',{
  configurable:true,enumerable:true,
  get(){futureTimeReads++;throw Error('future timestamp getter executed');},
 });
 Object.defineProperty(bars,Symbol.iterator,{
  configurable:true,enumerable:false,
  value:()=>{iteratorCalls++;throw Error('custom iterator executed');},
 });
 assert.throws(()=>studyHourlyFvgMidpoint(bars,source),
  /Unexpected FVG archive array metadata/);
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,2*H),
  /Unexpected FVG archive array metadata/);
 assert.equal(iteratorCalls,0);
 assert.equal(futureTimeReads,0);
});


// A second well-known iterator symbol is not an authorized quote/volume channel.
// The archive preflight must reject it without invoking caller code or looking
// ahead to a future timestamp.
test('as-of rejects undeclared async iterator before future time inspection',()=>{
 const bars:Bar[]=Array.from({length:3},(_,i)=>({
  time:i*H,open:100,high:102,low:98,close:100,volume:0,observed_minutes:60,
 }));
 let asyncIteratorReads=0;
 let futureTimeReads=0;
 Object.defineProperty(bars,Symbol.asyncIterator,{
  configurable:true,enumerable:false,
  get(){asyncIteratorReads++;throw Error('async iterator getter executed');},
 });
 Object.defineProperty(bars[2],'time',{
  configurable:true,enumerable:true,
  get(){futureTimeReads++;throw Error('unrevealed future timestamp read');},
 });
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,2*H),
  /Unexpected FVG archive array metadata/);
 assert.equal(asyncIteratorReads,0);
 assert.equal(futureTimeReads,0);
});

// Async iteration is never part of the BID-only JSON archive contract.
// A non-enumerable data property must fail before a future timestamp getter.
test('full and as-of reject data-valued async iterator without future reads',async()=>{
 const {studyHourlyFvgMidpoint}=await import('../lib/hourly-fvg-midpoint-study.ts');
 const bars:Bar[]=Array.from({length:3},(_,i)=>({
  time:i*H,open:100,high:102,low:98,close:100,volume:0,observed_minutes:60,
 }));
 let calls=0;
 let futureReads=0;
 Object.defineProperty(bars,Symbol.asyncIterator,{
  configurable:true,enumerable:false,
  value:()=>{calls++;throw Error('async iterator executed');},
 });
 Object.defineProperty(bars[2],'time',{
  configurable:true,enumerable:true,
  get(){futureReads++;throw Error('future timestamp executed');},
 });
 assert.throws(()=>studyHourlyFvgMidpoint(bars,source),
  /Unexpected FVG archive array metadata/);
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,2*H),
  /Unexpected FVG archive array metadata/);
 assert.equal(calls,0);
 assert.equal(futureReads,0);
});


// A display-oriented well-known symbol is still undeclared array metadata.
// It must not trigger a caller getter or a future candle read in causal replay.
test('as-of rejects own Symbol.toStringTag metadata before future evidence',()=>{
 const bars:Bar[]=Array.from({length:3},(_,i)=>({
  time:i*H,open:100,high:102,low:98,close:100,volume:0,observed_minutes:60,
 }));
 let tagReads=0;
 let futureReads=0;
 Object.defineProperty(bars,Symbol.toStringTag,{
  configurable:true,enumerable:false,
  get(){tagReads++;throw Error('toStringTag getter executed');},
 });
 Object.defineProperty(bars[2],'time',{
  configurable:true,enumerable:true,
  get(){futureReads++;throw Error('future timestamp getter executed');},
 });
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,2*H),
  /Unexpected FVG archive array metadata/);
 assert.equal(tagReads,0);
 assert.equal(futureReads,0);
});


// A non-enumerable data-valued display tag is not a JSON archive field.
// Validate the entire array shape before consulting unrevealed future bars.
test('full and as-of reject data-valued Symbol.toStringTag without future reads',async()=>{
 const {studyHourlyFvgMidpoint}=await import('../lib/hourly-fvg-midpoint-study.ts');
 const bars:Bar[]=Array.from({length:3},(_,i)=>({
  time:i*H,open:100,high:102,low:98,close:100,volume:0,observed_minutes:60,
 }));
 let futureReads=0;
 Object.defineProperty(bars,Symbol.toStringTag,{
  configurable:true,enumerable:false,value:'VerifiedBrokerBidArchive',
 });
 Object.defineProperty(bars[2],'time',{
  configurable:true,enumerable:true,
  get(){futureReads++;throw Error('future timestamp getter executed');},
 });
 assert.throws(()=>studyHourlyFvgMidpoint(bars,source),
  /Unexpected FVG archive array metadata/);
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,2*H),
  /Unexpected FVG archive array metadata/);
 assert.equal(futureReads,0);
});


// Array.prototype.slice can consult an own constructor / Symbol.species.
// Reject undeclared constructors before any caller code or future candle
// evidence is accessed; a synthetic subclass must not alter volume history.
test('full and as-of reject own constructor accessor before species or future reads',async()=>{
 const {studyHourlyFvgMidpoint}=await import('../lib/hourly-fvg-midpoint-study.ts');
 const bars:Bar[]=Array.from({length:3},(_,i)=>({
  time:i*H,open:100,high:102,low:98,close:100,volume:0,observed_minutes:60,
 }));
 let constructorReads=0;
 let futureReads=0;
 Object.defineProperty(bars,'constructor',{
  configurable:true,enumerable:false,
  get(){constructorReads++;throw Error('array species constructor executed');},
 });
 Object.defineProperty(bars[2],'time',{
  configurable:true,enumerable:true,
  get(){futureReads++;throw Error('unrevealed future timestamp executed');},
 });
 assert.throws(()=>studyHourlyFvgMidpoint(bars,source),
  /Unexpected FVG archive array metadata/);
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,2*H),
  /Unexpected FVG archive array metadata/);
 assert.equal(constructorReads,0);
 assert.equal(futureReads,0);
});
