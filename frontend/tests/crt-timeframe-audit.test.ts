import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditCrtCrossTimeframe,certifiedCrtFourHourBars} from '../lib/crt-timeframe-audit.ts';
import {screenCrtHypotheses} from '../lib/crt-quant-filters.ts';
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
  {checkedFourHourBars:2,uncheckableFourHourBars:0,
   verifiedFourHourStarts:[BASE,BASE+H4]});
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
  {checkedFourHourBars:0,uncheckableFourHourBars:2,
   verifiedFourHourStarts:[]});
 assert.deepEqual(auditCrtCrossTimeframe(h,q.slice(16)),
  {checkedFourHourBars:1,uncheckableFourHourBars:1,
   verifiedFourHourStarts:[BASE+H4]});
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
  {checkedFourHourBars:0,uncheckableFourHourBars:2,
   verifiedFourHourStarts:[]});
});

test('uncheckable archive-edge 4H candle cannot manufacture a CRT sweep candidate',()=>{
 // 15m API history begins at 04:00. The 00:00 reference is not independently
 // certified, even though the 04:00 sweep and 08:00 follow-up are certified.
 const h=[
  candle(BASE,105,110,100,105,240),
  candle(BASE+H4,104,109,98.5,104,240),
  candle(BASE+2*H4,104,106,101,104,240),
 ];
 const q=Array.from({length:32},(_,i)=>{
  const t=BASE+H4+i*Q;
  return i<16?candle(t,104,108,101,104):candle(t,104,106,101,104);
 });
 q[3].high=109;q[7].low=98.5;
 const source={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'NSXUSD-CFD',provider:'owner-authorized-archive',
  priceSide:'bid' as const,volumeType:'unverified' as const,volumeVerified:false,
 };
 const unfiltered=screenCrtHypotheses({fourHour:h,fifteenMinute:q,source});
 assert.equal(unfiltered.candidates.length,1,'regression fixture has a real-looking but uncertified sweep');
 const audit=auditCrtCrossTimeframe(h,q);
 assert.deepEqual(audit.verifiedFourHourStarts,[BASE+H4,BASE+2*H4]);
 assert.equal(audit.uncheckableFourHourBars,1);
 const certified=certifiedCrtFourHourBars(h,q,audit);
 assert.deepEqual(certified.map(x=>x.time),[BASE+H4,BASE+2*H4]);
 assert.equal(screenCrtHypotheses({fourHour:certified,fifteenMinute:q,source}).candidates.length,0,
  'uncheckable 4H reference must never appear in candidate counts');
});
test('a tampered or stale certification report cannot be used to select 4H bars',()=>{
 const {h,q}=fixture();
 const valid=auditCrtCrossTimeframe(h,q);
 assert.throws(()=>certifiedCrtFourHourBars(h,q,{
  ...valid,verifiedFourHourStarts:[BASE+2*H4,BASE+H4],
 }),/Stale or inconsistent 4H\/15m certification report/);
 assert.throws(()=>certifiedCrtFourHourBars(h,q,{
  ...valid,checkedFourHourBars:1,
 }),/Stale or inconsistent 4H\/15m certification report/);
});

test('a stale 4H/15m audit cannot certify edited historical OHLC',()=>{
 const x=fixture();
 const report=auditCrtCrossTimeframe(x.h,x.q);
 x.h[0].close+=0.01; // Still a valid 4H candle, but no longer agrees with 15m.
 assert.throws(()=>certifiedCrtFourHourBars(x.h,x.q,report),/OHLC mismatch/);
 const y=fixture();
 const old=auditCrtCrossTimeframe(y.h,y.q);
 y.q[0].open+=0.01; // Valid 15m candle; invalidates the previously checked open.
 assert.throws(()=>certifiedCrtFourHourBars(y.h,y.q,old),/OHLC mismatch/);
});

test('a forged audit cannot substitute an existing uncheckable 4H reference',()=>{
 const {h,q}=fixture();
 const partial=q.slice(16); // 00:00 4H is uncheckable; 04:00 is verified.
 const report=auditCrtCrossTimeframe(h,partial);
 assert.deepEqual(report.verifiedFourHourStarts,[BASE+H4]);
 const forged={...report,verifiedFourHourStarts:[BASE]};
 assert.throws(()=>certifiedCrtFourHourBars(h,partial,forged),
  /Stale or inconsistent 4H\/15m certification report/);
});
