import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditFrozenChronology} from '../lib/sweep-chronology-evidence.ts';
import type {RiskPathReport,RiskPathTrade} from '../lib/sweep-confluence-risk-path.ts';
const H=3600,W=604800,T=Date.UTC(2024,0,1)/1000,C=[0,5,15],P=14*W;
function trade(at:number,gain:number):RiskPathTrade{
 const grossBps=gain*100;
 return {sweepAt:at-2*H,confirmationAt:at,entryAt:at,exitAt:at+H,direction:'bullish',entry:100,stop:99,target:102,exit:100+gain,reason:'TIME',grossBps,netBps:C.map(c=>grossBps-c),netR:C.map(c=>(grossBps-c)/100)};
}
function fixture():RiskPathReport{
 const trades:RiskPathTrade[]=[];
 for(let p=0;p<3;p++)for(let w=0;w<14;w++)for(let k=0;k<3;k++)trades.push(trade(T+(p*14+w)*W+(12+2*k)*H,[.2,-.1,.1][p]));
 return {engine:'sweep-confluence-ohlc-risk-path-v1',sourceEngine:'sweep-mss-fvg-same-close-v1',datasetId:'archive',instrument:'NSXUSD-CFD',config:{atrPeriod:14,stopAtrMultiple:1,rewardRisk:2,maxHoldBars:3,roundTripCostsBps:[...C]},inputSignals:trades.length,closed:trades.length,pending:0,gapExcluded:0,warmupExcluded:0,overlapExcluded:0,priceExcluded:0,trades,meanNetBps:C.map((_,j)=>trades.reduce((s,t)=>s+t.netBps[j],0)/trades.length),meanNetR:C.map((_,j)=>trades.reduce((s,t)=>s+t.netR[j],0)/trades.length),warning:'synthetic'};
}
function plan(){return {datasetId:'archive',instrument:'NSXUSD-CFD',developmentStart:T,validationStart:T+P,holdoutStart:T+2*P,holdoutEnd:T+3*P}}
test('fixed purge, embargo and all-path accounting',()=>{
 const a=auditFrozenChronology(fixture(),plan());
 assert.equal(a.accounted,126);assert.equal(a.outside,0);
 for(const z of a.slices){assert.equal(z.completedEntries,42);assert.equal(z.purged,3);assert.equal(z.embargoed,3);assert.equal(z.eligible,36);assert.equal(z.weeks,12);assert.equal(z.status,'DESCRIPTIVE_ONLY')}
 assert.equal(a.untouchedHoldoutVerified,false);assert.equal(a.sourceProvenanceVerified,false);assert.equal(a.eligibleForLiveTrading,false);
});
test('equal-week and trade-weighted means remain descriptive',()=>{
 const a=auditFrozenChronology(fixture(),plan());
 for(const [i,v] of [.15,-.15,.05].entries()){assert.ok(Math.abs(a.slices[i].tradeMeanR!-v)<1e-10);assert.ok(Math.abs(a.slices[i].equalWeekMeanR!-v)<1e-10)}
});
test('withhold low sample instead of imputing excluded returns',()=>{
 const f=fixture();f.trades=f.trades.filter(t=>t.entryAt>=T+P||t.entryAt<T+2*W);
 f.closed=f.trades.length;f.inputSignals=f.closed;
 f.meanNetBps=C.map((_,j)=>f.trades.reduce((s,t)=>s+t.netBps[j],0)/f.closed);
 f.meanNetR=C.map((_,j)=>f.trades.reduce((s,t)=>s+t.netR[j],0)/f.closed);
 const z=auditFrozenChronology(f,plan()).slices[0];
 assert.equal(z.status,'WITHHELD');assert.equal(z.tradeMeanR,null);assert.equal(z.equalWeekMeanR,null);
});
test('strict UTC-Monday and 14-week minimum boundaries',()=>{
 const f=fixture(),p=plan();
 assert.throws(()=>auditFrozenChronology(f,{...p,validationStart:p.validationStart+H}),/Monday/);
 assert.throws(()=>auditFrozenChronology(f,{...p,validationStart:p.developmentStart+13*W}),/14 full/);
});
test('source identity mismatches fail closed',()=>{
 const f=fixture(),p=plan();
 assert.throws(()=>auditFrozenChronology(f,{...p,datasetId:'other'}),/identity/);
 assert.throws(()=>auditFrozenChronology(f,{...p,instrument:'XAUUSD'}),/identity/);
});
test('frozen 5 bps cost required',()=>{
 const f=fixture();f.config.roundTripCostsBps=[0,15];
 for(const t of f.trades){t.netBps=[t.netBps[0],t.netBps[2]];t.netR=[t.netR[0],t.netR[2]]}
 f.meanNetBps=[f.meanNetBps[0],f.meanNetBps[2]];f.meanNetR=[f.meanNetR[0],f.meanNetR[2]];
 assert.throws(()=>auditFrozenChronology(f,plan()),/5 bps/);
});
test('upstream rejects tampered costs and overlapping paths',()=>{
 const a=fixture();a.trades[0].netR[1]=999;
 assert.throws(()=>auditFrozenChronology(a,plan()),/Cost\/R/);
 const b=fixture();b.trades[1].entryAt=b.trades[0].entryAt;
 assert.throws(()=>auditFrozenChronology(b,plan()),/chronology/);
});
test('outside completed paths stay outside, not promoted to holdout',()=>{
 const f=fixture();f.trades.push(trade(T+3*P+12*H,.1));f.closed++;f.inputSignals++;
 f.meanNetBps=C.map((_,j)=>f.trades.reduce((s,t)=>s+t.netBps[j],0)/f.closed);
 f.meanNetR=C.map((_,j)=>f.trades.reduce((s,t)=>s+t.netR[j],0)/f.closed);
 const a=auditFrozenChronology(f,plan());assert.equal(a.outside,1);assert.equal(a.accounted,127);
});
