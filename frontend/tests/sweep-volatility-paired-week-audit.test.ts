import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditFrozenVolatilityPairedWeeks} from '../lib/sweep-volatility-paired-week-audit.ts';
import type {RiskPathReport,RiskPathTrade} from '../lib/sweep-confluence-risk-path.ts';
import type {VolatilityRegimeReport,VolatilityRegime} from '../lib/causal-volatility-regime.ts';

const H=3600,WEEK=604800,START=Date.UTC(2025,0,6,12)/1000;
const COSTS=[0,5,15];
function trade(at:number,regime:VolatilityRegime):RiskPathTrade{
 const gain=regime==='LOW'?.2:regime==='NORMAL'?.1:.3;
 const gross=gain*100;
 return {sweepAt:at-2*H,confirmationAt:at,entryAt:at,exitAt:at+H,
  direction:'bullish',entry:100,stop:99,target:102,exit:100+gain,reason:'TIME',
  grossBps:gross,netBps:COSTS.map(c=>gross-c),netR:COSTS.map(c=>(gross-c)/100)};
}
function makeReport(trades:RiskPathTrade[]):RiskPathReport{
 const ts=[...trades].sort((a,b)=>a.entryAt-b.entryAt);
 return {engine:'sweep-confluence-ohlc-risk-path-v1',datasetId:'archive-a',instrument:'NSXUSD-CFD',
  sourceEngine:'sweep-mss-fvg-same-close-v1',config:{atrPeriod:14,stopAtrMultiple:1,rewardRisk:2,maxHoldBars:3,roundTripCostsBps:[...COSTS]},
  inputSignals:ts.length,closed:ts.length,pending:0,gapExcluded:0,warmupExcluded:0,
  overlapExcluded:0,priceExcluded:0,trades:ts,
  meanNetBps:COSTS.map((_,j)=>ts.length?ts.reduce((s,t)=>s+t.netBps[j],0)/ts.length:null),
  meanNetR:COSTS.map((_,j)=>ts.length?ts.reduce((s,t)=>s+t.netR[j],0)/ts.length:null),warning:'synthetic'};
}
function makeVolatility(ts:RiskPathTrade[],byEntry:ReadonlyMap<number,VolatilityRegime>,skip=-1):VolatilityRegimeReport{
 const labels=ts.filter((_,i)=>i!==skip).map(t=>{
  const regime=byEntry.get(t.entryAt);if(!regime)throw Error('Missing synthetic predeclared regime');
  return {candleOpenAt:t.entryAt-H,observedAt:t.entryAt,eligibleFrom:t.entryAt,
   normalizedAtrBps:200,trailingPercentile:regime==='LOW'?.1:regime==='HIGH'?.9:.5,regime};
 }).sort((a,b)=>a.candleOpenAt-b.candleOpenAt);
 return {engine:'causal-1h-natr-terciles-v1',datasetId:'archive-a',instrument:'NSXUSD-CFD',
  frame:'1H',atrPeriod:14,baselineBars:24,inputCandles:labels.length,
  labelled:labels.length,unlabelled:0,labels,
  counts:{LOW:labels.filter(l=>l.regime==='LOW').length,
   NORMAL:labels.filter(l=>l.regime==='NORMAL').length,
   HIGH:labels.filter(l=>l.regime==='HIGH').length},warning:'synthetic'};
}
function fixture(weeks=12,perRegime=3){
 const ts:RiskPathTrade[]=[],byEntry=new Map<number,VolatilityRegime>();
 for(let w=0;w<weeks;w++)for(let r=0;r<3;r++)for(let k=0;k<perRegime;k++){
  const regime=(['LOW','NORMAL','HIGH'] as const)[r];
  const at=START+w*WEEK+(r*perRegime+k)*2*H;
  ts.push(trade(at,regime));byEntry.set(at,regime);
 }
 return {r:makeReport(ts),v:makeVolatility(ts,byEntry),byEntry};
}
test('fixed contrasts, equal-week difference and deterministic adjusted intervals',()=>{
 const {r,v}=fixture();const a=auditFrozenVolatilityPairedWeeks(r,v);
 const b=auditFrozenVolatilityPairedWeeks(r,v);
 assert.deepEqual(a,b);assert.equal(a.eligibleForLiveTrading,false);
 assert.equal(a.contrasts.length,3);assert.deepEqual(a.contrasts.map(c=>[c.first,c.second]),
  [['LOW','NORMAL'],['HIGH','NORMAL'],['HIGH','LOW']]);
 assert.ok(a.contrasts.every(c=>c.status==='DESCRIPTIVE_ONLY'&&c.sharedUtcWeeks===12));
 assert.ok(Math.abs(a.contrasts[0].pairedWeekMeanDifferenceR!-.1)<1e-9);
 assert.ok(Math.abs(a.contrasts[1].pairedWeekMeanDifferenceR!-.2)<1e-9);
 assert.ok(a.contrasts.every(c=>c.bonferroniBootstrapIntervalR!==null));
});
test('withholds all estimates below twelve shared weeks',()=>{
 const {r,v}=fixture(11);const a=auditFrozenVolatilityPairedWeeks(r,v);
 assert.ok(a.contrasts.every(c=>c.status==='WITHHELD'&&c.withheldReason==='TOO_FEW_SHARED_WEEKS'&&c.pairedWeekMeanDifferenceR===null));
});
test('withholds when shared cohort trade counts are below thirty',()=>{
 const {r,v}=fixture(12,2);const a=auditFrozenVolatilityPairedWeeks(r,v);
 assert.ok(a.contrasts.every(c=>c.withheldReason==='TOO_FEW_SHARED_TRADES'&&c.bonferroniBootstrapIntervalR===null));
});
test('no shared weeks means no fabricated cross-regime effect',()=>{
 const ts:RiskPathTrade[]=[],byEntry=new Map<number,VolatilityRegime>();
 for(let r=0;r<3;r++)for(let w=0;w<12;w++)for(let k=0;k<3;k++){
  const at=START+(r*12+w)*WEEK+k*2*H,regime=(['LOW','NORMAL','HIGH'] as const)[r];
  ts.push(trade(at,regime));byEntry.set(at,regime);
 }
 const a=auditFrozenVolatilityPairedWeeks(makeReport(ts),makeVolatility(ts,byEntry));
 assert.ok(a.contrasts.every(c=>c.sharedUtcWeeks===0&&c.withheldReason==='TOO_FEW_SHARED_WEEKS'));
});
test('one missing volatility label withholds all estimates, never drops path silently',()=>{
 const {r,byEntry}=fixture();const v=makeVolatility(r.trades,byEntry,0);
 const a=auditFrozenVolatilityPairedWeeks(r,v);
 assert.equal(a.unlabelledPaths,1);
 assert.ok(a.contrasts.every(c=>c.withheldReason==='UNLABELLED_PATHS'&&c.pairedWeekMeanDifferenceR===null));
});
test('frozen illustrative five-bps scenario is mandatory',()=>{
 const {r,v}=fixture();r.config.roundTripCostsBps=[0,15];
 r.trades.forEach(t=>{t.netBps=[t.netBps[0],t.netBps[2]];t.netR=[t.netR[0],t.netR[2]]});
 r.meanNetBps=[r.meanNetBps[0],r.meanNetBps[2]];r.meanNetR=[r.meanNetR[0],r.meanNetR[2]];
 assert.throws(()=>auditFrozenVolatilityPairedWeeks(r,v),/Frozen 5 bps/);
});
test('upstream arithmetic tampering fails closed',()=>{
 const {r,v}=fixture();r.trades[0].netR[1]=9;
 assert.throws(()=>auditFrozenVolatilityPairedWeeks(r,v),/Cost\/R arithmetic mismatch/);
});
test('future-available label fails closed',()=>{
 const {r,v}=fixture();v.labels[0].eligibleFrom+=H;
 assert.throws(()=>auditFrozenVolatilityPairedWeeks(r,v),/noncausal/);
});
test('source mismatch fails closed',()=>{
 const {r,v}=fixture();v.datasetId='another-source';
 assert.throws(()=>auditFrozenVolatilityPairedWeeks(r,v),/Mismatched/);
});
test('empty path input never invents performance',()=>{
 const a=auditFrozenVolatilityPairedWeeks(makeReport([]),makeVolatility([],new Map()));
 assert.ok(a.contrasts.every(c=>c.pairedWeekMeanDifferenceR===null&&c.sharedUtcWeeks===0));
});
