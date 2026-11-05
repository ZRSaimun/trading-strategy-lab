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

// A data-valued constructor override is also an undeclared archive field.
// Do not allow Array species customization to influence causal prefix copying.
test('full and as-of reject own data-valued constructor before future reads',async()=>{
 const {studyHourlyFvgMidpoint}=await import('../lib/hourly-fvg-midpoint-study.ts');
 const bars:Bar[]=Array.from({length:3},(_,i)=>({
  time:i*H,open:100,high:102,low:98,close:100,volume:0,observed_minutes:60,
 }));
 let speciesReads=0;
 let futureReads=0;
 const customConstructor={
  get [Symbol.species](){speciesReads++;throw Error('species executed');},
 };
 Object.defineProperty(bars,'constructor',{
  configurable:true,enumerable:false,value:customConstructor,
 });
 Object.defineProperty(bars[2],'time',{
  configurable:true,enumerable:true,
  get(){futureReads++;throw Error('future timestamp executed');},
 });
 assert.throws(()=>studyHourlyFvgMidpoint(bars,source),
  /Unexpected FVG archive array metadata/);
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,2*H),
  /Unexpected FVG archive array metadata/);
 assert.equal(speciesReads,0);
 assert.equal(futureReads,0);
});


// A caller-defined serializer could substitute unverified price/volume evidence
// when the archive is exported. The JSON-array contract forbids this metadata.
test('full and as-of reject archive toJSON getter before future timestamps',async()=>{
 const {studyHourlyFvgMidpoint}=await import('../lib/hourly-fvg-midpoint-study.ts');
 const bars:Bar[]=Array.from({length:3},(_,i)=>({
  time:i*H,open:100,high:102,low:98,close:100,volume:0,observed_minutes:60,
 }));
 let serializerReads=0;
 let futureReads=0;
 Object.defineProperty(bars,'toJSON',{
  configurable:true,enumerable:false,
  get(){serializerReads++;throw Error('archive serializer executed');},
 });
 Object.defineProperty(bars[2],'time',{
  configurable:true,enumerable:true,
  get(){futureReads++;throw Error('future timestamp executed');},
 });
 assert.throws(()=>studyHourlyFvgMidpoint(bars,source),
  /Unexpected FVG archive array metadata/);
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,2*H),
  /Unexpected FVG archive array metadata/);
 assert.equal(serializerReads,0);
 assert.equal(futureReads,0);
});


// A malformed *future* hourly timestamp is permitted to be inspected only as
// timestamp metadata, never as a reason to access unrevealed prices or volume.
// Negative zero is rejected rather than silently normalized to epoch zero.
test('as-of rejects negative-zero future time without reading future OHLC or volume',()=>{
 const bars:Bar[]=Array.from({length:3},(_,i)=>({
  time:i*H,open:100,high:102,low:98,close:100,volume:1,observed_minutes:60,
 }));
 let futurePriceReads=0;
 for(const field of ['open','high','low','close','volume'] as const){
  Object.defineProperty(bars[2],field,{
   configurable:true,enumerable:true,
   get(){futurePriceReads++;throw Error('unrevealed future price or volume accessed');},
  });
 }
 bars[2].time=-0;
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,H),
  /negative.zero|timestamp|time|invalid/i);
 assert.equal(futurePriceReads,0);
});

// A future row's timestamp is allowable structural metadata, but an invalid
// non-finite value must never authorize inspecting unrevealed OHLC or volume.
// Each case uses a fresh archive so one rejection cannot mask another.
test('as-of rejects non-finite future timestamps without future price access',()=>{
 for(const badTime of [Number.NaN,Number.POSITIVE_INFINITY,Number.NEGATIVE_INFINITY]){
  const bars:Bar[]=Array.from({length:3},(_,i)=>({
   time:i*H,open:100,high:102,low:98,close:100,volume:1,observed_minutes:60,
  }));
  let futureReads=0;
  for(const field of ['open','high','low','close','volume'] as const){
   Object.defineProperty(bars[2],field,{
    configurable:true,enumerable:true,
    get(){futureReads++;throw Error('future OHLC/volume accessed');},
   });
  }
  bars[2].time=badTime;
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,H),
   /Invalid or unordered hourly as-of input timestamp/);
  assert.equal(futureReads,0,'invalid future timestamp must not expose prices');
 }
});


