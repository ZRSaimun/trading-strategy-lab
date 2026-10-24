import {test} from 'node:test';
import assert from 'node:assert/strict';
import {loadArchiveWindow,type ArchivePage} from '../lib/backtest-history.ts';

const id='a'.repeat(64);
const identity={id,provider:'HistData',instrument:'XAUUSD-OTC',archive_sha256:'b'.repeat(64)};
const bar=(time:number)=>({time,open:100,high:101,low:99,close:100,volume:null,observed_minutes:1});
function page(times:number[],has_more=false,override:Partial<ArchivePage>={}):ArchivePage{
 return {dataset:identity,candles:times.map(bar),has_more,
         next_before:has_more?times[0]:null,quality:{live:false,price_side:'bid'},...override};
}
test('loads source-isolated pages in ascending order without duplicate boundaries',async()=>{
 const seen:Array<[number|null,number]>=[];
 const result=await loadArchiveWindow(id,'1m',async(before,limit)=>{
  seen.push([before,limit]);
  return seen.length===1?page([180,240],true):page([60,120]);
 },10,2);
 assert.deepEqual(result.bars.map(b=>b.time),[60,120,180,240]);
 assert.deepEqual(seen,[[null,2],[180,2]]);
 assert.equal(result.pages,2);
 assert.equal(result.capped,false);
 assert.equal(result.dataset.archive_sha256,identity.archive_sha256);
});
test('stops at 20k maximum and clearly records a capped, not complete, window',async()=>{
 const result=await loadArchiveWindow(id,'1m',async(before)=>{
  return before===null?page([300,360],true):page([180,240],true);
 },4,2);
 assert.deepEqual(result.bars.map(b=>b.time),[180,240,300,360]);
 assert.equal(result.capped,true);
 assert.equal(result.pages,2);
 assert.rejects(()=>loadArchiveWindow(id,'1H',async()=>page([60]),20001));
});
test('rejects source identity mutation, overlapping pages and malformed cursor',async()=>{
 const changed={...identity,archive_sha256:'c'.repeat(64)};
 await assert.rejects(()=>loadArchiveWindow(id,'1m',async before=>
  before===null?page([180,240],true):page([60,120],false,{dataset:changed}),10,2),/identity changed/);
 await assert.rejects(()=>loadArchiveWindow(id,'1m',async before=>
  before===null?page([180,240],true):page([120,180]),10,2),/overlapping|malformed/);
 await assert.rejects(()=>loadArchiveWindow(id,'1m',async()=>page([180,240],true,{next_before:240}),10,2),/cursor/);
 await assert.rejects(()=>loadArchiveWindow(id,'1m',async()=>page([180,180]),10,2),/unordered/);
});
test('fails closed on live quotes, empty archives and mismatched dataset id',async()=>{
 await assert.rejects(()=>loadArchiveWindow(id,'1m',async()=>page([])),/no candles/);
 await assert.rejects(()=>loadArchiveWindow(id,'1m',async()=>page([60],false,{quality:{live:true,price_side:'bid'}})),/bid-only/);
 await assert.rejects(()=>loadArchiveWindow(id,'1m',async()=>page([60],false,{dataset:{...identity,id:'c'.repeat(64)}})),/identity changed/);
 await assert.rejects(()=>loadArchiveWindow('invalid','1m',async()=>page([60])),/Unsupported/);
});
