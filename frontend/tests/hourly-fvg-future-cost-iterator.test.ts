import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic integrity check only; no authenticated broker quotes or fills.
test('future timestamp cannot inject an own cost-array iterator after source preflight',()=>{
 const H=3600;
 const source={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
  volumeType:'unverified' as const,volumeVerified:false,
 };
 const costs=[1,3];
 const bars:Bar[]=Array.from({length:23},(_,i)=>({
  time:i*H,open:100,high:101,low:99,close:100,
  volume:10,observed_minutes:60,
 }));
 let timestampReads=0,marketReads=0,iteratorReads=0;
 const forbidden=():never=>{marketReads++;throw Error('future market evidence read');};
 bars.push({
  get time(){
   timestampReads++;
   Object.defineProperty(costs,Symbol.iterator,{
    configurable:true,enumerable:false,
    get(){iteratorReads++;throw Error('untrusted iterator executed');},
   });
   return 24*H;
  },
  get open(){return forbidden();},get high(){return forbidden();},
  get low(){return forbidden();},get close(){return forbidden();},
  get volume(){return forbidden();},
  get observed_minutes(){return forbidden();},
 } as unknown as Bar);
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H,{
  hypotheticalRoundTripCostsBps:costs,
 }),/FVG as-of cost scenario schema changed during timestamp scan/);
 assert.equal(timestampReads,1);
 assert.equal(marketReads,0);
 assert.equal(iteratorReads,0,'injected iterator getter must not execute');
});

test('ordinary cost array remains valid with strictly future timestamp',()=>{
 const H=3600;
 const source={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
  volumeType:'unverified' as const,volumeVerified:false,
 };
 const bars:Bar[]=Array.from({length:23},(_,i)=>({
  time:i*H,open:100,high:101,low:99,close:100,
  volume:10,observed_minutes:60,
 }));
 bars.push({time:24*H} as Bar);
 assert.doesNotThrow(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H,{
  hypotheticalRoundTripCostsBps:[1,3],
 }));
});
