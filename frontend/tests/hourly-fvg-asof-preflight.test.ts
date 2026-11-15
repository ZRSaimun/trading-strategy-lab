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
