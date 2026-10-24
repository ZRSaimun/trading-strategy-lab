import {test} from 'node:test';
import assert from 'node:assert/strict';
import {compareSweepsToPastHourControls} from '../lib/sweep-matched-baseline.ts';
import type {Bar,Detection} from '../lib/research.ts';
const base=Date.UTC(2026,9,19)/1000;
const mk=(i:number):Bar=>{const p=100+i*.1;return {time:base+i*3600,open:p,high:p+1,low:p-1,close:p+.05,volume:null,observed_minutes:60}};
const bars=(n=80)=>Array.from({length:n},(_,i)=>mk(i));
const event=(i:number,kind:'SELL-SIDE SWEEP'|'BUY-SIDE SWEEP'='SELL-SIDE SWEEP'):Detection=>({
 kind,direction:kind==='SELL-SIDE SWEEP'?'bullish observation':'bearish observation',
 observed_at:base+(i+1)*3600,reference_times:[base],level:100,explanation:'synthetic',rule_version:'structure-research-v3'
});
const cfg={datasetId:'sha-immutable',instrument:'XAUUSD-OTC',frame:'1H',horizonBars:1,costBps:5};
test('matches only earlier matured controls at the same UTC close-hour and direction',()=>{
 const r=compareSweepsToPastHourControls(bars(),[event(28),event(29,'BUY-SIDE SWEEP')],cfg);
 assert.equal(r.matched,2);assert.equal(r.unmatched,0);
 for(const p of r.pairs){
  assert.ok(p.control.exitAt<=p.sweep.observedAt);
  assert.equal(new Date(p.control.observedAt*1000).getUTCHours(),new Date(p.sweep.observedAt*1000).getUTCHours());
  assert.equal(p.control.direction,p.sweep.direction);
  assert.equal(p.differenceBps,p.sweep.netBps-p.control.netBps);
 }
});
test('a sweep before any eligible same-hour history is unmatched, not a zero-return control',()=>{
 const r=compareSweepsToPastHourControls(bars(35),[event(4)],cfg);
 assert.equal(r.matched,0);assert.equal(r.unmatched,1);assert.equal(r.meanDifferenceBps,null);
});
test('controls are unique, and observed sweep bars cannot become controls',()=>{
 const r=compareSweepsToPastHourControls(bars(),[event(28),event(52)],cfg);
 assert.equal(r.matched,1);assert.equal(r.unmatched,1);
 assert.ok(!r.pairs.some(p=>p.control.observedAt===event(28).observed_at));
 assert.equal(new Set(r.pairs.map(p=>p.control.observedAt)).size,r.matched);
});
test('selection is deterministic and cannot depend on later appended candles',()=>{
 const a=compareSweepsToPastHourControls(bars(60),[event(28)],cfg,'locked-seed');
 const b=compareSweepsToPastHourControls(bars(80),[event(28)],cfg,'locked-seed');
 assert.deepEqual(a.pairs,b.pairs);
 assert.deepEqual(a.pairs,compareSweepsToPastHourControls(bars(60),[event(28)],cfg,'locked-seed').pairs);
});
test('input event ordering cannot change selected controls or results',()=>{
 const a=compareSweepsToPastHourControls(bars(),[event(28),event(29,'BUY-SIDE SWEEP')],cfg);
 const b=compareSweepsToPastHourControls(bars(),[event(29,'BUY-SIDE SWEEP'),event(28)],cfg);
 assert.deepEqual(a.pairs,b.pairs);
});
test('changing the common cost changes both net returns equally but not matched advantage',()=>{
 const a=compareSweepsToPastHourControls(bars(),[event(28)],cfg);
 const b=compareSweepsToPastHourControls(bars(),[event(28)],{...cfg,costBps:50});
 assert.ok(Math.abs(a.meanDifferenceBps!-b.meanDifferenceBps!)<1e-9);
 assert.ok(Math.abs((a.meanSweepNetBps!-b.meanSweepNetBps!)-45)<1e-9);
 assert.ok(Math.abs((a.meanControlNetBps!-b.meanControlNetBps!)-45)<1e-9);
});
test('missing or partial horizon data is never used as a baseline label',()=>{
 const bad=bars();bad[5]={...bad[5],observed_minutes:30};
 const r=compareSweepsToPastHourControls(bad,[event(28)],cfg);
 assert.equal(r.matched,0);assert.equal(r.unmatched,1);
 const gap=bars();gap[5]={...gap[5],time:gap[5].time+60};
 assert.equal(compareSweepsToPastHourControls(gap,[event(28)],cfg).matched,0);
});
test('rejects overflowing control returns rather than contaminating averages',()=>{
 const extreme=bars();extreme[5]={...extreme[5],open:1e-300,low:1e-300,close:1e300,high:1e300};
 const r=compareSweepsToPastHourControls(extreme,[event(28)],cfg);
 assert.equal(r.matched,0);assert.equal(r.unmatched,1);
});
test('pending sweep outcomes are not matched using future candles',()=>{
 const r=compareSweepsToPastHourControls(bars(30),[event(29)],cfg);
 assert.equal(r.pending,1);assert.equal(r.matched,0);assert.equal(r.unmatched,0);
});
test('rejects non-v3 events, invalid seeds and invalid source/cost configuration',()=>{
 assert.throws(()=>compareSweepsToPastHourControls(bars(),[{...event(28),rule_version:'v2'}],cfg),/causal v3/);
 assert.throws(()=>compareSweepsToPastHourControls(bars(),[event(28)],cfg,' '),/seed/);
 assert.throws(()=>compareSweepsToPastHourControls(bars(),[event(28)],{...cfg,costBps:-1}),/cost/);
 assert.throws(()=>compareSweepsToPastHourControls(bars(),[event(28)],{...cfg,datasetId:''}),/identity/);
});
