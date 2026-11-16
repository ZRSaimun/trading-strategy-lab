import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic as-of preflight regression; not market-source or profitability evidence.
test('invalid as-of close rejects before touching any archive or source getter',()=>{
 const source=Object.defineProperty({},'datasetId',{
  get(){throw Error('source getter must not run');},enumerable:true,
 }) as FvgSource;
 const bars=new Proxy([] as Bar[],{
  get(){throw Error('archive getter must not run');},
  getOwnPropertyDescriptor(){throw Error('archive descriptor must not run');},
  ownKeys(){throw Error('archive keys must not be read');},
 });
 const invalid=[-0,0,-3600,3600.5,NaN,Infinity,-Infinity,
  Date.UTC(2100,0,1,1)/1000,Date.UTC(2026,10,1,6)/1000+1];
 for(const cutoff of invalid)
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,cutoff),
   /Invalid UTC hourly as-of close/);
});


// An invalid cutoff must not even enumerate source provenance metadata.
// This catches preflight regressions that invoke Reflect.ownKeys or descriptor
// inspection before validating the caller's timestamp.
test('invalid as-of cutoff avoids source metadata introspection',()=>{
 let sourceInspections=0;
 const source=new Proxy({} as FvgSource,{
  get(){sourceInspections++;throw Error('source read before cutoff validation');},
  ownKeys(){sourceInspections++;throw Error('source keys before cutoff validation');},
  getOwnPropertyDescriptor(){sourceInspections++;throw Error('source descriptor before cutoff validation');},
 });
 const bars=new Proxy([] as Bar[],{
  get(){throw Error('archive read before cutoff validation');},
  ownKeys(){throw Error('archive keys before cutoff validation');},
  getOwnPropertyDescriptor(){throw Error('archive descriptor before cutoff validation');},
 });
 for(const cutoff of [0,-0,3600.5,Date.UTC(2100,0,1,1)/1000]){
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,cutoff),
   /Invalid UTC hourly as-of close/);
 }
 assert.equal(sourceInspections,0);
});

// A caller can bypass TypeScript at runtime. Reject object/string cutoffs
// without invoking valueOf/Symbol.toPrimitive or reading source/archive data.
test('non-numeric as-of cutoffs fail before coercion or evidence access',()=>{
 let coercions=0;
 const hostile=Object.defineProperty({},Symbol.toPrimitive,{
  get(){coercions++;throw Error('coercion hook must not run');},
 });
 const source=Object.defineProperty({},'datasetId',{
  get(){throw Error('source getter must not run');},enumerable:true,
 }) as FvgSource;
 const bars=new Proxy([] as Bar[],{
  get(){throw Error('archive getter must not run');},
  getOwnPropertyDescriptor(){throw Error('archive descriptor must not run');},
  ownKeys(){throw Error('archive keys must not be read');},
 });
 for(const cutoff of [hostile,'3600',3600n,null,undefined,true]){
  assert.throws(()=>studyHourlyFvgMidpointAsOf(
   bars,source,cutoff as unknown as number),/Invalid UTC hourly as-of close/);
 }
 assert.equal(coercions,0);
});


// Symbols and callable objects are valid JavaScript values despite being
// impossible UTC timestamps. Fail closed without invoking a callable cutoff
// or touching source/archive evidence.
test('symbol and callable as-of cutoffs fail closed before evidence access',()=>{
 let calls=0;
 const callable=()=>{calls++;throw Error('callable cutoff must not run');};
 const source=Object.defineProperty({},'provider',{
  get(){throw Error('source getter must not run');},enumerable:true,
 }) as FvgSource;
 const bars=new Proxy([] as Bar[],{
  get(){throw Error('archive getter must not run');},
  getOwnPropertyDescriptor(){throw Error('archive descriptor must not run');},
  ownKeys(){throw Error('archive keys must not be read');},
 });
 for(const cutoff of [Symbol('as-of'),Symbol.for('as-of'),callable]){
  assert.throws(()=>studyHourlyFvgMidpointAsOf(
   bars,source,cutoff as unknown as number),/Invalid UTC hourly as-of close/);
 }
 assert.equal(calls,0);
});


