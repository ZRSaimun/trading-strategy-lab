import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditRollingDirection} from '../lib/forecast-audit.ts';
import type {Bar} from '../lib/research.ts';
const base=1700000040;
const make=(n:number,close:number):Bar=>({time:base+n*60,open:close,high:close+1,low:close-1,close,volume:null,observed_minutes:1});
const bars=Array.from({length:180},(_,i)=>make(i,100+Math.sin(i/5)*4+i/20));
test('scores only matured next-close outcomes at three predeclared horizons',()=>{
 const r=auditRollingDirection(bars,60,40);
 assert.equal(r.status,'HISTORICAL AUDIT ONLY');
 assert.deepEqual(r.horizons.map(h=>h.horizon),[1,3,12]);
 for(const h of r.horizons){
  assert.equal(h.samples,180-40-2*h.horizon+1);
  assert.ok(h.brier!==null&&h.brier>=0&&h.brier<=1);
  assert.equal(h.baselineBrier,0.25);
  assert.equal(h.bins.reduce((n,b)=>n+b.count,0),h.samples);
  for(const s of h.recent){assert.equal(s.evaluatedAt-s.observedAt,h.horizon*60);assert.ok(s.probability>0&&s.probability<1)}
 }
});
test('future extension never changes already evaluated historical forecasts',()=>{
 const shorter=auditRollingDirection(bars.slice(0,120),60);
 const longer=auditRollingDirection(bars,60);
 for(let i=0;i<3;i++){
  const cut=shorter.horizons[i].lastEvaluatedAt!;
  assert.deepEqual(longer.horizons[i].evaluations.filter(s=>s.evaluatedAt<=cut),shorter.horizons[i].evaluations.filter(s=>s.evaluatedAt<=cut));
  assert.equal(shorter.horizons[i].samples,120-40-2*shorter.horizons[i].horizon+1);
 }
});
test('missing and partial bars split history rather than creating artificial predictions',()=>{
 const r=auditRollingDirection([...bars.slice(0,70),...bars.slice(71)],60);
 assert.equal(r.segments,2);
 assert.equal(r.horizons[2].samples,(70-40-24+1)+(109-40-24+1));
 const partial=bars.map((x,i)=>i===70?{...x,observed_minutes:0}:x);
 const q=auditRollingDirection(partial,60);
 assert.equal(q.segments,2);assert.equal(q.excludedBars,1);
 assert.equal(q.horizons[0].samples,r.horizons[0].samples);
});
test('flat closes are not falsely counted as upward moves; smoothing avoids 0/1 certainty',()=>{
 const r=auditRollingDirection(Array.from({length:100},(_,i)=>make(i,100)),60);
 const one=r.horizons[0];assert.ok(one.samples>0);
 assert.equal(one.recent[0].up,false);assert.equal(one.recent[0].probability,1/42);
 assert.ok(one.logLoss!==null&&Number.isFinite(one.logLoss));
});
test('no score or fake accuracy is reported when there is too little data',()=>{
 const r=auditRollingDirection(bars.slice(0,25),60);
 for(const h of r.horizons){assert.equal(h.samples,0);assert.equal(h.brier,null);assert.equal(h.brierSkill,null);assert.equal(h.calibrationError,null)}
});
test('rejects malformed data, unaligned frames and unsafe settings',()=>{
 assert.throws(()=>auditRollingDirection([bars[1],bars[0]],60),/unordered/);
 assert.throws(()=>auditRollingDirection([{...bars[0],close:Infinity}],60),/OHLC/);
 assert.throws(()=>auditRollingDirection([{...bars[0],time:bars[0].time+1}],60),/misaligned/);
 assert.throws(()=>auditRollingDirection(bars,60,5),/settings/);
 assert.throws(()=>auditRollingDirection(bars,90),/settings/);
});
