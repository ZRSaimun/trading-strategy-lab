import {test} from 'node:test';
import assert from 'node:assert/strict';
import {loadNyCloseWindow} from '../lib/ny-close-history.ts';
import {isNyRegularSessionMinute} from '../lib/ny-close-momentum.ts';
import type {ArchivePage} from '../lib/backtest-history.ts';

const id='a'.repeat(64);
const dataset={id,provider:'HistData',instrument:'NSXUSD-CFD',archive_sha256:'b'.repeat(64)};
const bar=(t:number)=>({time:t,open:100,high:102,low:99,close:101,
 volume:null,observed_minutes:1});
const t=(day:number,h:number,m:number)=>Date.UTC(2026,0,day,h,m)/1000;
function pg(times:number[],more=false,change:Partial<ArchivePage>={}):ArchivePage{
 return {dataset,quality:{live:false,price_side:'bid'},candles:times.map(bar),
  has_more:more,next_before:more?times[0]:null,...change};
}
test('NY equity regular session filter respects January and July US daylight time',()=>{
 assert.equal(isNyRegularSessionMinute(t(5,14,30)),true);
 assert.equal(isNyRegularSessionMinute(t(5,14,29)),false);
 assert.equal(isNyRegularSessionMinute(t(5,21,0)),false);
 const july=Date.UTC(2026,6,6,13,30)/1000;
 assert.equal(isNyRegularSessionMinute(july),true);
 assert.equal(isNyRegularSessionMinute(july-60),false);
 assert.equal(isNyRegularSessionMinute(july+390*60),false);
 // US equity exchange is closed on Saturdays; do not infer weekend RTH.
 assert.equal(isNyRegularSessionMinute(t(10,14,30)),false);
});
test('scans older page through off-session data without pretending all minutes were tradable',async()=>{
 const seen:Array<[number|null,number]>=[];
 const result=await loadNyCloseWindow(id,async(before,limit)=>{
  seen.push([before,limit]);
  return seen.length===1?pg([t(5,14,30),t(5,14,31)],true):
   pg([t(5,13,0),t(5,14,29)]);
 },4,4,2);
 assert.deepEqual(result.bars.map(x=>x.time),[t(5,14,30),t(5,14,31)]);
 assert.deepEqual(seen,[[null,2],[t(5,14,30),2]]);
 assert.equal(result.rawBarsScanned,4);
 assert.equal(result.pages,2);
 assert.equal(result.capped,false);
 assert.equal(result.dataset.archive_sha256,dataset.archive_sha256);
});
test('bounded scanner flags unfinished older archive and retains later source bars',async()=>{
 const result=await loadNyCloseWindow(id,async(before)=>{
  return before===null?pg([t(5,14,33),t(5,14,34)],true):
   pg([t(5,14,31),t(5,14,32)],true);
 },4,3,2);
 assert.equal(result.capped,true);
 assert.equal(result.rawBarsScanned,4);
 assert.deepEqual(result.bars.map(x=>x.time),[t(5,14,32),t(5,14,33),t(5,14,34)]);
});
test('refuses changed archive, malformed cursors and overlapping input',async()=>{
 await assert.rejects(()=>loadNyCloseWindow(id,async before=>
  before===null?pg([t(5,14,33),t(5,14,34)],true):
    pg([t(5,14,31),t(5,14,32)],false,
      {dataset:{...dataset,archive_sha256:'c'.repeat(64)}}),4,4,2),/Source changed/);
 await assert.rejects(()=>loadNyCloseWindow(id,async()=>
  pg([t(5,14,33),t(5,14,34)],true,{next_before:t(5,14,34)}),4,4,2),/cursor/);
 await assert.rejects(()=>loadNyCloseWindow(id,async before=>
  before===null?pg([t(5,14,33),t(5,14,34)],true):
   pg([t(5,14,33),t(5,14,34)]),4,4,2),/Overlapping/);
});
test('refuses executable-live claims, non-M1 observations and invalid scan limits',async()=>{
 await assert.rejects(()=>loadNyCloseWindow(id,async()=>pg([t(5,14,30)],false,
  {quality:{live:true,price_side:'bid'}})),/Source changed/);
 await assert.rejects(()=>loadNyCloseWindow(id,async()=>pg([t(5,14,30)],false,
  {candles:[{...bar(t(5,14,30)),observed_minutes:0}]})),/malformed/);
 await assert.rejects(()=>loadNyCloseWindow('bad',async()=>pg([])),/Invalid source/);
 await assert.rejects(()=>loadNyCloseWindow(id,async()=>pg([]),100001),/Invalid source/);
});