// Preflight must not attempt prototype discovery, membership checks, or
// mutations on caller-owned evidence when the cutoff is already invalid.
test('invalid as-of cutoff avoids prototype, membership and mutation traps',()=>{
 let traps=0;
 const deny=()=>{traps++;throw Error('evidence trap invoked before cutoff preflight');};
 const handlers={
  get:deny,ownKeys:deny,getOwnPropertyDescriptor:deny,
  getPrototypeOf:deny,has:deny,set:deny,defineProperty:deny,
  deleteProperty:deny,setPrototypeOf:deny,
 };
 const source=new Proxy({} as FvgSource,handlers);
 const archive=new Proxy([] as Bar[],handlers);
 for(const cutoff of [0,-0,3600.5,Number.POSITIVE_INFINITY]){
  assert.throws(()=>studyHourlyFvgMidpointAsOf(archive,source,cutoff),
   /Invalid UTC hourly as-of close/);
 }
 assert.equal(traps,0);
});

// Revoked proxies throw on every attempted internal operation, including
// operations not represented by the explicit hostile traps above.
test('invalid as-of cutoff never inspects revoked evidence proxies',()=>{
 const source=Proxy.revocable({} as FvgSource,{});
 const archive=Proxy.revocable([] as Bar[],{});
 source.revoke();
 archive.revoke();
 for(const cutoff of [-0,0,3600.5,Number.NaN]){
  assert.throws(()=>studyHourlyFvgMidpointAsOf(archive.proxy,source.proxy,cutoff),
   /Invalid UTC hourly as-of close/);
 }
});

// Missing evidence is not a reason to bypass the as-of timestamp contract.
// This guards validation precedence even when runtime callers bypass TS types.
test('invalid as-of cutoff precedes null evidence validation',()=>{
 for(const cutoff of [0,-0,3600.5,Number.NaN]){
  assert.throws(()=>studyHourlyFvgMidpointAsOf(
   null as unknown as Bar[],null as unknown as FvgSource,cutoff),
   /Invalid UTC hourly as-of close/);
 }
});

// A valid completed-hour cutoff must not turn absent evidence into an empty
// (apparently evaluated) research study. Reject before touching source fields.
test('valid as-of cutoff rejects absent candle archive instead of fabricating evidence',()=>{
 let reads=0;
 const source=new Proxy({} as FvgSource,{
  get(){reads++;throw Error('source must not be inspected without an archive');},
  ownKeys(){reads++;throw Error('source must not be enumerated');},
  getOwnPropertyDescriptor(){reads++;throw Error('source must not be described');},
 });
 for(const archive of [null,undefined,{}]){
  assert.throws(()=>studyHourlyFvgMidpointAsOf(
   archive as unknown as Bar[],source,3600),
   /Invalid or oversized hourly research window/);
 }
 assert.equal(reads,0);
});


// Runtime callers can supply primitives despite the Bar[] type annotation.
// With a valid cutoff, these must fail as absent archive evidence before any
// source metadata is read, not produce an apparently empty research result.
test('valid as-of cutoff rejects primitive candle archives before source inspection',()=>{
 let reads=0;
 const source=new Proxy({} as FvgSource,{
  get(){reads++;throw Error('source read without valid archive');},
  ownKeys(){reads++;throw Error('source enumerated without valid archive');},
  getOwnPropertyDescriptor(){reads++;throw Error('source described without valid archive');},
 });
 for(const archive of [false,0,3600,'', 'candles', 1n, Symbol('archive')]){
  assert.throws(()=>studyHourlyFvgMidpointAsOf(
   archive as unknown as Bar[],source,3600),
   /Invalid or oversized hourly research window/);
 }
 assert.equal(reads,0);
});

