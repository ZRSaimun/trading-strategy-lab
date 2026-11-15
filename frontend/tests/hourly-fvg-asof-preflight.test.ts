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
