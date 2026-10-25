import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditMatchedSweepFriction} from '../lib/sweep-paired-friction-audit.ts';
import type {MatchedSweepComparison,MatchedSweepPair} from '../lib/sweep-matched-baseline.ts';
const DAY=86400,WEEK=7*DAY,MON=Date.UTC(2026,0,5)/1000;
function pair(i:number,grossSweep=9,grossControl=3):MatchedSweepPair{
 const observedAt=MON+i*WEEK+3*DAY;
 const mk=(time:number,gross:number)=>({observedAt:time,entryAt:time+60,exitAt:time+120,
  entry:100,exit:100*(1+gross/10000),grossBps:gross,netBps:gross-5,
  kind:'SELL-SIDE SWEEP' as const,direction:'bullish' as const});
 const sweep=mk(observedAt,grossSweep),control=mk(observedAt-180,grossControl);
 return {sweep,control,differenceBps:sweep.netBps-control.netBps};
}
function fixture(pairs:MatchedSweepPair[]):MatchedSweepComparison{
 const mean=(f:(p:MatchedSweepPair)=>number)=>pairs.length?pairs.reduce((s,p)=>s+f(p),0)/pairs.length:null;
 return {datasetId:'immutable-sha-abc',instrument:'NSXUSD-CFD',frame:'1H',horizonBars:1,
  costBps:5,seed:'locked',matched:pairs.length,unmatched:0,pending:0,gapExcluded:0,priceExcluded:0,
  pairs,meanSweepNetBps:mean(p=>p.sweep.netBps),meanControlNetBps:mean(p=>p.control.netBps),
  meanDifferenceBps:mean(p=>p.differenceBps),warning:'synthetic'};
}
test('fixed asymmetric cost grid and symmetric cost cancellation',()=>{
 const a=auditMatchedSweepFriction(fixture(Array.from({length:36},(_,i)=>pair(i))));
 assert.equal(a.status,'DESCRIPTIVE_ONLY');assert.equal(a.activeUtcWeeks,36);
 assert.equal(a.rows[0].eventMeanDifferenceBps,6);
 assert.equal(a.rows[1].eventMeanDifferenceBps,6);
 assert.equal(a.rows[2].eventMeanDifferenceBps,4);
 assert.equal(a.rows[3].eventMeanDifferenceBps,1);
 assert.equal(a.rows[4].eventMeanDifferenceBps,-4);
 assert.equal(a.eventWeightedBreakEvenExtraSweepBps,6);
 assert.equal(a.rows[4].positiveWeekFraction,0);
});
test('missing evidence reports nulls, not zero or profit',()=>{
 const a=auditMatchedSweepFriction(fixture([]));
 assert.equal(a.status,'INSUFFICIENT_EVIDENCE');assert.equal(a.eventWeightedBreakEvenExtraSweepBps,null);
 assert.equal(a.rows[0].eventMeanDifferenceBps,null);assert.equal(a.rows[0].positiveWeekFraction,null);
});
test('insufficient weeks cannot be hidden by trade count',()=>{
 const p=Array.from({length:35},(_,i)=>pair(i));
 for(let i=0;i<p.length;i++){
  const d=(i-Math.floor(i/6))*WEEK;
  p[i]={...p[i],sweep:{...p[i].sweep,observedAt:p[i].sweep.observedAt-d,entryAt:p[i].sweep.entryAt-d,exitAt:p[i].sweep.exitAt-d},
   control:{...p[i].control,observedAt:p[i].control.observedAt-d,entryAt:p[i].control.entryAt-d,exitAt:p[i].control.exitAt-d}};
 }
 assert.throws(()=>auditMatchedSweepFriction(fixture(p)),/Duplicate matched sweep/);
 const a=auditMatchedSweepFriction(fixture(Array.from({length:11},(_,i)=>pair(i))));
 assert.equal(a.status,'INSUFFICIENT_EVIDENCE');
 assert.equal(a.eventWeightedBreakEvenExtraSweepBps,null);
});
test('input order cannot change the result',()=>{
 const p=Array.from({length:35},(_,i)=>pair(i,10+i%3,2));
 assert.deepEqual(auditMatchedSweepFriction(fixture(p)),auditMatchedSweepFriction(fixture([...p].reverse())));
});
test('rejects future-matured control',()=>{
 const p=pair(0);p.control.exitAt=p.sweep.observedAt+1;
 assert.throws(()=>auditMatchedSweepFriction(fixture([p])),/chronology/);
});
test('rejects corrupted gross/net or inconsistent paired difference',()=>{
 const p=pair(0);p.sweep.netBps=900;
 assert.throws(()=>auditMatchedSweepFriction(fixture([p])),/arithmetic/);
 const q=pair(0);q.differenceBps=99;
 assert.throws(()=>auditMatchedSweepFriction(fixture([q])),/difference/);
});
test('rejects source aggregate tampering',()=>{
 const c=fixture([pair(0)]);c.meanDifferenceBps=999;
 assert.throws(()=>auditMatchedSweepFriction(c),/aggregate/);
});
test('rejects duplicate controls and duplicate sweeps',()=>{
 const p=pair(0),q=pair(1);
 q.control={...q.control,observedAt:p.control.observedAt};
 assert.throws(()=>auditMatchedSweepFriction(fixture([p,q])),/Duplicate/);
});
test('rejects missing identities, negative or nonfinite costs, invalid direction',()=>{
 const a=fixture([pair(0)]);a.seed=' ';assert.throws(()=>auditMatchedSweepFriction(a),/identity/);
 const b=fixture([pair(0)]);b.costBps=-1;assert.throws(()=>auditMatchedSweepFriction(b),/cost/);
 const c=fixture([pair(0)]);c.pairs[0].sweep.direction='bearish';assert.throws(()=>auditMatchedSweepFriction(c),/direction/);
});
test('baseline negative difference yields no fictitious positive break-even threshold',()=>{
 const a=auditMatchedSweepFriction(fixture(Array.from({length:36},(_,i)=>pair(i,1,3))));
 assert.equal(a.eventWeightedBreakEvenExtraSweepBps,null);
 assert.ok(a.rows.every(r=>r.eventMeanDifferenceBps!==null&&r.eventMeanDifferenceBps<=0));
});
