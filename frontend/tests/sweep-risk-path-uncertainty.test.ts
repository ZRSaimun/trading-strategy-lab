import {test} from 'node:test';
import assert from 'node:assert/strict';
import {estimateConfluenceRiskPathUncertainty as audit} from '../lib/sweep-risk-path-uncertainty.ts';
import type {RiskPathReport,RiskPathTrade} from '../lib/sweep-confluence-risk-path.ts';
const WEEK=604800,BASE=Date.UTC(2025,0,6)/1000,COSTS=[0,5,15];
function report(n=40):RiskPathReport{
 const trades:RiskPathTrade[]=Array.from({length:n},(_,i)=>{
  const entryAt=BASE+i*WEEK,reason=i%4===0?'TARGET':i%4===1?'STOP':'TIME';
  const exit=reason==='TARGET'?102:reason==='STOP'?99:100;
  const grossBps=(exit/100-1)*10000;
  const netBps=COSTS.map(c=>grossBps-c);
  return {sweepAt:entryAt-3600,confirmationAt:entryAt,entryAt,exitAt:entryAt+3600,
   direction:'bullish',entry:100,stop:99,target:102,exit,reason,grossBps,
   netBps,netR:netBps.map(x=>x/100)};
 });
 const avg=(j:number,key:'netBps'|'netR')=>trades.length?trades.reduce((s,t)=>s+t[key][j],0)/trades.length:null;
 return {engine:'sweep-confluence-ohlc-risk-path-v1',datasetId:'sha-source-A',instrument:'NSXUSD-CFD',
  sourceEngine:'sweep-mss-fvg-same-close-v1',config:{atrPeriod:14,stopAtrMultiple:1,rewardRisk:2,maxHoldBars:3,roundTripCostsBps:COSTS},
  inputSignals:n,closed:n,pending:0,gapExcluded:0,warmupExcluded:0,overlapExcluded:0,priceExcluded:0,
  trades,meanNetBps:COSTS.map((_,j)=>avg(j,'netBps')),meanNetR:COSTS.map((_,j)=>avg(j,'netR')),warning:'synthetic'};
}
test('frozen 40-week results are reproducible and do not claim significance',()=>{
 const a=audit(report()),b=audit(report());assert.deepEqual(a,b);
 assert.equal(a.status,'DESCRIPTIVE_ONLY');assert.equal(a.weeks,40);assert.equal(a.trades,40);
 assert.equal(a.stopExits,10);assert.equal(a.targetExits,10);assert.equal(a.timeExits,20);
 assert.ok(a.scenarios[0].lower95NetBps!==null);
 assert.ok(Math.abs(a.scenarios[1].meanNetBps!-(a.scenarios[0].meanNetBps!-5))<1e-8);
 assert.ok(Math.abs(a.scenarios[2].meanNetBps!-(a.scenarios[0].meanNetBps!-15))<1e-8);
 assert.ok(a.warning.includes('multiple testing'));
});
test('insufficient independent weeks withhold confidence bounds',()=>{
 const r=audit(report(11));assert.equal(r.status,'INSUFFICIENT_EVIDENCE');
 assert.equal(r.scenarios[0].lower95NetBps,null);
});
test('empty report has null means, no fake profits',()=>{
 const r=audit(report(0));assert.equal(r.trades,0);assert.equal(r.weeks,0);
 assert.equal(r.scenarios[0].meanNetBps,null);
});
test('fails closed on tampered net cost and net R',()=>{
 const r=report();r.trades[0].netBps[1]+=1;
 assert.throws(()=>audit(r),/Inconsistent net/);
 const s=report();s.trades[0].netR[0]+=1;
 assert.throws(()=>audit(s),/Inconsistent net/);
});
test('fails closed on incorrect reported means and accounting',()=>{
 const r=report();r.meanNetBps[0]!+=1;
 assert.throws(()=>audit(r),/Reported mean/);
 const s=report();s.inputSignals++;
 assert.throws(()=>audit(s),/accounting/);
});
test('fails closed on overlapping or future-dated trade chronology',()=>{
 const r=report();r.trades[1].entryAt=r.trades[0].entryAt;
 assert.throws(()=>audit(r),/chronology/);
 const s=report();s.trades[0].sweepAt=s.trades[0].entryAt;
 assert.throws(()=>audit(s),/chronology/);
});
test('rejects fabricated stops, targets, prices and fills',()=>{
 const r=report();r.trades[0].target=105;
 assert.throws(()=>audit(r),/Inconsistent stop/);
 const s=report();s.trades[1].exit=100;
 assert.throws(()=>audit(s),/Inconsistent stop/);
 const u=report();u.trades[0].entry=-1;
 assert.throws(()=>audit(u),/Invalid trade prices/);
});
test('rejects mismatched identities, unsorted costs, invalid seed',()=>{
 const r=report();r.engine='invalid' as RiskPathReport['engine'];
 assert.throws(()=>audit(r),/identity/);
 const s=report();s.config.roundTripCostsBps=[5,0,15];
 assert.throws(()=>audit(s),/cost scenarios/);
 assert.throws(()=>audit(report(),' '),/seed/);
});
test('changing future weeks does not rewrite earlier descriptive mean',()=>{
 const small=audit(report(11));const big=audit(report(40));
 assert.ok(Math.abs(small.scenarios[0].meanNetBps!-report(11).meanNetBps[0]!)<1e-8);
 assert.equal(big.trades,40);
});
