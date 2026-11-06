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


// A future timestamp accessor is permitted only to reveal its own UTC hour.
// Its unrevealed price, volume and coverage properties must remain untouched.
test('as-of reads a valid future hour getter once but never its market evidence',()=>{
 const bars:Bar[]=Array.from({length:4},(_,i)=>({
  time:i*H,open:100,high:102,low:98,close:100,volume:1,observed_minutes:60,
 }));
 let timestampReads=0;
 let futureEvidenceReads=0;
 for(const row of bars.slice(2)){
  const hour=row.time;
  Object.defineProperty(row,'time',{
   configurable:true,enumerable:true,
   get(){timestampReads++;return hour;},
  });
  for(const field of ['open','high','low','close','volume','observed_minutes'] as const){
   Object.defineProperty(row,field,{
    configurable:true,enumerable:true,
    get(){futureEvidenceReads++;throw Error('future market evidence accessed');},
   });
  }
 }
 const expected=studyHourlyFvgMidpointAsOf(bars.slice(0,2),source,2*H);
 const actual=studyHourlyFvgMidpointAsOf(bars,source,2*H);
 assert.deepEqual(actual,expected,'future metadata must not change completed-prefix study');
 assert.equal(timestampReads,2,'each future timestamp should be read once');
 assert.equal(futureEvidenceReads,0,'unrevealed future market evidence must remain unread');
});


// A nonempty completed prefix must retain an actual formed FVG when later
// timestamps are inspected. Flat-prefix tests alone cannot catch a regression
// that accidentally discards valid formations while avoiding future reads.
test('as-of retains completed bullish FVG with unread future market evidence',()=>{
 const bars:Bar[]=[
  {time:0,open:99,high:100,low:98,close:99,volume:1,observed_minutes:60},
  {time:H,open:101,high:104,low:100,close:103,volume:1,observed_minutes:60},
  {time:2*H,open:103,high:105,low:102,close:104,volume:1,observed_minutes:60},
  {time:3*H,open:104,high:106,low:101,close:103,volume:1,observed_minutes:60},
  {time:4*H,open:103,high:105,low:100,close:102,volume:1,observed_minutes:60},
 ];
 let futureReads=0;
 for(const row of bars.slice(3)){
  for(const field of ['open','high','low','close','volume','observed_minutes'] as const){
   Object.defineProperty(row,field,{
    configurable:true,enumerable:true,
    get(){futureReads++;throw Error('future evidence accessed');},
   });
  }
 }
 const expected=studyHourlyFvgMidpointAsOf(bars.slice(0,3),source,3*H);
 const actual=studyHourlyFvgMidpointAsOf(bars,source,3*H);
 assert.ok(expected.observations.some(o=>
  o.direction==='BULLISH' && o.formationClosedAt===3*H),
  'fixture must contain a real completed bullish gap');
 assert.deepEqual(actual,expected,'future candles cannot erase completed formation');
 assert.equal(futureReads,0);
});


// Mirror the bullish completed-formation replay with a bearish gap. A
// direction-specific refactor must not let future candles create or erase
// the already closed bearish formation at the as-of boundary.
test('as-of retains completed bearish FVG with unread future market evidence',()=>{
 const bars:Bar[]=[
  {time:0,open:105,high:106,low:104,close:105,volume:1,observed_minutes:60},
  {time:H,open:103,high:104,low:100,close:101,volume:1,observed_minutes:60},
  {time:2*H,open:100,high:102,low:98,close:99,volume:1,observed_minutes:60},
  {time:3*H,open:99,high:103,low:97,close:101,volume:1,observed_minutes:60},
  {time:4*H,open:101,high:105,low:99,close:104,volume:1,observed_minutes:60},
 ];
 let futureReads=0;
 for(const row of bars.slice(3)){
  for(const field of ['open','high','low','close','volume','observed_minutes'] as const){
   Object.defineProperty(row,field,{
    configurable:true,enumerable:true,
    get(){futureReads++;throw Error('future evidence accessed');},
   });
  }
 }
 const expected=studyHourlyFvgMidpointAsOf(bars.slice(0,3),source,3*H);
 const actual=studyHourlyFvgMidpointAsOf(bars,source,3*H);
 assert.ok(expected.observations.some(o=>
  o.direction==='BEARISH' && o.formationClosedAt===3*H),
  'fixture must contain a real completed bearish gap');
 assert.deepEqual(actual,expected,'future candles cannot erase completed bearish formation');
 assert.equal(futureReads,0);
});


