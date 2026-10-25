import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditFrozenWeekSignSymmetry} from '../lib/sweep-week-sign-symmetry-stress.ts';
import type {RiskPathReport,RiskPathTrade} from '../lib/sweep-confluence-risk-path.ts';

const H=3600,WEEK=604800,START=Date.UTC(2025,0,6,12)/1000,COSTS=[0,5,15];
function trade(at:number,gain:number):RiskPathTrade{
 const grossBps=gain*100;
 return {sweepAt:at-2*H,confirmationAt:at,entryAt:at,exitAt:at+H,
  direction:'bullish',entry:100,stop:99,target:102,exit:100+gain,
  reason:'TIME',grossBps,netBps:COSTS.map(c=>grossBps-c),
  netR:COSTS.map(c=>(grossBps-c)/100)};
}
function fixture(gains:number[],perWeek=3):RiskPathReport{
 const trades:RiskPathTrade[]=[];
 for(let w=0;w<gains.length;w++)for(let k=0;k<perWeek;k++)
  trades.push(trade(START+w*WEEK+k*2*H,gains[w]));
 return {engine:'sweep-confluence-ohlc-risk-path-v1',
  sourceEngine:'sweep-mss-fvg-same-close-v1',datasetId:'archive-a',instrument:'NSXUSD-CFD',
  config:{atrPeriod:14,stopAtrMultiple:1,rewardRisk:2,maxHoldBars:3,roundTripCostsBps:[...COSTS]},
  inputSignals:trades.length,closed:trades.length,pending:0,gapExcluded:0,
  warmupExcluded:0,overlapExcluded:0,priceExcluded:0,trades,
  meanNetBps:COSTS.map((_,j)=>trades.length?trades.reduce((s,t)=>s+t.netBps[j],0)/trades.length:null),
  meanNetR:COSTS.map((_,j)=>trades.length?trades.reduce((s,t)=>s+t.netR[j],0)/trades.length:null),
  warning:'synthetic'};
}
test('exact enumeration includes both tails for twelve same-sign weeks',()=>{
 const a=auditFrozenWeekSignSymmetry(fixture(Array(12).fill(.2)));
 assert.equal(a.status,'DESCRIPTIVE_ONLY');assert.equal(a.enumeration,'EXACT');
 assert.equal(a.draws,4096);assert.equal(a.trades,36);assert.equal(a.utcWeeks,12);
 assert.ok(Math.abs(a.observedEqualWeekMeanNetR!-.15)<1e-10);
 assert.equal(a.nullAbsoluteTailFraction,2/4096);
 assert.ok(a.null95ReferenceR![0]<0&&a.null95ReferenceR![1]>0);
 assert.equal(a.eligibleForLiveTrading,false);
});
test('opposite-signed balanced weeks have null reference tail fraction one',()=>{
 const a=auditFrozenWeekSignSymmetry(fixture([...Array(6).fill(.2),...Array(6).fill(-.1)]));
 assert.ok(Math.abs(a.observedEqualWeekMeanNetR!)<1e-10);
 assert.equal(a.nullAbsoluteTailFraction,1);
});
test('concentration reveals one week dominating absolute week means',()=>{
 const a=auditFrozenWeekSignSymmetry(fixture([...Array(11).fill(.05),.55]));
 assert.ok(Math.abs(a.maxWeekAbsoluteContributionShare!-1)<1e-10);
});
test('seeded Monte Carlo above sixteen weeks is deterministic',()=>{
 const r=fixture(Array(17).fill(.2));
 const a=auditFrozenWeekSignSymmetry(r);
 assert.equal(a.draws,8192);assert.equal(a.enumeration,'SEEDED_MONTE_CARLO');
 assert.deepEqual(a,auditFrozenWeekSignSymmetry(r));
});
test('withholds all effects when fewer than twelve UTC weeks',()=>{
 const a=auditFrozenWeekSignSymmetry(fixture(Array(11).fill(.2)));
 assert.equal(a.withheldReason,'TOO_FEW_WEEKS');
 assert.equal(a.observedEqualWeekMeanNetR,null);assert.equal(a.null95ReferenceR,null);
 assert.equal(a.draws,0);
});
test('withholds all effects when fewer than thirty completed paths',()=>{
 const a=auditFrozenWeekSignSymmetry(fixture(Array(12).fill(.2),2));
 assert.equal(a.withheldReason,'TOO_FEW_TRADES');assert.equal(a.nullAbsoluteTailFraction,null);
});
test('empty report never invents return evidence',()=>{
 const a=auditFrozenWeekSignSymmetry(fixture([]));
 assert.equal(a.trades,0);assert.equal(a.utcWeeks,0);assert.equal(a.status,'WITHHELD');
});
test('source and cost tampering fail closed',()=>{
 const a=fixture(Array(12).fill(.2));a.sourceEngine='incorrect' as RiskPathReport['sourceEngine'];
 assert.throws(()=>auditFrozenWeekSignSymmetry(a),/identity/);
 const b=fixture(Array(12).fill(.2));b.trades[0].netR[1]=999;
 assert.throws(()=>auditFrozenWeekSignSymmetry(b),/Cost\/R/);
});
test('frozen five-bps scenario is mandatory',()=>{
 const r=fixture(Array(12).fill(.2));
 r.config.roundTripCostsBps=[0,15];
 for(const t of r.trades){t.netBps=[t.netBps[0],t.netBps[2]];t.netR=[t.netR[0],t.netR[2]]}
 r.meanNetBps=[r.meanNetBps[0],r.meanNetBps[2]];
 r.meanNetR=[r.meanNetR[0],r.meanNetR[2]];
 assert.throws(()=>auditFrozenWeekSignSymmetry(r),/5 bps/);
});
test('overlapping hypothetical positions fail closed',()=>{
 const r=fixture(Array(12).fill(.2));r.trades[1].entryAt=r.trades[0].entryAt;
 assert.throws(()=>auditFrozenWeekSignSymmetry(r),/chronology/);
});