// Array-like objects can masquerade as a complete archive at runtime. Their
// length and indexed getters must not be evaluated as candle evidence.
test('valid as-of cutoff rejects array-like archive impostors before source access',()=>{
 let evidenceReads=0;
 const source=new Proxy({} as FvgSource,{
  get(){evidenceReads++;throw Error('source accessed before archive validation');},
  ownKeys(){evidenceReads++;throw Error('source enumerated before archive validation');},
 });
 const impostor=Object.defineProperties({}, {
  length:{get(){evidenceReads++;throw Error('array-like length evaluated');}},
  0:{get(){evidenceReads++;throw Error('array-like candle evaluated');}},
 });
 assert.throws(()=>studyHourlyFvgMidpointAsOf(
  impostor as unknown as Bar[],source,3600),
  /Invalid or oversized hourly research window/);
 assert.equal(evidenceReads,0);
});


// An oversized archive must be rejected by its declared length, without
// iterating over rows or inspecting source identity. This bounds as-of work
// before untrusted candle access; no market data are fabricated here.
test('valid as-of cutoff rejects oversized archive before row or source reads',()=>{
 let reads=0;
 const source=new Proxy({} as FvgSource,{
  get(){reads++;throw Error('source read before size preflight');},
  ownKeys(){reads++;throw Error('source enumeration before size preflight');},
  getOwnPropertyDescriptor(){reads++;throw Error('source descriptor before size preflight');},
 });
 const archive=new Proxy(new Array(20001) as Bar[],{
  get(target,key,receiver){
   if(key==='length')return Reflect.get(target,key,receiver);
   reads++;throw Error('oversized archive row accessed');
  },
  ownKeys(){reads++;throw Error('oversized archive enumerated');},
  getOwnPropertyDescriptor(){reads++;throw Error('oversized archive described');},
 });
 assert.throws(()=>studyHourlyFvgMidpointAsOf(archive,source,3600),
  /Invalid or oversized hourly research window/);
 assert.equal(reads,0);
});


// An own accessor slot is not stable historical evidence: its getter could
// return different candles on successive reads. Reject without invoking it,
// and without reading the source declaration or future OHLC values.
test('as-of scanner rejects accessor-backed archive rows without executing getters',()=>{
 let reads=0;
 const archive=new Array(1) as Bar[];
 Object.defineProperty(archive,'0',{
  enumerable:true,configurable:true,
  get(){reads++;throw Error('unstable archive row getter executed');},
 });
 const source=new Proxy({} as FvgSource,{
  get(){reads++;throw Error('source accessed before archive slot preflight');},
  ownKeys(){reads++;throw Error('source enumerated before archive slot preflight');},
  getOwnPropertyDescriptor(){reads++;throw Error('source described before archive slot preflight');},
 });
 assert.throws(()=>studyHourlyFvgMidpointAsOf(archive,source,3600),
  /FVG as-of archive requires own data-property candle slots/);
 assert.equal(reads,0);
});

// Exactly 20,000 slots is within the declared work bound, but an unfilled
// archive is still missing evidence. Distinguish the size gate from the
// own-row evidence gate without manufacturing historical candles.
test('as-of archive maximum length is inclusive but sparse evidence fails closed',()=>{
 let sourceReads=0;
 const source=new Proxy({} as FvgSource,{
  get(){sourceReads++;throw Error('source accessed before archive evidence');},
  ownKeys(){sourceReads++;throw Error('source enumerated before archive evidence');},
 });
 const archive=new Array(20000) as Bar[];
 assert.throws(()=>studyHourlyFvgMidpointAsOf(archive,source,3600),
  /Hourly research array contains missing or hidden own-index candle evidence/);
 assert.equal(sourceReads,0);
});


