import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditConfluenceVolatilityInteraction} from '../lib/sweep-volatility-interaction-audit.ts';
import type {RiskPathReport,RiskPathTrade} from '../lib/sweep-confluence-risk-path.ts';
import type {VolatilityRegimeReport,VolatilityRegime} from '../lib/causal-volatility-regime.ts';

const H=3600,START=Date.UTC(2025,0,6,12)/1000;
const costs=[0,5];
function trade(at:number):RiskPathTrade{
 return {sweepAt:at-2*H,confirmationAt:at,entryAt:at,exitAt:at+H,
  direction:'bullish',entry:100,stop:99,target:102,exit:101,reason:'TIME',
  grossBps:100,netBps:[100,95],netR:[1,.95]};
}
function report(trades:RiskPathTrade[]):RiskPathReport{
 return {engine:'sweep-confluence-ohlc-risk-path-v1',datasetId:'archive-a',instrument:'NSXUSD-CFD',
  sourceEngine:'sweep-mss-fvg-same-close-v1',config:{atrPeriod:14,stopAtrMultiple:1,rewardRisk:2,maxHoldBars:3,roundTripCostsBps:costs},
  inputSignals:trades.length,closed:trades.length,pending:0,gapExcluded:0,warmupExcluded:0,
  overlapExcluded:0,priceExcluded:0,trades,meanNetBps:trades.length?[100,95]:[null,null],
  meanNetR:trades.length?[1,.95]:[null,null],warning:'synthetic'};
}
function label(at:number,regime:VolatilityRegime='NORMAL'){
 const p=regime==='LOW'?.1:regime==='HIGH'?.9:.5;
 return {candleOpenAt:at-H,observedAt:at,eligibleFrom:at,
  normalizedAtrBps:200,trailingPercentile:p,regime};
}
function volatility(labels:ReturnType<typeof label>[]):VolatilityRegimeReport{
 return {engine:'causal-1h-natr-terciles-v1',datasetId:'archive-a',instrument:'NSXUSD-CFD',
  frame:'1H',atrPeriod:14,baselineBars:24,inputCandles:labels.length,
  labelled:labels.length,unlabelled:0,labels,
  counts:{LOW:labels.filter(l=>l.regime==='LOW').length,
   NORMAL:labels.filter(l=>l.regime==='NORMAL').length,HIGH:labels.filter(l=>l.regime==='HIGH').length},warning:'synthetic'};
}
test('joins only exact next-open labels and reports all four cohorts',()=>{
 const ts=[trade(START),trade(START+H*3),trade(START+H*6),trade(START+H*9)];
 const v=volatility([label(START,'LOW'),label(START+H*3,'NORMAL'),label(START+H*6,'HIGH')]);
 const r=auditConfluenceVolatilityInteraction(report(ts),v);
 assert.deepEqual(r.groups.map(g=>g.trades),[1,1,1,1]);
 assert.equal(r.matched,3);assert.equal(r.unlabelled,1);
 assert.equal(r.groups[0].scenarios[1].meanNetR,.95);
 assert.equal(r.status,'INSUFFICIENT_EVIDENCE');
});
test('empty report never fabricates returns',()=>{
 const r=auditConfluenceVolatilityInteraction(report([]),volatility([]));
 assert.equal(r.trades,0);assert.ok(r.groups.every(g=>g.scenarios[0].meanNetR===null));
});
test('does not assign a future label to an earlier entry',()=>{
 const r=auditConfluenceVolatilityInteraction(report([trade(START)]),volatility([label(START+H)]));
 assert.equal(r.unlabelled,1);
});
test('rejects early-available or delayed labels, preventing lookahead',()=>{
 const v=volatility([label(START)]);v.labels[0].eligibleFrom=START-H;
 assert.throws(()=>auditConfluenceVolatilityInteraction(report([trade(START)]),v),/noncausal/);
 const w=volatility([label(START)]);w.labels[0].observedAt=START+H;
 assert.throws(()=>auditConfluenceVolatilityInteraction(report([trade(START)]),w),/noncausal/);
});
test('rejects mismatched source and instrument',()=>{
 const v=volatility([label(START)]);v.datasetId='other';
 assert.throws(()=>auditConfluenceVolatilityInteraction(report([trade(START)]),v),/Mismatched/);
 const w=volatility([label(START)]);w.instrument='XAUUSD';
 assert.throws(()=>auditConfluenceVolatilityInteraction(report([trade(START)]),w),/Mismatched/);
});
test('rejects duplicate and unsorted labels',()=>{
 const v=volatility([label(START),label(START)]);
 assert.throws(()=>auditConfluenceVolatilityInteraction(report([trade(START)]),v),/noncausal/);
 const w=volatility([label(START+H),label(START)]);
 assert.throws(()=>auditConfluenceVolatilityInteraction(report([trade(START)]),w),/noncausal/);
});
test('rejects falsified bucket ranks and counts',()=>{
 const v=volatility([label(START)]);v.labels[0].regime='HIGH';
 assert.throws(()=>auditConfluenceVolatilityInteraction(report([trade(START)]),v),/frozen rank/);
 const w=volatility([label(START)]);w.counts.NORMAL=0;
 assert.throws(()=>auditConfluenceVolatilityInteraction(report([trade(START)]),w),/counts mismatch/);
});
test('rejects malformed accounting and nonfinite normalized ATR',()=>{
 const v=volatility([label(START)]);v.inputCandles=0;
 assert.throws(()=>auditConfluenceVolatilityInteraction(report([trade(START)]),v),/accounting/);
 const w=volatility([label(START)]);w.labels[0].normalizedAtrBps=NaN;
 assert.throws(()=>auditConfluenceVolatilityInteraction(report([trade(START)]),w),/noncausal/);
});
test('rejects tampered cost arithmetic before regime analysis',()=>{
 const r=report([trade(START)]);r.trades[0].netR[1]=5;
 assert.throws(()=>auditConfluenceVolatilityInteraction(r,volatility([label(START)])),/Cost\/R arithmetic mismatch/);
});
test('all cohorts need 30 paths and 12 weeks before descriptive-only status',()=>{
 const ts:RiskPathTrade[]=[],ls:ReturnType<typeof label>[]=[];
 for(let i=0;i<90;i++){
  const at=START+i*604800;
  ts.push(trade(at));ls.push(label(at,(['LOW','NORMAL','HIGH'] as const)[i%3]));
 }
 const r=auditConfluenceVolatilityInteraction(report(ts),volatility(ls));
 assert.equal(r.status,'DESCRIPTIVE_ONLY');
 assert.ok(r.groups.slice(0,3).every(g=>g.eventWeeks===30));
 assert.equal(r.groups[3].trades,0);
});
