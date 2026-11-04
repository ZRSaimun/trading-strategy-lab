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