// Formation at 3H must not appear at the 2H decision boundary, even when
// its final candle has a valid timestamp and a tempting bullish gap.
test('as-of does not form a three-hour FVG before the third bar closes',()=>{
 const bars:Bar[]=[
  {time:0,open:99,high:100,low:98,close:99,volume:1,observed_minutes:60},
  {time:H,open:101,high:104,low:100,close:103,volume:1,observed_minutes:60},
  {time:2*H,open:103,high:105,low:102,close:104,volume:1,observed_minutes:60},
 ];
 let futureReads=0;
 for(const field of ['open','high','low','close','volume','observed_minutes'] as const){
  Object.defineProperty(bars[2],field,{
   configurable:true,enumerable:true,
   get(){futureReads++;throw Error('unclosed formation evidence accessed');},
  });
 }
 const before=studyHourlyFvgMidpointAsOf(bars,source,2*H);
 const prefix=studyHourlyFvgMidpointAsOf(bars.slice(0,2),source,2*H);
 assert.deepEqual(before,prefix,'unclosed third candle cannot form a gap');
 assert.equal(before.observations.length,0);
 assert.equal(futureReads,0,'third candle OHLC/volume/coverage must remain unread');
});


// Bearish formations obey the same third-candle close boundary as bullish
// ones. The future candle's timestamp may be inspected, but not its evidence.
test('as-of does not form bearish FVG before third hourly bar closes',()=>{
 const bars:Bar[]=[
  {time:0,open:105,high:106,low:104,close:105,volume:1,observed_minutes:60},
  {time:H,open:103,high:104,low:100,close:101,volume:1,observed_minutes:60},
  {time:2*H,open:100,high:102,low:98,close:99,volume:1,observed_minutes:60},
 ];
 let futureReads=0;
 for(const field of ['open','high','low','close','volume','observed_minutes'] as const){
  Object.defineProperty(bars[2],field,{
   configurable:true,enumerable:true,
   get(){futureReads++;throw Error('unclosed bearish candle evidence accessed');},
  });
 }
 const before=studyHourlyFvgMidpointAsOf(bars,source,2*H);
 const prefix=studyHourlyFvgMidpointAsOf(bars.slice(0,2),source,2*H);
 assert.deepEqual(before,prefix,'unclosed bearish third candle cannot form a gap');
 assert.equal(before.observations.length,0);
 assert.equal(futureReads,0,'future OHLC, volume and coverage must remain unread');
});


// Only aligned hourly decision times are accepted: a one-second-early
// request fails closed, and the last valid boundary has two closed bars.
// The third candle becomes eligible at exactly 3H.
test('as-of bullish formation transitions only at exact third-hour close',()=>{
 const bars:Bar[]=[
  {time:0,open:99,high:100,low:98,close:99,volume:1,observed_minutes:60},
  {time:H,open:101,high:104,low:100,close:103,volume:1,observed_minutes:60},
  {time:2*H,open:103,high:105,low:102,close:104,volume:1,observed_minutes:60},
 ];
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,3*H-1),
  /Invalid UTC hourly as-of close/,
  'intrahour decisions must fail closed instead of rounding forward');
 const before=studyHourlyFvgMidpointAsOf(bars,source,2*H);
 const prefix=studyHourlyFvgMidpointAsOf(bars.slice(0,2),source,2*H);
 assert.deepEqual(before,prefix,'a nearly closed bar is still unrevealed');
 assert.equal(before.observations.length,0);
 const atClose=studyHourlyFvgMidpointAsOf(bars,source,3*H);
 assert.ok(atClose.observations.some(o=>
  o.direction==='BULLISH' && o.formationClosedAt===3*H),
  'formation first becomes eligible at the exact close');
});


