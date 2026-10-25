import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditConfluenceRiskPathAttrition} from '../lib/sweep-risk-path-attrition.ts';
import type {RiskPathReport,RiskPathTrade} from '../lib/sweep-confluence-risk-path.ts';
const WEEK=604800,MONDAY=345600;
function fixture(id:string,n:number,extra:Partial<Pick<RiskPathReport,
 'pending'|'gapExcluded'|'warmupExcluded'|'overlapExcluded'|'priceExcluded'>>={}):RiskPathReport{
 const trades:RiskPathTrade[]=Array.from({length:n},(_,k)=>{
  const entryAt=MONDAY+(2700+Number(id.slice(1))*30+k)*WEEK+3600;
  return {sweepAt:entryAt-7200,confirmationAt:entryAt,entryAt,exitAt:entryAt+3600,
   direction:'bullish',entry:100,stop:99,target:102,exit:100.1,reason:'TIME',
   grossBps:10,netBps:[10,5],netR:[0.1,0.05]};
 });
 const pending=extra.pending??0,gapExcluded=extra.gapExcluded??0,
  warmupExcluded=extra.warmupExcluded??0,overlapExcluded=extra.overlapExcluded??0,
  priceExcluded=extra.priceExcluded??0;
 return {engine:'sweep-confluence-ohlc-risk-path-v1',sourceEngine:'sweep-mss-fvg-same-close-v1',
  datasetId:id,instrument:'NSXUSD-CFD',
  config:{atrPeriod:14,stopAtrMultiple:1,rewardRisk:2,maxHoldBars:3,roundTripCostsBps:[0,5]},
  inputSignals:n+pending+gapExcluded+warmupExcluded+overlapExcluded+priceExcluded,
  closed:n,pending,gapExcluded,warmupExcluded,overlapExcluded,priceExcluded,
  trades,meanNetBps:n?[10,5]:[null,null],meanNetR:n?[0.1,0.05]:[null,null],warning:''};
}
test('attrition: separates eligible, unresolved and protocol exclusions',()=>{
 const r=auditConfluenceRiskPathAttrition([fixture('s0',2,{pending:1,gapExcluded:1,warmupExcluded:2}),fixture('s1',1,{priceExcluded:1})]);
 assert.deepEqual(r.counts,{inputSignals:8,closed:3,pending:1,gapExcluded:1,warmupExcluded:2,overlapExcluded:0,priceExcluded:1});
 assert.equal(r.eligibleShare,3/8);assert.equal(r.excludedShare,5/8);
 assert.equal(r.unresolvedShare,2/8);assert.equal(r.equalSourceEligibleShare,(2/6+1/2)/2);
 assert.deepEqual(r.sourceEligibleShareRange,{min:2/6,max:1/2});
 assert.equal(r.activeSources,2);
});
test('attrition: input order cannot change deterministic report',()=>{
 const a=fixture('s0',2,{pending:1}),b=fixture('s1',1,{gapExcluded:2});
 assert.deepEqual(auditConfluenceRiskPathAttrition([a,b]),auditConfluenceRiskPathAttrition([b,a]));
});
test('attrition: zero input signals have null rates',()=>{
 const r=auditConfluenceRiskPathAttrition([fixture('s0',0)]);
 assert.equal(r.eligibleShare,null);assert.equal(r.excludedShare,null);
 assert.equal(r.unresolvedShare,null);assert.equal(r.equalSourceEligibleShare,null);
 assert.equal(r.sourceEligibleShareRange,null);assert.equal(r.activeSources,0);
});
test('attrition: no closed paths but unresolved signals retain denominator',()=>{
 const r=auditConfluenceRiskPathAttrition([fixture('s0',0,{pending:3,gapExcluded:1})]);
 assert.equal(r.eligibleShare,0);assert.equal(r.unresolvedShare,1);
 assert.equal(r.counts.inputSignals,4);
});
test('attrition: duplicate dataset identity is rejected',()=>{
 assert.throws(()=>auditConfluenceRiskPathAttrition([fixture('s0',1),fixture('s0',1)]),/Duplicate dataset/);
});
test('attrition: tampered accounting fails closed',()=>{
 const r=fixture('s0',1);r.inputSignals=2;
 assert.throws(()=>auditConfluenceRiskPathAttrition([r]),/Inconsistent report accounting/);
});
test('attrition: tampered trade return fails closed',()=>{
 const r=fixture('s0',1);r.trades[0].netR[1]=100;
 assert.throws(()=>auditConfluenceRiskPathAttrition([r]),/Cost\/R arithmetic mismatch/);
});
test('attrition: mixed instruments and strategy configs fail closed',()=>{
 const a=fixture('s0',1),b=fixture('s1',1);b.instrument='XAUUSD';
 assert.throws(()=>auditConfluenceRiskPathAttrition([a,b]),/Mixed instrument/);
 b.instrument=a.instrument;b.config.rewardRisk=3;
 assert.throws(()=>auditConfluenceRiskPathAttrition([a,b]),/Inconsistent gross return or stop\/target|Mixed instrument/);
});
test('attrition: absent input and overlapping selected trades rejected',()=>{
 assert.throws(()=>auditConfluenceRiskPathAttrition([]),/Require 1/);
 const a=fixture('s0',1),b=fixture('s1',1),t=a.trades[0],u=b.trades[0];
 const offset=t.entryAt-u.entryAt;
 for(const k of ['sweepAt','confirmationAt','entryAt','exitAt'] as const)u[k]+=offset;
 assert.throws(()=>auditConfluenceRiskPathAttrition([a,b]),/Cross-source overlapping/);
});
