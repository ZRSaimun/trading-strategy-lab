import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditMatchedSweepsChronologically,type ChronologicalBoundaries} from '../lib/sweep-chronological-audit.ts';
import type {MatchedSweepComparison,MatchedSweepPair} from '../lib/sweep-matched-baseline.ts';
const DAY=86400;
const start=Date.UTC(2025,0,6)/1000;
const bounds:ChronologicalBoundaries={developmentStartUtc:start,developmentEndUtc:start+90*DAY,
 validationEndUtc:start+180*DAY,holdoutEndUtc:start+270*DAY,embargoSeconds:0};
function pair(day:number,controlDay:number,difference=2,exitOffset=7200):MatchedSweepPair{
 const observedAt=start+day*DAY+3600,controlAt=start+controlDay*DAY+3600;
 const sweep={observedAt,entryAt:observedAt,exitAt:observedAt+exitOffset,
  kind:'SELL-SIDE SWEEP' as const,direction:'bullish' as const,entry:100,exit:100,grossBps:difference+5,netBps:difference+5};
 const control={...sweep,observedAt:controlAt,entryAt:controlAt,exitAt:controlAt+7200,
  grossBps:5,netBps:5};
 return {sweep,control,differenceBps:difference};
}
function comparison(pairs:MatchedSweepPair[]):MatchedSweepComparison{return {
 datasetId:'immutable-source',instrument:'NSXUSD-CFD',frame:'1H',horizonBars:2,costBps:5,seed:'locked-v1',
 matched:pairs.length,unmatched:0,pending:0,gapExcluded:0,priceExcluded:0,pairs,
 meanSweepNetBps:null,meanControlNetBps:null,meanDifferenceBps:null,warning:'synthetic'
}}
test('uses explicit half-open windows and excludes controls from prior splits',()=>{
 const p=[pair(10,9),pair(91,89),pair(100,99),pair(181,179),pair(200,199)];
 const a=auditMatchedSweepsChronologically(comparison(p),bounds);
 assert.deepEqual(a.windows.map(w=>w.matched),[1,1,1]);
 assert.equal(a.crossWindowControlExcluded,2);
 assert.equal(a.windows[1].meanDifferenceBps,2);
 assert.equal(a.windows[2].status,'INSUFFICIENT_EVIDENCE');
});
test('purges labels crossing an end boundary and optional embargo neighborhoods',()=>{
 const a=auditMatchedSweepsChronologically(comparison([
  pair(89,88,2,DAY+7200),pair(87,86),pair(92,91),pair(176,175),pair(181,180)
 ]),{...bounds,embargoSeconds:2*DAY});
 assert.deepEqual(a.windows.map(w=>w.matched),[1,1,0]);
 assert.equal(a.boundaryPurged,3);
});
test('rejects impossible chronological splits and excessive embargo',()=>{
 assert.throws(()=>auditMatchedSweepsChronologically(comparison([]),{...bounds,validationEndUtc:bounds.developmentEndUtc}),/boundaries/);
 assert.throws(()=>auditMatchedSweepsChronologically(comparison([]),{...bounds,embargoSeconds:45*DAY}),/embargo/);
 assert.throws(()=>auditMatchedSweepsChronologically(comparison([]),{...bounds,holdoutEndUtc:Infinity}),/boundaries/);
});
test('requires mature prior controls and rejects duplicates or forged returns',()=>{
 const a=pair(20,19),b=pair(22,21);
 assert.throws(()=>auditMatchedSweepsChronologically(comparison([{...a,control:{...a.control,exitAt:a.sweep.observedAt+1}}]),bounds),/chronology/);
 assert.throws(()=>auditMatchedSweepsChronologically(comparison([a,a]),bounds),/Duplicate/);
 assert.throws(()=>auditMatchedSweepsChronologically(comparison([a,{...b,control:a.control,differenceBps:b.sweep.netBps-a.control.netBps}]),bounds),/Duplicate/);
 assert.throws(()=>auditMatchedSweepsChronologically(comparison([{...a,differenceBps:12}]),bounds),/inconsistent/);
 assert.throws(()=>auditMatchedSweepsChronologically(comparison([{...a,differenceBps:Infinity}]),bounds),/Nonfinite/);
});
test('is order-invariant, read-only and explicitly not an untouched holdout',()=>{
 const ps=[pair(10,9,1),pair(110,109,-3),pair(200,199,5)];
 const data=comparison(ps),snapshot=JSON.stringify(data);
 const a=auditMatchedSweepsChronologically(data,bounds);
 const b=auditMatchedSweepsChronologically(comparison([...ps].reverse()),bounds);
 assert.deepEqual(a,b);assert.equal(JSON.stringify(data),snapshot);
 assert.match(a.warning,/NOT a genuinely untouched holdout/);
 assert.deepEqual(a.windows.map(w=>w.meanDifferenceBps),[1,-3,5]);
});
test('reports minimum evidence threshold without calling any split profitable',()=>{
 const ps=Array.from({length:45},(_,i)=>pair(1+i*2,i*2,1));
 const a=auditMatchedSweepsChronologically(comparison(ps),bounds);
 assert.equal(a.windows[0].matched,45);
 assert.ok(a.windows[0].weeks>=12);
 assert.equal(a.windows[0].status,'EXPLORATORY_ONLY');
 assert.equal(a.windows[1].status,'INSUFFICIENT_EVIDENCE');
});
test('rejects invalid source identity, pair count and overflowing return sum',()=>{
 const p=pair(10,9);
 assert.throws(()=>auditMatchedSweepsChronologically({...comparison([p]),instrument:' '},bounds),/identity|source/);
 assert.throws(()=>auditMatchedSweepsChronologically({...comparison([p]),matched:2},bounds),/count/);
 const huge=pair(10,9,1e308);
 const huge2=pair(12,11,1e308);
 assert.throws(()=>auditMatchedSweepsChronologically(comparison([huge,huge2]),bounds),/Overflowed/);
});
