import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditCrtCrossTimeframe} from '../lib/crt-timeframe-audit.ts';
import type {Bar} from '../lib/research.ts';

const BASE=Date.UTC(2026,9,20)/1000, Q=900, H4=14400;
const candle=(time:number,open=100,high=101,low=99,close=100,mins=15):Bar=>({
 time,open,high,low,close,volume:null,observed_minutes:mins,
});
function fixture(){
 const q=Array.from({length:32},(_,i)=>candle(BASE+i*Q));
 q[0].open=100.5;q[4].high=103;q[7].low=97;q[15].close=100.25;
 q[16].open=100.25;q[19].high=104;q[24].low=95;q[31].close=100.75;
 const h=[
  candle(BASE,100.5,103,97,100.25,240),
  candle(BASE+H4,100.25,104,95,100.75,240),
 ];
 return {h,q};
}
test('validates two complete adjacent 4H bars against exactly 16 observed 15m bars each',()=>{
 const {h,q}=fixture();
 assert.deepEqual(auditCrtCrossTimeframe(h,q),
  {checkedFourHourBars:2,uncheckableFourHourBars:0});
});
test('fails closed when source-identical timeframe response has inconsistent OHLC',()=>{
 for(const field of ['open','high','low','close'] as const){
  const {h,q}=fixture();h[0][field]+=0.01;
  assert.throws(()=>auditCrtCrossTimeframe(h,q),/OHLC mismatch/);
 }
});
test('missing interior 15m observations never certify an apparently complete 4H bar',()=>{
 const {h,q}=fixture();
 q.splice(5,1);
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/Missing or noncontiguous/);
});
test('partial overlapping boundary windows are explicitly uncheckable, not falsely verified',()=>{
 const {h,q}=fixture();
 assert.deepEqual(auditCrtCrossTimeframe(h,q.slice(1,31)),
  {checkedFourHourBars:0,uncheckableFourHourBars:2});
 assert.deepEqual(auditCrtCrossTimeframe(h,q.slice(16)),
  {checkedFourHourBars:1,uncheckableFourHourBars:1});
});
test('mutations to candles after the checked 4H window do not affect past audit',()=>{
 const {h,q}=fixture();
 const before=auditCrtCrossTimeframe(h,q);
 q.push(candle(BASE+32*Q,200,210,190,200));
 assert.deepEqual(auditCrtCrossTimeframe(h,q),before);
});
test('rejects malformed 15m/4H input instead of silently accepting',()=>{
 const x=fixture();x.q[0].observed_minutes=14;
 assert.throws(()=>auditCrtCrossTimeframe(x.h,x.q),/Incomplete or invalid/);
 const y=fixture();y.h[0].time+=Q;
 assert.throws(()=>auditCrtCrossTimeframe(y.h,y.q),/Incomplete or invalid/);
 const z=fixture();z.q[1].time=z.q[0].time;
 assert.throws(()=>auditCrtCrossTimeframe(z.h,z.q),/Out-of-order/);
});
test('a missing 15m response cannot be presented as verified 4H coherence',()=>{
 const {h}=fixture();
 assert.deepEqual(auditCrtCrossTimeframe(h,[]),
  {checkedFourHourBars:0,uncheckableFourHourBars:2});
});
