import {test} from 'node:test';
import assert from 'node:assert/strict';
import {estimateSweepDifferenceUncertainty} from '../lib/sweep-uncertainty.ts';
import type {MatchedSweepComparison,MatchedSweepPair} from '../lib/sweep-matched-baseline.ts';
const monday=Date.UTC(2025,0,6)/1000;
function pair(i:number,differenceBps:number):MatchedSweepPair{
 const observedAt=monday+i*604800+7200;
 const sweep={observedAt,kind:'SELL-SIDE SWEEP' as const,direction:'bullish' as const,
  entryAt:observedAt,exitAt:observedAt+3600,entry:100,exit:100,grossBps:differenceBps,netBps:differenceBps};
 const control={...sweep,observedAt:observedAt-604800,entryAt:observedAt-604800,exitAt:observedAt-604800+3600,grossBps:0,netBps:0};
 return {sweep,control,differenceBps};
}
function comparison(pairs:MatchedSweepPair[]):MatchedSweepComparison{return {
 datasetId:'sha-verified',instrument:'XAUUSD-OTC',frame:'1H',horizonBars:1,costBps:5,seed:'locked',
 matched:pairs.length,unmatched:0,pending:0,gapExcluded:0,priceExcluded:0,pairs,
 meanSweepNetBps:null,meanControlNetBps:null,meanDifferenceBps:null,warning:'synthetic'
}}
test('insufficient pairs or weeks never yield a confidence interval',()=>{
 const small=estimateSweepDifferenceUncertainty(comparison(Array.from({length:14},(_,i)=>pair(i,2))));
 assert.equal(small.status,'INSUFFICIENT_EVIDENCE');assert.equal(small.lower95Bps,null);
 assert.equal(small.weeks,14);assert.equal(small.meanDifferenceBps,2);
 const none=estimateSweepDifferenceUncertainty(comparison([]));
 assert.equal(none.meanDifferenceBps,null);assert.equal(none.weeks,0);
});
test('deterministic interval preserves constant paired differences',()=>{
 const data=comparison(Array.from({length:40},(_,i)=>pair(i,3)));
 const a=estimateSweepDifferenceUncertainty(data),b=estimateSweepDifferenceUncertainty(data);
 assert.deepEqual(a,b);assert.equal(a.status,'DESCRIPTIVE_ONLY');
 assert.equal(a.lower95Bps,3);assert.equal(a.upper95Bps,3);
});
test('negative clustered differences remain negative under resampling',()=>{
 const a=estimateSweepDifferenceUncertainty(comparison(Array.from({length:40},(_,i)=>pair(i,-7))));
 assert.equal(a.lower95Bps,-7);assert.equal(a.upper95Bps,-7);
});
test('bootstrap respects whole-week clusters and never mutates input',()=>{
 const data=comparison(Array.from({length:50},(_,i)=>pair(i,i%5===0?40:-10)));
 const snapshot=JSON.stringify(data);
 const a=estimateSweepDifferenceUncertainty(data,'seed-one');
 const b=estimateSweepDifferenceUncertainty(data,'seed-two');
 assert.equal(JSON.stringify(data),snapshot);
 assert.equal(a.meanDifferenceBps,0);
 assert.ok(a.lower95Bps!<=a.meanDifferenceBps!);
 assert.ok(a.upper95Bps!>=a.meanDifferenceBps!);
 assert.ok(b.lower95Bps!==null&&b.upper95Bps!==null);
});
test('rejects duplicate sweeps, unmatured controls and forged return differences',()=>{
 const a=pair(0,1),b=pair(1,2);
 assert.throws(()=>estimateSweepDifferenceUncertainty(comparison([a,a])),/duplicate/);
 assert.throws(()=>estimateSweepDifferenceUncertainty(comparison([{...a,control:{...a.control,exitAt:a.sweep.observedAt+1}}])),/chronology/);
 assert.throws(()=>estimateSweepDifferenceUncertainty(comparison([{...a,differenceBps:10}])),/inconsistent/);
 assert.throws(()=>estimateSweepDifferenceUncertainty(comparison([{...a,differenceBps:Infinity}])),/Nonfinite/);
 assert.throws(()=>estimateSweepDifferenceUncertainty({...comparison([a,b]),matched:3}),/count/);
});
test('rejects missing identity, invalid seed and overflowing arithmetic',()=>{
 const a=pair(0,1);
 assert.throws(()=>estimateSweepDifferenceUncertainty({...comparison([a]),datasetId:' '}),/identity/);
 assert.throws(()=>estimateSweepDifferenceUncertainty(comparison([a]),' '),/seed/);
 const huge=comparison([pair(0,1e308),pair(1,1e308)]);
 assert.throws(()=>estimateSweepDifferenceUncertainty(huge),/Overflowed/);
});
test('multiple events within a week count as one dependence cluster',()=>{
 const ps=Array.from({length:10},(_,i)=>[pair(i,1),pair(i,2)]).flat();
 const distinct=ps.map((p,i)=>i%2===0?p:{...p,sweep:{...p.sweep,observedAt:p.sweep.observedAt+7200,entryAt:p.sweep.entryAt+7200,exitAt:p.sweep.exitAt+7200}});
 const r=estimateSweepDifferenceUncertainty(comparison(distinct));
 assert.equal(r.weeks,10);assert.equal(r.matched,20);
 assert.equal(r.status,'INSUFFICIENT_EVIDENCE');
});
test('pair input ordering does not affect interval or paired mean',()=>{
 const data=comparison(Array.from({length:40},(_,i)=>pair(i,i%3?1:-4)));
 const a=estimateSweepDifferenceUncertainty(data);
 const b=estimateSweepDifferenceUncertainty(comparison([...data.pairs].reverse()));
 assert.equal(a.meanDifferenceBps,b.meanDifferenceBps);
 assert.equal(a.lower95Bps,b.lower95Bps);
 assert.equal(a.upper95Bps,b.upper95Bps);
});