// A future fractional hour is invalid timestamp metadata, not a reason to
// inspect unrevealed prices. Keep this separate from non-finite/negative-zero.
test('as-of rejects fractional future hour without reading future OHLC or volume',()=>{
 const bars:Bar[]=Array.from({length:3},(_,i)=>({
  time:i*H,open:100,high:102,low:98,close:100,volume:1,observed_minutes:60,
 }));
 let futureReads=0;
 for(const field of ['open','high','low','close','volume'] as const){
  Object.defineProperty(bars[2],field,{
   configurable:true,enumerable:true,
   get(){futureReads++;throw Error('future price evidence accessed');},
  });
 }
 bars[2].time=2*H+0.5;
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,H),
  /Invalid or unordered hourly as-of input timestamp/);
 assert.equal(futureReads,0);
});


// A representable multiple of one hour can still exceed JavaScript's safe
// integer timestamp range. It must fail before any unrevealed OHLC is read.
test('as-of rejects unsafe-integer future hour without reading future prices',()=>{
 const bars:Bar[]=Array.from({length:3},(_,i)=>({
  time:i*H,open:100,high:102,low:98,close:100,volume:1,observed_minutes:60,
 }));
 let futureReads=0;
 for(const field of ['open','high','low','close','volume'] as const){
  Object.defineProperty(bars[2],field,{
   configurable:true,enumerable:true,
   get(){futureReads++;throw Error('future price evidence accessed');},
  });
 }
 bars[2].time=(Math.floor(Number.MAX_SAFE_INTEGER/H)+1)*H;
 assert.equal(Number.isSafeInteger(bars[2].time),false);
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,H),
  /Invalid or unordered hourly as-of input timestamp/);
 assert.equal(futureReads,0);
});


// Malformed future timestamp types must be rejected without coercion or
// access to the future candle's price/volume evidence. BigInt is especially
// important: arithmetic coercion can throw before the intended validation.
test('as-of rejects non-number future timestamps without future OHLC reads',()=>{
 for(const badTime of ['7200',7200n,null,undefined]){
  const bars:Bar[]=Array.from({length:3},(_,i)=>({
   time:i*H,open:100,high:102,low:98,close:100,volume:1,observed_minutes:60,
  }));
  let futureReads=0;
  for(const field of ['open','high','low','close','volume'] as const){
   Object.defineProperty(bars[2],field,{
    configurable:true,enumerable:true,
    get(){futureReads++;throw Error('future evidence accessed');},
   });
  }
  (bars[2] as unknown as {time:unknown}).time=badTime;
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,H),
   /Invalid or unordered hourly as-of input timestamp/);
  assert.equal(futureReads,0,'future prices must remain unread for malformed timestamp types');
 }
});


// A caller-supplied object timestamp may advertise a valid hour through
// valueOf / Symbol.toPrimitive. Never coerce it or inspect future evidence.
test('as-of rejects coercible future timestamp objects without invoking caller code',()=>{
 for(const primitive of ['valueOf',Symbol.toPrimitive] as const){
  const bars:Bar[]=Array.from({length:3},(_,i)=>({
   time:i*H,open:100,high:102,low:98,close:100,volume:1,observed_minutes:60,
  }));
  let coercions=0;
  let futureReads=0;
  const fakeTime=Object.create(null) as Record<PropertyKey,unknown>;
  Object.defineProperty(fakeTime,primitive,{
   get(){coercions++;throw Error('timestamp coercion getter executed');},
  });
  for(const field of ['open','high','low','close','volume'] as const){
   Object.defineProperty(bars[2],field,{
    configurable:true,enumerable:true,
    get(){futureReads++;throw Error('future OHLC/volume accessed');},
   });
  }
  (bars[2] as unknown as {time:unknown}).time=fakeTime;
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,H),
   /Invalid or unordered hourly as-of input timestamp/);
  assert.equal(coercions,0,'timestamp must not be coerced');
  assert.equal(futureReads,0,'unrevealed future evidence must stay unread');
 }
});