// The bearish direction must obey the same aligned decision-time contract:
// no third-bar formation at 2H, and eligibility only once 3H has closed.
test('as-of bearish formation transitions only at exact third-hour close',()=>{
 const bars:Bar[]=[
  {time:0,open:105,high:106,low:104,close:105,volume:1,observed_minutes:60},
  {time:H,open:103,high:104,low:100,close:101,volume:1,observed_minutes:60},
  {time:2*H,open:100,high:102,low:98,close:99,volume:1,observed_minutes:60},
 ];
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,3*H-1),
  /Invalid UTC hourly as-of close/,
  'an intrahour decision must fail closed rather than round to the next hour');
 const before=studyHourlyFvgMidpointAsOf(bars,source,2*H);
 const prefix=studyHourlyFvgMidpointAsOf(bars.slice(0,2),source,2*H);
 assert.deepEqual(before,prefix,'the bearish third candle is not yet completed');
 assert.equal(before.observations.length,0);
 const atClose=studyHourlyFvgMidpointAsOf(bars,source,3*H);
 assert.ok(atClose.observations.some(o=>
  o.direction==='BEARISH' && o.formationClosedAt===3*H),
  'bearish gap first becomes eligible at the exact close');
});


// A midpoint intersection on the first post-formation bar is knowable only
// after that bar closes. Formation itself cannot count as a first touch.
test('as-of first midpoint touch waits for next completed hour',()=>{
 const bars:Bar[]=[
  {time:0,open:99,high:100,low:98,close:99,volume:1,observed_minutes:60},
  {time:H,open:101,high:104,low:100,close:103,volume:1,observed_minutes:60},
  {time:2*H,open:103,high:105,low:102,close:104,volume:1,observed_minutes:60},
  {time:3*H,open:103,high:104,low:100,close:102,volume:1,observed_minutes:60},
 ];
 let futureReads=0;
 for(const field of ['open','high','low','close','volume','observed_minutes'] as const){
  Object.defineProperty(bars[3],field,{
   configurable:true,enumerable:true,
   get(){futureReads++;throw Error('unclosed touch bar accessed');},
  });
 }
 const formation=studyHourlyFvgMidpointAsOf(bars,source,3*H);
 assert.equal(formation.observations.length,1);
 assert.equal(formation.observations[0].firstTouchOutcome,'INCOMPLETE_WINDOW');
 assert.equal(formation.observations[0].firstTouchClosedAt,null);
 assert.equal(futureReads,0);
 const completed=bars.slice(0,3).concat([
  {time:3*H,open:103,high:104,low:100,close:102,volume:1,observed_minutes:60},
 ]);
 const touched=studyHourlyFvgMidpointAsOf(completed,source,4*H);
 assert.equal(touched.observations.length,1);
 assert.equal(touched.observations[0].firstTouchOutcome,'TOUCH');
 assert.equal(touched.observations[0].firstTouchClosedAt,4*H);
 assert.equal(touched.observations[0].firstTouchOutcomeObservedAt,4*H);
});


