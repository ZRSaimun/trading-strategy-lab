import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditConfluenceWeekInfluence} from '../lib/sweep-risk-path-week-influence.ts';
import type {RiskPathReport,RiskPathTrade} from '../lib/sweep-confluence-risk-path.ts';

const WEEK=604800,MONDAY=345600;
function fixture(weeks=12,perWeek=3,exceptionalWeek=-1):RiskPathReport{
 const costs=[0,5,15],trades:RiskPathTrade[]=[];
 for(let w=0;w<weeks;w++)for(let k=0;k<perWeek;k++){
  const entryAt=MONDAY+(2800+w)*WEEK+k*86400+3600;
  const grossBps=w===exceptionalWeek?200:10;
  const entry=100,stop=99,target=102,exit=100+grossBps/100;
  trades.push({sweepAt:entryAt-7200,confirmationAt:entryAt,entryAt,
   exitAt:entryAt+3600,direction:'bullish',entry,stop,target,exit,reason:'TIME',
   grossBps,netBps:costs.map(c=>grossBps-c),
   netR:costs.map(c=>(grossBps-c)/100)});
 }
 const avg=(j:number,field:'netBps'|'netR')=>trades.length?
  trades.reduce((s,t)=>s+t[field][j],0)/trades.length:null;
 return {engine:'sweep-confluence-ohlc-risk-path-v1',
  datasetId:'immutable-test-source',instrument:'NSXUSD-CFD',
  sourceEngine:'sweep-mss-fvg-same-close-v1',
  config:{atrPeriod:14,stopAtrMultiple:1,rewardRisk:2,maxHoldBars:3,roundTripCostsBps:costs},
  inputSignals:trades.length,closed:trades.length,pending:0,gapExcluded:0,
  warmupExcluded:0,overlapExcluded:0,priceExcluded:0,trades,
  meanNetBps:costs.map((_,j)=>avg(j,'netBps')),
  meanNetR:costs.map((_,j)=>avg(j,'netR')),warning:''};
}
test('single exceptional UTC week has the largest leave-one-out influence',()=>{
 const r=auditConfluenceWeekInfluence(fixture(12,3,4));
 assert.equal(r.status,'DESCRIPTIVE_ONLY');
 assert.equal(r.eventWeeks,12);assert.equal(r.trades,36);
 assert.ok(Math.abs(r.largestWeekTradeShare!-1/12)<1e-12);
 assert.equal(r.scenarios[1].mostInfluentialWeekStartUtc,MONDAY+(2800+4)*WEEK);
 assert.ok(Math.abs(r.scenarios[1].worstLeaveOneWeekMeanR!-0.05)<1e-10);
 assert.ok(r.scenarios[1].largestAbsoluteShiftR!>0);
});
test('all-identical weeks have no leave-one-out effect',()=>{
 const r=auditConfluenceWeekInfluence(fixture());
 for(const s of r.scenarios){
  assert.ok(Math.abs(s.largestAbsoluteShiftR!)<1e-10);
  assert.equal(s.signFlipCount,0);
 }
});
test('withhold influence diagnostics for fewer than 30 paths',()=>{
 const r=auditConfluenceWeekInfluence(fixture(12,2));
 assert.equal(r.status,'INSUFFICIENT_EVIDENCE');
 assert.equal(r.scenarios[0].largestAbsoluteShiftR,null);
 assert.equal(r.scenarios[0].signFlipCount,null);
});
test('withhold diagnostics for fewer than 12 distinct UTC weeks',()=>{
 const r=auditConfluenceWeekInfluence(fixture(11,3));
 assert.equal(r.status,'INSUFFICIENT_EVIDENCE');
 assert.equal(r.eventWeeks,11);
});
test('empty valid report does not invent a return or week share',()=>{
 const r=auditConfluenceWeekInfluence(fixture(0,0));
 assert.equal(r.trades,0);assert.equal(r.largestWeekTradeShare,null);
 assert.equal(r.scenarios[0].meanNetR,null);
});
test('frozen inputs produce deterministic identical outputs',()=>{
 assert.deepEqual(auditConfluenceWeekInfluence(fixture(12,3,2)),
  auditConfluenceWeekInfluence(fixture(12,3,2)));
});
test('tampered cost arithmetic is rejected by independent source auditor',()=>{
 const f=fixture();f.trades[0].netR[1]=100;
 assert.throws(()=>auditConfluenceWeekInfluence(f),/Cost\/R arithmetic mismatch/);
});
test('mixed source engine and overlapping trades fail closed',()=>{
 const f=fixture();f.sourceEngine='other' as RiskPathReport['sourceEngine'];
 assert.throws(()=>auditConfluenceWeekInfluence(f),/identity/);
 const g=fixture();g.trades[1].entryAt=g.trades[0].entryAt;
 assert.throws(()=>auditConfluenceWeekInfluence(g),/chronology/);
});