// Boolean and Symbol timestamps cannot be interpreted as UTC hours. In
// particular, Symbol arithmetic must not throw an unrelated coercion error.
test('as-of rejects boolean and symbol future hours before future price access',()=>{
 for(const badTime of [false,true,Symbol('future-hour')]){
  const bars:Bar[]=Array.from({length:3},(_,i)=>({
   time:i*H,open:100,high:102,low:98,close:100,volume:1,observed_minutes:60,
  }));
  let futureReads=0;
  for(const field of ['open','high','low','close','volume'] as const){
   Object.defineProperty(bars[2],field,{
    configurable:true,enumerable:true,
    get(){futureReads++;throw Error('unrevealed future price accessed');},
   });
  }
  (bars[2] as unknown as {time:unknown}).time=badTime;
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,H),
   /Invalid or unordered hourly as-of input timestamp/);
  assert.equal(futureReads,0);
 }
});


// Duplicate future UTC buckets must not be silently deduplicated into a
// plausible causal prefix; timestamps are inspectable, future prices are not.
test('as-of rejects duplicate future hourly timestamp without reading future prices',()=>{
 const bars:Bar[]=Array.from({length:3},(_,i)=>({
  time:i*H,open:100,high:102,low:98,close:100,volume:1,observed_minutes:60,
 }));
 let futureReads=0;
 for(const field of ['open','high','low','close','volume'] as const){
  Object.defineProperty(bars[2],field,{
   configurable:true,enumerable:true,
   get(){futureReads++;throw Error('unrevealed future OHLC/volume accessed');},
  });
 }
 bars[2].time=H; // duplicate of the preceding, completed hourly bucket
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,H),
  /Invalid or unordered hourly as-of input timestamp/);
 assert.equal(futureReads,0);
});


// Out-of-order future metadata can make an older completed candle appear
// beyond the as-of cutoff. Reject it before reading that candle's prices.
test('as-of rejects descending distinct future hourly buckets without future OHLC reads',()=>{
 const bars:Bar[]=Array.from({length:4},(_,i)=>({
  time:i*H,open:100,high:102,low:98,close:100,volume:1,observed_minutes:60,
 }));
 let futureReads=0;
 for(const field of ['open','high','low','close','volume'] as const){
  Object.defineProperty(bars[3],field,{
   configurable:true,enumerable:true,
   get(){futureReads++;throw Error('unrevealed future evidence accessed');},
  });
 }
 bars[2].time=4*H;
 bars[3].time=3*H; // distinct and aligned, but descends from the prior bucket
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,H),
  /Invalid or unordered hourly as-of input timestamp/);
 assert.equal(futureReads,0);
});


// A valid archive may contain later hourly timestamps. An as-of scan must
// succeed using only completed rows, not merely avoid future reads on errors.
test('as-of accepts ordered future hours without reading future evidence fields',()=>{
 const bars:Bar[]=Array.from({length:4},(_,i)=>({
  time:i*H,open:100,high:102,low:98,close:100,volume:1,observed_minutes:60,
 }));
 let unrevealedReads=0;
 for(const row of bars.slice(2)){
  for(const field of ['open','high','low','close','volume','observed_minutes'] as const){
   Object.defineProperty(row,field,{
    configurable:true,enumerable:true,
    get(){unrevealedReads++;throw Error('unrevealed future evidence accessed');},
   });
  }
 }
 assert.doesNotThrow(()=>studyHourlyFvgMidpointAsOf(bars,source,2*H));
 assert.equal(unrevealedReads,0);
});


// An omitted future hourly bucket is a source-coverage gap, not permission
// to peek at later OHLC/volume. Timestamp-only preflight must still accept
// ordered, aligned future metadata; the completed as-of prefix is unchanged.
test('as-of accepts ordered gapped future timestamps without future evidence reads',()=>{
 const bars:Bar[]=Array.from({length:4},(_,i)=>({
  time:i*H,open:100,high:102,low:98,close:100,volume:1,observed_minutes:60,
 }));
 bars[2].time=4*H; // 2H and 3H are absent from the archive
 bars[3].time=7*H; // 5H and 6H are also absent
 let futureReads=0;
 for(const row of bars.slice(2)){
  for(const field of ['open','high','low','close','volume','observed_minutes'] as const){
   Object.defineProperty(row,field,{
    configurable:true,enumerable:true,
    get(){futureReads++;throw Error('future price/volume/coverage accessed');},
   });
  }
 }
 const prefix=bars.slice(0,2);
 const expected=studyHourlyFvgMidpointAsOf(prefix,source,2*H);
 const actual=studyHourlyFvgMidpointAsOf(bars,source,2*H);
 assert.deepEqual(actual,expected,'future timestamp gaps cannot change as-of result');
 assert.equal(futureReads,0,'future market evidence must remain unread');
});