// A bearish midpoint touch on the first post-formation candle must not be
// inferred from its timestamp or from an unclosed candle's high/low.
// The same exact-close rule applies to both FVG directions.
test('as-of bearish first midpoint touch waits for next completed hour',()=>{
 const bars:Bar[]=[
  {time:0,open:105,high:106,low:104,close:105,volume:1,observed_minutes:60},
  {time:H,open:103,high:104,low:100,close:101,volume:1,observed_minutes:60},
  {time:2*H,open:100,high:102,low:98,close:99,volume:1,observed_minutes:60},
  {time:3*H,open:103,high:104,low:102,close:103,volume:1,observed_minutes:60},
 ];
 let futureReads=0;
 for(const field of ['open','high','low','close','volume','observed_minutes'] as const){
  Object.defineProperty(bars[3],field,{
   configurable:true,enumerable:true,
   get(){futureReads++;throw Error('unclosed bearish touch evidence accessed');},
  });
 }
 const formation=studyHourlyFvgMidpointAsOf(bars,source,3*H);
 assert.equal(formation.observations.length,1);
 assert.equal(formation.observations[0].direction,'BEARISH');
 assert.equal(formation.observations[0].firstTouchOutcome,'INCOMPLETE_WINDOW');
 assert.equal(formation.observations[0].firstTouchClosedAt,null);
 assert.equal(futureReads,0,'unclosed bearish touch evidence must remain unread');
 const completed=bars.slice(0,3).concat([
  {time:3*H,open:103,high:104,low:102,close:103,volume:1,observed_minutes:60},
 ]);
 const touched=studyHourlyFvgMidpointAsOf(completed,source,4*H);
 assert.equal(touched.observations.length,1);
 assert.equal(touched.observations[0].direction,'BEARISH');
 assert.equal(touched.observations[0].firstTouchOutcome,'TOUCH');
 assert.equal(touched.observations[0].firstTouchClosedAt,4*H);
 assert.equal(touched.observations[0].firstTouchOutcomeObservedAt,4*H);
});


// A completed post-formation candle that stays above the bullish midpoint
// must not be mistaken for a touch. A later completed candle can first touch,
// but its timestamp must not leak into an earlier as-of decision.
test('as-of bullish first touch skips completed no-touch bar without lookahead',()=>{
 const bars:Bar[]=[
  {time:0,open:99,high:100,low:98,close:99,volume:1,observed_minutes:60},
  {time:H,open:101,high:104,low:100,close:103,volume:1,observed_minutes:60},
  {time:2*H,open:103,high:105,low:102,close:104,volume:1,observed_minutes:60},
  {time:3*H,open:104,high:106,low:103,close:105,volume:1,observed_minutes:60},
  {time:4*H,open:104,high:105,low:100,close:102,volume:1,observed_minutes:60},
 ];
 let futureReads=0;
 for(const field of ['open','high','low','close','volume','observed_minutes'] as const){
  Object.defineProperty(bars[4],field,{
   configurable:true,enumerable:true,
   get(){futureReads++;throw Error('later touch evidence accessed early');},
  });
 }
 const atFour=studyHourlyFvgMidpointAsOf(bars,source,4*H);
 const prefix=studyHourlyFvgMidpointAsOf(bars.slice(0,4),source,4*H);
 assert.deepEqual(atFour,prefix);
 assert.equal(atFour.observations.length,1);
 assert.equal(atFour.observations[0].firstTouchOutcome,'INCOMPLETE_WINDOW');
 assert.equal(atFour.observations[0].firstTouchClosedAt,null);
 assert.equal(futureReads,0);
 const completed=bars.slice(0,4).concat([
  {time:4*H,open:104,high:105,low:100,close:102,volume:1,observed_minutes:60},
 ]);
 const atFive=studyHourlyFvgMidpointAsOf(completed,source,5*H);
 assert.equal(atFive.observations.length,1);
 assert.equal(atFive.observations[0].firstTouchOutcome,'TOUCH');
 assert.equal(atFive.observations[0].firstTouchClosedAt,5*H);
 assert.equal(atFive.observations[0].firstTouchOutcomeObservedAt,5*H);
});