// A hole can appear populated through the array's prototype chain. Such a
// value is not an own archived candle and must never count as source evidence.
test('as-of scanner rejects prototype-inherited candle slots without reading them',()=>{
 let inheritedReads=0;
 let sourceReads=0;
 const prototype=Object.create(Array.prototype);
 Object.defineProperty(prototype,'0',{
  configurable:true,
  get(){inheritedReads++;throw Error('inherited candle getter executed');},
 });
 const archive=new Array(1) as Bar[];
 Object.setPrototypeOf(archive,prototype);
 const source=new Proxy({} as FvgSource,{
  get(){sourceReads++;throw Error('source read before own-slot validation');},
  ownKeys(){sourceReads++;throw Error('source enumerated before own-slot validation');},
 });
 assert.throws(()=>studyHourlyFvgMidpointAsOf(archive,source,3600),
  /Hourly research array contains missing or hidden own-index candle evidence/);
 assert.equal(inheritedReads,0);
 assert.equal(sourceReads,0);
});


// A non-enumerable own slot is hidden from ordinary archive enumeration.
// It must not be counted as an observed candle even if its value is present.
// The rejection must precede source access and any candle-field reads.
test('as-of scanner rejects hidden own candle slots before reading evidence',()=>{
 let reads=0;
 const row=new Proxy({} as Bar,{
  get(){reads++;throw Error('hidden candle was inspected');},
  ownKeys(){reads++;throw Error('hidden candle enumerated');},
 });
 const archive=[row] as Bar[];
 Object.defineProperty(archive,'0',{
  value:row,enumerable:false,writable:true,configurable:true,
 });
 const source=new Proxy({} as FvgSource,{
  get(){reads++;throw Error('source read before hidden-slot rejection');},
  ownKeys(){reads++;throw Error('source enumerated before hidden-slot rejection');},
 });
 assert.throws(()=>studyHourlyFvgMidpointAsOf(archive,source,3600),
  /Hourly research array contains missing or hidden own-index candle evidence/);
 assert.equal(reads,0);
});


// A declared array-level property must not smuggle a second feed or receipt
// into a BID-only study. Reject metadata by descriptor without executing its
// getter or reading source identity, even when there are no candle rows.
test('as-of scanner rejects undeclared archive metadata without executing it',()=>{
 let reads=0;
 const archive=[] as Bar[];
 Object.defineProperty(archive,'askQuotes',{
  enumerable:false,configurable:true,
  get(){reads++;throw Error('undeclared ASK metadata getter executed');},
 });
 const source=new Proxy({} as FvgSource,{
  get(){reads++;throw Error('source read before archive schema rejection');},
  ownKeys(){reads++;throw Error('source enumerated before archive schema rejection');},
  getOwnPropertyDescriptor(){reads++;throw Error('source described before archive schema rejection');},
 });
 assert.throws(()=>studyHourlyFvgMidpointAsOf(archive,source,3600),
  /Unexpected FVG archive array metadata outside frozen BID-only protocol/);
 assert.equal(reads,0);
});


// A custom iterator can substitute or skip source rows during iteration.
// The frozen BID-only archive must reject the override by descriptor without
// running it or inspecting a source receipt, even for an empty archive.
test('as-of scanner rejects custom archive iterator without executing getter',()=>{
 let reads=0;
 const archive=[] as Bar[];
 Object.defineProperty(archive,Symbol.iterator,{
  configurable:true,enumerable:false,
  get(){reads++;throw Error('custom archive iterator executed');},
 });
 const source=new Proxy({} as FvgSource,{
  get(){reads++;throw Error('source read before archive schema rejection');},
  ownKeys(){reads++;throw Error('source enumerated before archive schema rejection');},
  getOwnPropertyDescriptor(){reads++;throw Error('source described before archive schema rejection');},
 });
 assert.throws(()=>studyHourlyFvgMidpointAsOf(archive,source,3600),
  /Unexpected FVG archive array metadata outside frozen BID-only protocol/);
 assert.equal(reads,0);
});
