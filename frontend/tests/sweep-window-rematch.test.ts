import {test} from 'node:test';
import assert from 'node:assert/strict';
import {rematchSweepsWithinWindows} from '../lib/sweep-window-rematch.ts';
import type {Bar,Detection} from '../lib/research.ts';
import type {ChronologicalBoundaries} from '../lib/sweep-chronological-audit.ts';
const base=Date.UTC(2025,0,6)/1000;
const HOUR=3600;
const bar=(i:number):Bar=>{const p=100+i*.01;return {
 time:base+i*HOUR,open:p,high:p+1,low:p-1,close:p+.005,volume:null,observed_minutes:60};};
const bars=(n=300)=>Array.from({length:n},(_,i)=>bar(i));
const event=(i:number,kind:'SELL-SIDE SWEEP'|'BUY-SIDE SWEEP'='SELL-SIDE SWEEP'):Detection=>({
 kind,direction:kind==='SELL-SIDE SWEEP'?'bullish observation':'bearish observation',
 observed_at:base+(i+1)*HOUR,reference_times:[base+i*HOUR],level:100,
 explanation:'synthetic',rule_version:'structure-research-v3'});
const boundaries:ChronologicalBoundaries={developmentStartUtc:base,developmentEndUtc:base+100*HOUR,
 validationEndUtc:base+200*HOUR,holdoutEndUtc:base+300*HOUR,embargoSeconds:0};
const cfg={datasetId:'source-hash',instrument:'NSXUSD-CFD',frame:'1H',horizonBars:1,costBps:5};

test('rematches controls within each window rather than reusing earlier-window controls',()=>{
 const report=rematchSweepsWithinWindows(bars(),[event(28),event(128),event(228)],cfg,boundaries);
 assert.deepEqual(report.windows.map(w=>w.matched),[1,1,1]);
 for(const w of report.windows){
  const p=w.pairs[0];
  assert.ok(p.control.observedAt>=w.startUtc);
  assert.ok(p.control.exitAt<=p.sweep.observedAt);
  assert.ok(p.sweep.exitAt<w.endUtc);
  assert.equal(new Date(p.control.observedAt*1000).getUTCHours(),new Date(p.sweep.observedAt*1000).getUTCHours());
  assert.equal(w.status,'INSUFFICIENT_EVIDENCE');
 }
 assert.match(report.warning,/NOT a genuinely untouched holdout/);
});
test('outcome crossing window boundary is pending rather than counted',()=>{
 const report=rematchSweepsWithinWindows(bars(),[event(98),event(128)],cfg,boundaries);
 assert.equal(report.windows[0].matched,0);
 assert.equal(report.windows[0].pending,1);
 assert.equal(report.windows[1].matched,1);
});
test('embargo prevents using prior-window controls and boundary labels',()=>{
 const report=rematchSweepsWithinWindows(bars(),[event(28),event(128),event(228)],cfg,
  {...boundaries,embargoSeconds:10*HOUR});
 assert.deepEqual(report.windows.map(w=>w.matched),[0,0,0]);
 assert.deepEqual(report.windows.map(w=>w.unmatched),[1,1,1]);
});
test('excludes incomplete controls and does not invent a baseline return',()=>{
 const data=bars();data[4]={...data[4],observed_minutes:59};
 const r=rematchSweepsWithinWindows(data,[event(28)],cfg,boundaries);
 assert.equal(r.windows[0].matched,0);
 assert.equal(r.windows[0].unmatched,1);
 assert.equal(r.windows[0].meanDifferenceBps,null);
});
test('results are deterministic, input-order invariant and read-only',()=>{
 const data=bars(),obs=[event(28),event(52),event(128),event(228)];
 const before=JSON.stringify({data,obs,boundaries});
 const a=rematchSweepsWithinWindows(data,obs,cfg,boundaries,'fixed-v1');
 const b=rematchSweepsWithinWindows(data,[...obs].reverse(),cfg,boundaries,'fixed-v1');
 assert.deepEqual(a,b);
 assert.equal(JSON.stringify({data,obs,boundaries}),before);
});
test('appending later candles cannot change earlier window pairs',()=>{
 const obs=[event(28),event(128)];
 const a=rematchSweepsWithinWindows(bars(230),obs,cfg,boundaries);
 const b=rematchSweepsWithinWindows(bars(300),obs,cfg,boundaries);
 assert.deepEqual(a.windows.slice(0,2),b.windows.slice(0,2));
});
test('rejects invalid time boundaries, unsupported frames, reversed bars and bad seed',()=>{
 assert.throws(()=>rematchSweepsWithinWindows(bars(),[],cfg,{...boundaries,holdoutEndUtc:base+180*HOUR}),/boundaries/);
 assert.throws(()=>rematchSweepsWithinWindows(bars(),[],cfg,{...boundaries,embargoSeconds:50*HOUR}),/embargo/);
 assert.throws(()=>rematchSweepsWithinWindows(bars(),[],{...cfg,frame:'9H'},boundaries),/Unsupported/);
 assert.throws(()=>rematchSweepsWithinWindows([bar(2),bar(1)],[],cfg,boundaries),/increasing/);
 assert.throws(()=>rematchSweepsWithinWindows(bars(),[],cfg,boundaries,' '),/seed/);
});
test('rejects invalid source identity, costs and event version in its own window',()=>{
 assert.throws(()=>rematchSweepsWithinWindows(bars(),[event(28)],{...cfg,datasetId:''},boundaries),/identity/);
 assert.throws(()=>rematchSweepsWithinWindows(bars(),[event(28)],{...cfg,costBps:-1},boundaries),/cost/);
 assert.throws(()=>rematchSweepsWithinWindows(bars(),[{...event(28),rule_version:'v2'}],cfg,boundaries),/causal v3/);
});