// A completed bearish post-formation candle below the midpoint is not a
// touch. A later candle may touch only when its own hourly close is revealed.
test('as-of bearish first touch skips completed no-touch bar without lookahead',()=>{
 const bars:Bar[]=[
  {time:0,open:105,high:106,low:104,close:105,volume:1,observed_minutes:60},
  {time:H,open:103,high:104,low:100,close:101,volume:1,observed_minutes:60},
  {time:2*H,open:100,high:102,low:98,close:99,volume:1,observed_minutes:60},
  {time:3*H,open:99,high:101,low:97,close:100,volume:1,observed_minutes:60},
  {time:4*H,open:101,high:104,low:100,close:103,volume:1,observed_minutes:60},
 ];
 let futureReads=0;
 for(const field of ['open','high','low','close','volume','observed_minutes'] as const){
  Object.defineProperty(bars[4],field,{
   configurable:true,enumerable:true,
   get(){futureReads++;throw Error('later bearish touch evidence accessed early');},
  });
 }
 const atFour=studyHourlyFvgMidpointAsOf(bars,source,4*H);
 const prefix=studyHourlyFvgMidpointAsOf(bars.slice(0,4),source,4*H);
 assert.deepEqual(atFour,prefix);
 assert.equal(atFour.observations.length,1);
 assert.equal(atFour.observations[0].direction,'BEARISH');
 assert.equal(atFour.observations[0].firstTouchOutcome,'INCOMPLETE_WINDOW');
 assert.equal(atFour.observations[0].firstTouchClosedAt,null);
 assert.equal(futureReads,0);
 const completed=bars.slice(0,4).concat([
  {time:4*H,open:101,high:104,low:100,close:103,volume:1,observed_minutes:60},
 ]);
 const atFive=studyHourlyFvgMidpointAsOf(completed,source,5*H);
 assert.equal(atFive.observations.length,1);
 assert.equal(atFive.observations[0].direction,'BEARISH');
 assert.equal(atFive.observations[0].firstTouchOutcome,'TOUCH');
 assert.equal(atFive.observations[0].firstTouchClosedAt,5*H);
 assert.equal(atFive.observations[0].firstTouchOutcomeObservedAt,5*H);
});


// Missing completed hourly intervals are not evidence of a first touch.
// A later candle that spans the midpoint cannot repair the missing hour.
test('as-of refuses first-touch inference across a missing hourly candle',()=>{
 const bars:Bar[]=[
  {time:0,open:99,high:100,low:98,close:99,volume:1,observed_minutes:60},
  {time:H,open:101,high:104,low:100,close:103,volume:1,observed_minutes:60},
  {time:2*H,open:103,high:105,low:102,close:104,volume:1,observed_minutes:60},
  // No bar starting at 3H: the first post-formation hour is unobserved.
  {time:4*H,open:104,high:105,low:100,close:102,volume:1,observed_minutes:60},
 ];
 const result=studyHourlyFvgMidpointAsOf(bars,source,5*H);
 assert.equal(result.observations.length,1);
 assert.equal(result.observations[0].direction,'BULLISH');
 assert.equal(result.observations[0].firstTouchOutcome,'INCOMPLETE_WINDOW');
 assert.equal(result.observations[0].firstTouchClosedAt,null,
  'later midpoint intersection cannot bypass missing first eligible hour');
});


// Missing first eligible bearish hour cannot be reconstructed from a later
// midpoint intersection. No fabricated candle or first-touch timestamp.
test('as-of bearish first touch remains unknown across a missing hour',()=>{
 const bars:Bar[]=[
  {time:0,open:105,high:106,low:104,close:105,volume:1,observed_minutes:60},
  {time:H,open:103,high:104,low:100,close:101,volume:1,observed_minutes:60},
  {time:2*H,open:100,high:102,low:98,close:99,volume:1,observed_minutes:60},
  // Missing 3H–4H first eligible candle.
  {time:4*H,open:101,high:104,low:100,close:103,volume:1,observed_minutes:60},
 ];
 const result=studyHourlyFvgMidpointAsOf(bars,source,5*H);
 assert.equal(result.observations.length,1);
 assert.equal(result.observations[0].direction,'BEARISH');
 assert.equal(result.observations[0].firstTouchOutcome,'INCOMPLETE_WINDOW');
 assert.equal(result.observations[0].firstTouchClosedAt,null);
});


