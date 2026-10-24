import {test} from 'node:test';
import assert from 'node:assert/strict';
import {summarizeRiskPathCostRegimes} from '../lib/sweep-risk-path-regime-stress.ts';
import type {RiskPathReport,RiskPathTrade} from '../lib/sweep-confluence-risk-path.ts';
const makeTrade=(date:string,exit:number):RiskPathTrade=>{
 const entryAt=Date.parse(date)/1000,grossBps=(exit/100-1)*10000,costs=[0,5,15];
 return {sweepAt:entryAt-7200,confirmationAt:entryAt,entryAt,exitAt:entryAt+3600,
  direction:'bullish',entry:100,stop:99,target:102,exit,
  reason:exit===102?'TARGET':exit<=99?'STOP':'TIME',grossBps,
  netBps:costs.map(c=>grossBps-c),netR:costs.map(c=>(grossBps-c)/100)};
};
function fixture():RiskPathReport{
 const trades=[makeTrade('2024-01-02T10:00:00Z',102),makeTrade('2024-02-02T10:00:00Z',99),makeTrade('2025-01-02T10:00:00Z',100.5)];
 return {engine:'sweep-confluence-ohlc-risk-path-v1',sourceEngine:'sweep-mss-fvg-same-close-v1',
  datasetId:'source-a',instrument:'NSXUSD-CFD',
  config:{atrPeriod:14,stopAtrMultiple:1,rewardRisk:2,maxHoldBars:3,roundTripCostsBps:[0,5,15]},
  inputSignals:3,closed:3,pending:0,gapExcluded:0,warmupExcluded:0,overlapExcluded:0,priceExcluded:0,
  trades,meanNetBps:[0,5,15].map((_,j)=>trades.reduce((a,x)=>a+x.netBps[j],0)/3),
  meanNetR:[0,5,15].map((_,j)=>trades.reduce((a,x)=>a+x.netR[j],0)/3),warning:''};
}
test('frozen annual regime and break-even are reproducible',()=>{
 const a=summarizeRiskPathCostRegimes(fixture());
 assert.deepEqual(a,summarizeRiskPathCostRegimes(fixture()));
 assert.equal(a.trades,3);assert.equal(a.eventWeeks,3);
 assert.deepEqual(a.annual.map(y=>[y.utcEntryYear,y.trades]),[[2024,2],[2025,1]]);
 assert.ok(Math.abs(a.meanBpsBreakevenCost!-50)<1e-8);
 assert.ok(Math.abs(a.meanRBreakevenCost!-50)<1e-8);
 assert.ok(Math.abs(a.scenarios[1].meanNetBps!-45)<1e-8);
});
test('drawdown is additive R and losses are counted causally',()=>{
 const a=summarizeRiskPathCostRegimes(fixture());
 assert.ok(Math.abs(a.scenarios[0].maxAdditiveRDrawdown!-1)<1e-8);
 assert.equal(a.scenarios[0].longestLosingRun,1);
 assert.equal(a.scenarios[0].positiveNetRate,2/3);
 assert.equal(a.annual[0].scenarios[0].positiveNetRate,.5);
});
test('empty studies have null means, costs and drawdown',()=>{
 const f=fixture();f.trades=[];f.closed=0;f.inputSignals=0;
 f.meanNetBps=[null,null,null];f.meanNetR=[null,null,null];
 const a=summarizeRiskPathCostRegimes(f);
 assert.equal(a.meanBpsBreakevenCost,null);assert.equal(a.meanRBreakevenCost,null);
 assert.equal(a.scenarios[0].maxAdditiveRDrawdown,null);assert.deepEqual(a.annual,[]);
});
test('negative gross expectancy cannot imply a positive cost budget',()=>{
 const f=fixture();f.trades=[makeTrade('2024-01-02T10:00:00Z',99)];
 f.closed=1;f.inputSignals=1;f.meanNetBps=[...f.trades[0].netBps];f.meanNetR=[...f.trades[0].netR];
 const a=summarizeRiskPathCostRegimes(f);
 assert.ok(a.meanBpsBreakevenCost!<0);assert.ok(a.meanRBreakevenCost!<0);
});
test('tampered cost, means and counters fail closed',()=>{
 const a=fixture();a.trades[0].netR[1]=5;
 assert.throws(()=>summarizeRiskPathCostRegimes(a),/Cost\/R/);
 const b=fixture();b.meanNetBps[0]=999;
 assert.throws(()=>summarizeRiskPathCostRegimes(b),/Reported means/);
 const c=fixture();c.pending=1;
 assert.throws(()=>summarizeRiskPathCostRegimes(c),/accounting/);
});
test('overlap and wrong source engine fail closed',()=>{
 const a=fixture();a.trades[1].entryAt=a.trades[0].entryAt;
 assert.throws(()=>summarizeRiskPathCostRegimes(a),/chronology/);
 const b=fixture();b.sourceEngine='other' as RiskPathReport['sourceEngine'];
 assert.throws(()=>summarizeRiskPathCostRegimes(b),/identity/);
});
test('stop geometry and invalid cost ordering fail closed',()=>{
 const a=fixture();a.trades[0].target=103;
 assert.throws(()=>summarizeRiskPathCostRegimes(a),/stop\/target/);
 const b=fixture();b.config.roundTripCostsBps=[0,5,5];
 assert.throws(()=>summarizeRiskPathCostRegimes(b),/costs/);
 const c=fixture();c.config.roundTripCostsBps=[-1,5,15];
 assert.throws(()=>summarizeRiskPathCostRegimes(c),/costs/);
});
test('gross returns and stop fills must reconcile with trade prices',()=>{
 const a=fixture();a.trades[1].exit=101;
 assert.throws(()=>summarizeRiskPathCostRegimes(a),/gross return|stop\/target/);
 const b=fixture();b.trades[0].grossBps=400;
 assert.throws(()=>summarizeRiskPathCostRegimes(b),/gross return/);
});