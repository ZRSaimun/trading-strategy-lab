import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic no-lookahead integrity test, not market evidence.
const H=3600;
const source={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
 volumeType:'unverified' as const,volumeVerified:false};

for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending timestamp cannot delete completed ${direction} volume-baseline slot without changing length`,()=>{
  const bars:Bar[]=Array.from({length:21},(_,i)=>({
   time:i*H,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
  }));
  bars.push(...(direction==='BULLISH'?[
   {time:21*H,open:102,high:105,low:101,close:104,volume:10,observed_minutes:60},
   {time:22*H,open:104,high:106,low:103,close:105,volume:10,observed_minutes:60},
  ]:[
   {time:21*H,open:99,high:100,low:96,close:97,volume:10,observed_minutes:60},
   {time:22*H,open:97,high:98,low:95,close:96,volume:10,observed_minutes:60},
  ]));
  let timeReads=0,marketReads=0;
  const forbidden=():never=>{marketReads++;throw Error('future market field read');};
  const completedBaseline=studyHourlyFvgMidpointAsOf(bars,source,23*H);
  assert.ok(completedBaseline.observations.length>0);
  const originalRow=bars[10];
  bars.push({
   get time(){timeReads++;delete bars[10];return 23*H;},
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},get observed_minutes(){return forbidden();},
  } as unknown as Bar);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,23*H),
   /Hourly research.*(?:snapshot|archive|array|slot|row|hole)/i);
  assert.equal(timeReads,1);
  assert.equal(marketReads,0);
  assert.equal(bars.length,24);
  assert.equal(Object.hasOwn(bars,10),false);
  // Caller-side restoration must recover the identical completed-prefix result;
  // rejection must not poison later independent research scans.
  bars.pop();
  bars[10]=originalRow;
  assert.deepEqual(studyHourlyFvgMidpointAsOf(bars,source,23*H),completedBaseline);
 });
}