// A missing third formation hour cannot be replaced by a later candle with
// matching gap prices. Formation requires three consecutive completed hours.
test('as-of refuses bullish FVG formation across a missing third hour',()=>{
 const bars:Bar[]=[
  {time:0,open:99,high:100,low:98,close:99,volume:1,observed_minutes:60},
  {time:H,open:101,high:104,low:100,close:103,volume:1,observed_minutes:60},
  // Missing 2H–3H. The next observed candle is NOT the third consecutive hour.
  {time:3*H,open:103,high:105,low:102,close:104,volume:1,observed_minutes:60},
 ];
 const atThree=studyHourlyFvgMidpointAsOf(bars,source,3*H);
 assert.equal(atThree.observations.length,0,'missing third hour cannot form a gap');
 const atFour=studyHourlyFvgMidpointAsOf(bars,source,4*H);
 assert.equal(atFour.observations.length,0,'later prices cannot bridge the gap');
});


// Bearish formation requires the same three contiguous completed hours as
// bullish formation. A later lower-low candle cannot replace the missing 2H.
test('as-of refuses bearish FVG formation across a missing third hour',()=>{
 const bars:Bar[]=[
  {time:0,open:105,high:106,low:104,close:105,volume:1,observed_minutes:60},
  {time:H,open:103,high:104,low:100,close:101,volume:1,observed_minutes:60},
  // No 2H–3H bar; the lower candle at 3H is not a consecutive third bar.
  {time:3*H,open:100,high:102,low:98,close:99,volume:1,observed_minutes:60},
 ];
 const atThree=studyHourlyFvgMidpointAsOf(bars,source,3*H);
 assert.equal(atThree.observations.length,0,'unobserved third hour cannot form a bearish gap');
 const atFour=studyHourlyFvgMidpointAsOf(bars,source,4*H);
 assert.equal(atFour.observations.length,0,'later bearish prices cannot bridge missing formation evidence');
});


// A missing middle formation hour must not be silently replaced by a later
// third candle. This tests a distinct gap position from missing third hour.
test('as-of refuses bullish and bearish FVG formation across missing middle hour',()=>{
 for(const direction of ['BULLISH','BEARISH'] as const){
  const bars:Bar[]=direction==='BULLISH' ? [
   {time:0,open:99,high:100,low:98,close:99,volume:1,observed_minutes:60},
   {time:2*H,open:101,high:104,low:100,close:103,volume:1,observed_minutes:60},
   {time:3*H,open:103,high:105,low:102,close:104,volume:1,observed_minutes:60},
  ] : [
   {time:0,open:105,high:106,low:104,close:105,volume:1,observed_minutes:60},
   {time:2*H,open:103,high:104,low:100,close:101,volume:1,observed_minutes:60},
   {time:3*H,open:100,high:102,low:98,close:99,volume:1,observed_minutes:60},
  ];
  assert.equal(studyHourlyFvgMidpointAsOf(bars,source,3*H).observations.length,0);
  assert.equal(studyHourlyFvgMidpointAsOf(bars,source,4*H).observations.length,0,
   direction+' missing middle hour must not be bridged by later price evidence');
 }
});


