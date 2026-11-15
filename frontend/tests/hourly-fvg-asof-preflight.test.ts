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
   bars,source,cutoff as number),/Invalid UTC hourly as-of close/);
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
   bars,source,cutoff as number),/Invalid UTC hourly as-of close/);
 }
 assert.equal(calls,0);
});
