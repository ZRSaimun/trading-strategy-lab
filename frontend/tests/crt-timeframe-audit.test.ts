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
test('source-identical 4H and 15m OHLC must match exactly at tiny and large nominal scales',()=>{
 // The old max(1, nominal price) epsilon accepted a 5e-11 difference at
 // micro-prices and a full 0.01 difference near 1e9. Both are source
 // inconsistencies, regardless of unknown instrument tick size.
 for(const {scale,drift} of [
  {scale:1e-8,drift:5e-11},
  {scale:1e7,drift:0.01},
 ]){
  const {h,q}=fixture();
  for(const b of [...h,...q]){
   b.open*=scale;b.high*=scale;b.low*=scale;b.close*=scale;
  }
  assert.equal(auditCrtCrossTimeframe(h,q).checkedFourHourBars,2);
  h[0].high+=drift;
  assert.throws(()=>auditCrtCrossTimeframe(h,q),/OHLC mismatch/,
   'same-archive mismatch must never be masked by a nominal-price epsilon');
 }
});

test('fully reported 4H volume must equal the sixteen observed 15m volumes',()=>{
 const {h,q}=fixture();
 q.forEach((b,i)=>{b.volume=i%2===0?2.25:10.5;});
 h.forEach((b,i)=>{
  b.volume=q.slice(i*16,(i+1)*16).reduce((sum,v)=>sum+(v.volume??0),0);
 });
 assert.equal(auditCrtCrossTimeframe(h,q).checkedFourHourBars,2);
 // Price aggregates still agree: inconsistent numeric volume must not be
 // silently accepted as the same source's complete 4H observation.
 h[0].volume!+=1;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/);
});
test('integer 15m volume counts must match exactly even at large scales',()=>{
 // The old 64-ULP relative tolerance accepted a one-count discrepancy
 // near 1e14 despite every constituent being an exact integer count.
 const {h,q}=fixture();
 q.forEach(b=>{b.volume=6_250_000_000_000;});
 h.forEach(b=>{b.volume=100_000_000_000_000;});
 assert.equal(auditCrtCrossTimeframe(h,q).checkedFourHourBars,2);
 h[0].volume=100_000_000_000_001;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/);
 h[0].volume=100_000_000_000_000.5;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'fractional aggregate cannot certify sixteen exact integer counts');
});
test('integer count sums exceeding safe numeric precision cannot be certified',()=>{
 const {h,q}=fixture();
 q.forEach(b=>{b.volume=600_000_000_000_000;});
 h.forEach(b=>{b.volume=9_600_000_000_000_000;});
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'a numerically equal but unsafe integer total is not exact count evidence');
});
test('large fractional volume aggregates cannot hide a full reported-unit drift',()=>{
 // All sixteen volumes have genuine fractional parts, so the integer-only
 // branch does not apply. The former 64-ULP tolerance was >1 at this scale.
 const {h,q}=fixture();
 q.forEach(b=>{b.volume=6_250_000_000_000.25;});
 h.forEach(b=>{b.volume=100_000_000_000_004;});
 assert.equal(auditCrtCrossTimeframe(h,q).checkedFourHourBars,2);
 h[0].volume!+=1;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'a full unit discrepancy is not acceptable floating-point summation noise');
});
test('fractional volume sums above safe integer magnitude cannot be certified',()=>{
 // The old fractional branch accepted equal rounded totals above 2^53,
 // although sub-unit differences can no longer be reliably represented.
 const {h,q}=fixture();
 q.forEach(b=>{b.volume=600_000_000_000_000.25;});
 h.forEach(b=>{b.volume=9_600_000_000_000_004;});
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'matching rounded totals are not evidence of precise aggregation');
});
test('an unsafe constituent volume is not laundered through fractional tolerance',()=>{
 const {h,q}=fixture();
 q.forEach(b=>{b.volume=0;});
 h.forEach(b=>{b.volume=0;});
 q[0].volume=9_007_199_254_740_994;
 h[0].volume=9_007_199_254_740_994;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'a rounded unsafe input cannot be certified even when totals match');
});
test('small fractional volume summation still permits floating-point roundoff',()=>{
 const {h,q}=fixture();
 q.forEach(b=>{b.volume=0.1;});
 h.forEach(b=>{b.volume=1.6;});
 assert.equal(auditCrtCrossTimeframe(h,q).checkedFourHourBars,2);
});
test('tiny fractional volume mismatch cannot pass a one-unit tolerance floor',()=>{
 // Sixteen 1e-16 observations genuinely sum to ~1.6e-15. The old
 // Math.max(1, ...) floor allowed a zero 4H volume to pass as equal.
 const {h,q}=fixture();
 q.forEach(b=>{b.volume=1e-16;});
 h.forEach(b=>{b.volume=1.6e-15;});
 assert.equal(auditCrtCrossTimeframe(h,q).checkedFourHourBars,2,
  'legitimate tiny fractional summation roundoff remains acceptable');
 h[0].volume=0;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'a reported zero aggregate must not hide observed tiny fractional volume');
});
test('null constituent or aggregate volume stays unknown, not fabricated zero',()=>{
 const x=fixture();
 x.q.forEach(b=>{b.volume=5;});
 // A null 4H volume is unknown; price-only OHLC audit remains possible.
 assert.equal(auditCrtCrossTimeframe(x.h,x.q).checkedFourHourBars,2);
 const y=fixture();
 y.q.forEach(b=>{b.volume=5;});
 y.h.forEach(b=>{b.volume=80;});
 y.q[3].volume=null;
 assert.equal(auditCrtCrossTimeframe(y.h,y.q).checkedFourHourBars,2);
 // This checked count certifies price aggregation only, not real volume
 // source identity or a volume confirmation gate.
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

test('certified 4H bars remain detached and frozen after the original inputs change',()=>{
 const {h,q}=fixture();
 const report=auditCrtCrossTimeframe(h,q);
 const certified=certifiedCrtFourHourBars(h,q,report);
 const originalOpen=certified[0].open;
 assert.notStrictEqual(certified[0],h[0],
  'certification must not expose a mutable alias to the source candle');
 assert.equal(Object.isFrozen(certified[0]),true);
 assert.equal(Object.isFrozen(certified),true,
  'the certified candle collection itself must be immutable');
 assert.throws(()=>{(certified as Bar[]).push(candle(BASE+2*H4));},TypeError,
  'a consumer cannot append a fabricated 4H reference after certification');
 assert.throws(()=>{(certified as Bar[]).splice(0,1);},TypeError,
  'a consumer cannot silently remove an audited sweep');
 assert.deepEqual(certified.map(b=>b.time),[BASE,BASE+H4]);
 assert.equal(h.length,2,'the source input remains untouched');
 // Both source timeframes still reconcile, but the previously issued report
 // is stale. The already returned certified snapshot must not change.
 h[0].open+=0.01;
 q[0].open+=0.01;
 assert.equal(auditCrtCrossTimeframe(h,q).checkedFourHourBars,2);
 assert.equal(certified[0].open,originalOpen);
 assert.throws(()=>{certified[0].open=originalOpen+0.01;},TypeError,
  'downstream code cannot silently rewrite certified evidence');
 assert.throws(()=>certifiedCrtFourHourBars(h,q,report),
  /Stale or inconsistent 4H\/15m certification report/);
});

test('a stale 4H/15m audit cannot certify edited historical OHLC',()=>{
 const x=fixture();
 const report=auditCrtCrossTimeframe(x.h,x.q);
 x.h[0].close+=0.01; // Still a valid 4H candle, but no longer agrees with 15m.
 assert.throws(()=>certifiedCrtFourHourBars(x.h,x.q,report),/Stale or inconsistent 4H\/15m certification report/);
 const y=fixture();
 const old=auditCrtCrossTimeframe(y.h,y.q);
 y.q[0].open+=0.01; // Valid 15m candle; invalidates the previously checked open.
 assert.throws(()=>certifiedCrtFourHourBars(y.h,y.q,old),/Stale or inconsistent 4H\/15m certification report/);
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

test('certification rejects coordinated post-audit edits even when both timeframes still reconcile',()=>{
 const x=fixture();
 const report=auditCrtCrossTimeframe(x.h,x.q);
 assert.deepEqual(certifiedCrtFourHourBars(x.h,x.q,report),x.h,
  'unchanged audited candles remain eligible');
 // Both aggregates are changed together: a fresh cross-timeframe audit still
 // succeeds, but the old report must not certify these replacement prices.
 x.h[0].open+=0.01;
 x.q[0].open+=0.01;
 assert.equal(auditCrtCrossTimeframe(x.h,x.q).checkedFourHourBars,2);
 assert.throws(()=>certifiedCrtFourHourBars(x.h,x.q,report),
  /Stale or inconsistent 4H\/15m certification report/);

 const y=fixture();
 y.q.forEach(b=>{b.volume=5;});
 y.h.forEach(b=>{b.volume=80;});
 const volumeReport=auditCrtCrossTimeframe(y.h,y.q);
 y.q[0].volume=6;
 y.h[0].volume=81;
 assert.equal(auditCrtCrossTimeframe(y.h,y.q).checkedFourHourBars,2);
 assert.throws(()=>certifiedCrtFourHourBars(y.h,y.q,volumeReport),
  /Stale or inconsistent 4H\/15m certification report/);
});

test('a copied audit report without its issued snapshot cannot certify candle inputs',()=>{
 const x=fixture();
 const report=auditCrtCrossTimeframe(x.h,x.q);
 assert.throws(()=>certifiedCrtFourHourBars(x.h,x.q,{...report}),
  /Stale or inconsistent 4H\/15m certification report/);
});

test('issued cross-timeframe audit report and verified timestamp list are immutable',()=>{
 const {h,q}=fixture();
 const report=auditCrtCrossTimeframe(h,q);
 assert.equal(Object.isFrozen(report),true);
 assert.equal(Object.isFrozen(report.verifiedFourHourStarts),true);
 assert.throws(()=>{(report as {checkedFourHourBars:number}).checkedFourHourBars=0;},TypeError);
 assert.throws(()=>{(report.verifiedFourHourStarts as number[])[0]=BASE+2*H4;},TypeError);
 assert.throws(()=>{(report.verifiedFourHourStarts as number[]).push(BASE+2*H4);},TypeError);
 assert.deepEqual(report.verifiedFourHourStarts,[BASE,BASE+H4]);
 assert.equal(certifiedCrtFourHourBars(h,q,report).length,2,
  'unchanged frozen reports remain valid for source re-audit');
});

test('certified CRT candles expose only audited Bar fields without evaluating extra metadata',()=>{
 const {h,q}=fixture();
 let extraReads=0;
 Object.defineProperty(h[0],'claimedFeedAuthentication',{
  enumerable:true,configurable:true,
  get(){extraReads++;throw Error('unaudited source metadata getter was evaluated');},
 });
 (h[1] as Bar&{claimedBrokerExecution?:boolean}).claimedBrokerExecution=true;
 const report=auditCrtCrossTimeframe(h,q);
 const certified=certifiedCrtFourHourBars(h,q,report);
 assert.equal(extraReads,0,'unverified metadata must never be read or copied');
 assert.deepEqual(Reflect.ownKeys(certified[0]),[
  'time','open','high','low','close','volume','observed_minutes',
 ]);
 assert.equal(Object.hasOwn(certified[1],'claimedBrokerExecution'),false);
 assert.deepEqual(certified.map(b=>b.time),[BASE,BASE+H4]);
 assert.equal(Object.isFrozen(certified[0]),true);
 assert.equal(Object.isFrozen(certified),true);
});