// The first eligible midpoint touch is evidence only after the whole 1H
// candle closes, including the final millisecond of that candle.
test('as-of bullish and bearish midpoint touch requires completed UTC hour boundary',()=>{
 for(const direction of ['BULLISH','BEARISH'] as const){
  const bars:Bar[]=direction==='BULLISH' ? [
   {time:0,open:99,high:100,low:98,close:99,volume:1,observed_minutes:60},
   {time:H,open:101,high:104,low:100,close:103,volume:1,observed_minutes:60},
   {time:2*H,open:103,high:105,low:102,close:104,volume:1,observed_minutes:60},
   {time:3*H,open:104,high:105,low:100,close:102,volume:1,observed_minutes:60},
  ] : [
   {time:0,open:105,high:106,low:104,close:105,volume:1,observed_minutes:60},
   {time:H,open:103,high:104,low:100,close:101,volume:1,observed_minutes:60},
   {time:2*H,open:100,high:102,low:98,close:99,volume:1,observed_minutes:60},
   {time:3*H,open:103,high:104,low:102,close:103,volume:1,observed_minutes:60},
  ];
  // As-of boundaries are completed UTC hours, never intra-hour instants.
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,4*H-1),/Invalid UTC hourly as-of close/);
  const before=studyHourlyFvgMidpointAsOf(bars,source,3*H);
  const prefix=studyHourlyFvgMidpointAsOf(bars.slice(0,3),source,3*H);
  assert.deepEqual(before,prefix,direction+' pre-close result must equal revealed prefix');
  assert.equal(before.observations.length,1);
  assert.equal(before.observations[0].firstTouchOutcome,'INCOMPLETE_WINDOW');
  assert.equal(before.observations[0].firstTouchClosedAt,null);
  const closed=studyHourlyFvgMidpointAsOf(bars,source,4*H);
  assert.equal(closed.observations.length,1);
  assert.equal(closed.observations[0].direction,direction);
  assert.equal(closed.observations[0].firstTouchOutcome,'TOUCH');
  assert.equal(closed.observations[0].firstTouchClosedAt,4*H);
  assert.equal(closed.observations[0].firstTouchOutcomeObservedAt,4*H);
 }
});


// A midpoint touch uses the observed wick, not a rounded display price.
// Just-missing completed wicks remain unconfirmed; exact boundary intersection
// is eligible only at that candle's close, in both directional variants.
test('as-of midpoint wick threshold is inclusive without rounding near misses',()=>{
 for(const direction of ['BULLISH','BEARISH'] as const){
  const formation:Bar[]=direction==='BULLISH' ? [
   {time:0,open:99,high:100,low:98,close:99,volume:1,observed_minutes:60},
   {time:H,open:101,high:104,low:100,close:103,volume:1,observed_minutes:60},
   {time:2*H,open:103,high:105,low:102,close:104,volume:1,observed_minutes:60},
  ] : [
   {time:0,open:105,high:106,low:104,close:105,volume:1,observed_minutes:60},
   {time:H,open:103,high:104,low:100,close:101,volume:1,observed_minutes:60},
   {time:2*H,open:100,high:102,low:98,close:99,volume:1,observed_minutes:60},
  ];
  const wick:Bar=direction==='BULLISH'
   ? {time:3*H,open:103,high:104,low:101.01,close:103,volume:1,observed_minutes:60}
   : {time:3*H,open:101,high:102.99,low:100,close:101,volume:1,observed_minutes:60};
  const missed=studyHourlyFvgMidpointAsOf([...formation,wick],source,4*H);
  assert.equal(missed.observations.length,1);
  assert.equal(missed.observations[0].firstTouchOutcome,'INCOMPLETE_WINDOW',
   direction+' near-miss wick must not be rounded to a midpoint touch');
  assert.equal(missed.observations[0].firstTouchClosedAt,null);
  const exact={...wick,...(direction==='BULLISH'?{low:101}:{high:103})};
  const touched=studyHourlyFvgMidpointAsOf([...formation,exact],source,4*H);
  assert.equal(touched.observations.length,1);
  assert.equal(touched.observations[0].direction,direction);
  assert.equal(touched.observations[0].firstTouchOutcome,'TOUCH');
  assert.equal(touched.observations[0].firstTouchClosedAt,4*H);
  assert.equal(touched.observations[0].firstTouchOutcomeObservedAt,4*H);
 }
});
