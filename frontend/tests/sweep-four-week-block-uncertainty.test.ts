import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditFourWeekBlockUncertainty} from '../lib/sweep-four-week-block-uncertainty.ts';
import type {RiskPathReport,RiskPathTrade} from '../lib/sweep-confluence-risk-path.ts';
const W=604800,H=3600,T=Date.UTC(2024,0,1)/1000,C=[0,5,15];
function trade(at:number,exit:number):RiskPathTrade{
 const gross=(exit/100-1)*10000;
 return {sweepAt:at-2*H,confirmationAt:at,entryAt:at,exitAt:at+H,
  direction:'bullish',entry:100,stop:99,target:102,exit,reason:'TIME',
  grossBps:gross,netBps:C.map(c=>gross-c),netR:C.map(c=>(gross-c)/100)};
}
function fixture(weekCount=20,tradesPerWeek=2,exit=(w:number)=>100.5):RiskPathReport{
 const trades:RiskPathTrade[]=[];
 for(let w=0;w<weekCount;w++)for(let k=0;k<tradesPerWeek;k++)
  trades.push(trade(T+w*W+(2+k*3)*H,exit(w)));
 return {engine:'sweep-confluence-ohlc-risk-path-v1',
  sourceEngine:'sweep-mss-fvg-same-close-v1',datasetId:'immutable-archive-id',
  instrument:'NSXUSD-CFD',config:{atrPeriod:14,stopAtrMultiple:1,
   rewardRisk:2,maxHoldBars:3,roundTripCostsBps:[...C]},
  inputSignals:trades.length,closed:trades.length,pending:0,gapExcluded:0,
  warmupExcluded:0,overlapExcluded:0,priceExcluded:0,trades,
  meanNetBps:C.map((_,j)=>trades.length?trades.reduce((s,t)=>s+t.netBps[j],0)/trades.length:null),
  meanNetR:C.map((_,j)=>trades.length?trades.reduce((s,t)=>s+t.netR[j],0)/trades.length:null),
  warning:'synthetic'};
}
test('fixed four-week calendar-block audit is deterministic and cost-specific',()=>{
 const a=auditFourWeekBlockUncertainty(fixture());
 const b=auditFourWeekBlockUncertainty(fixture());
 assert.deepEqual(a,b);
 assert.equal(a.status,'DESCRIPTIVE_ONLY');assert.equal(a.replicates,3000);
 assert.equal(a.trades,40);assert.equal(a.activeWeeks,20);assert.equal(a.calendarWeeks,20);
 assert.equal(a.largestFourWeekTradeShare,.2);
 for(const [i,mean] of [.5,.45,.35].entries()){
  const s=a.scenarios[i];assert.ok(Math.abs(s.meanNetR!-mean)<1e-10);
  assert.ok(Math.abs(s.blockLower95NetR!-mean)<1e-10);
  assert.ok(Math.abs(s.blockUpper95NetR!-mean)<1e-10);
 }
 assert.equal(a.untouchedHoldoutVerified,false);assert.equal(a.eligibleForLiveTrading,false);
});
test('four-week blocks preserve clustered regime outcomes and bound observed means',()=>{
 const a=auditFourWeekBlockUncertainty(fixture(20,2,w=>w<10?101:99.5));
 assert.equal(a.status,'DESCRIPTIVE_ONLY');
 const s=a.scenarios[1];
 assert.ok(s.blockLower95NetR!<s.meanNetR!);
 assert.ok(s.blockUpper95NetR!>s.meanNetR!);
 assert.ok(s.blockUpper95NetR!-s.blockLower95NetR!>.2);
});
test('calendar gaps remain counted and affect active fraction',()=>{
 const f=fixture(20,2);
 // Remove one full UTC week; do not silently close the gap.
 f.trades=f.trades.filter(t=>t.entryAt<T+8*W||t.entryAt>=T+9*W);
 f.closed=f.trades.length;f.inputSignals=f.closed;
 f.meanNetBps=C.map((_,j)=>f.trades.reduce((s,t)=>s+t.netBps[j],0)/f.closed);
 f.meanNetR=C.map((_,j)=>f.trades.reduce((s,t)=>s+t.netR[j],0)/f.closed);
 const a=auditFourWeekBlockUncertainty(f);
 assert.equal(a.activeWeeks,19);assert.equal(a.calendarWeeks,20);
 assert.equal(a.activeWeekFraction,19/20);assert.equal(a.status,'DESCRIPTIVE_ONLY');
});
test('withholds for insufficient paths, active weeks, or calendar span',()=>{
 assert.equal(auditFourWeekBlockUncertainty(fixture(11,3)).status,'INSUFFICIENT_EVIDENCE');
 assert.equal(auditFourWeekBlockUncertainty(fixture(15,2)).status,'INSUFFICIENT_EVIDENCE');
 assert.equal(auditFourWeekBlockUncertainty(fixture(20,1)).status,'INSUFFICIENT_EVIDENCE');
 const z=auditFourWeekBlockUncertainty(fixture(20,0));
 assert.equal(z.status,'INSUFFICIENT_EVIDENCE');assert.equal(z.calendarWeeks,0);
 assert.equal(z.scenarios[1].blockLower95NetR,null);
});
test('rejects modified costs and invalid trade chronology before bootstrap',()=>{
 const f=fixture();f.trades[0].netR[1]=1000;
 assert.throws(()=>auditFourWeekBlockUncertainty(f),/Cost\/R|arithmetic|mismatch/);
 const g=fixture();g.trades[1].entryAt=g.trades[0].entryAt;
 assert.throws(()=>auditFourWeekBlockUncertainty(g),/chronology/);
});
test('seed is required, bounded, and affects nonconstant draws',()=>{
 assert.throws(()=>auditFourWeekBlockUncertainty(fixture(),''),/seed/);
 assert.throws(()=>auditFourWeekBlockUncertainty(fixture(),'x'.repeat(129)),/seed/);
 const f=fixture(20,2,w=>w<10?101:99.5);
 const a=auditFourWeekBlockUncertainty(f,'a');
 const b=auditFourWeekBlockUncertainty(f,'b');
 assert.notDeepEqual(a.scenarios[1],b.scenarios[1]);
});
test('large source calendar spans fail closed rather than allocate unbounded data',()=>{
 const f=fixture();
 const last=f.trades[f.trades.length-1];
 last.sweepAt+=2601*W;last.confirmationAt+=2601*W;
 last.entryAt+=2601*W;last.exitAt+=2601*W;
 assert.throws(()=>auditFourWeekBlockUncertainty(f),/calendar-week span/);
});
