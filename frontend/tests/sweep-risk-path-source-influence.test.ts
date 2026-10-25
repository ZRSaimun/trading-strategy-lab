import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditConfluenceSourceInfluence} from '../lib/sweep-risk-path-source-influence.ts';
import type {RiskPathReport,RiskPathTrade} from '../lib/sweep-confluence-risk-path.ts';
const WEEK=604800,MONDAY=345600,costs=[0,5];
function fixture(source=5,perSource=6,exceptional=-1,positive=10,negative=10):RiskPathReport[]{
 return Array.from({length:source},(_,i)=>{
  const trades:RiskPathTrade[]=Array.from({length:perSource},(_,k)=>{
   const entryAt=MONDAY+(2600+i*perSource+k)*WEEK+3600;
   const grossBps=i===exceptional?positive:negative;
   return {sweepAt:entryAt-7200,confirmationAt:entryAt,entryAt,exitAt:entryAt+3600,
    direction:'bullish',entry:100,stop:99,target:102,exit:100+grossBps/100,
    reason:'TIME',grossBps,netBps:costs.map(c=>grossBps-c),netR:costs.map(c=>(grossBps-c)/100)};
  });
  return {engine:'sweep-confluence-ohlc-risk-path-v1',sourceEngine:'sweep-mss-fvg-same-close-v1',
   datasetId:`source-${i}`,instrument:'NSXUSD-CFD',
   config:{atrPeriod:14,stopAtrMultiple:1,rewardRisk:2,maxHoldBars:3,roundTripCostsBps:[...costs]},
   inputSignals:trades.length,closed:trades.length,pending:0,gapExcluded:0,
   warmupExcluded:0,overlapExcluded:0,priceExcluded:0,trades,
   meanNetBps:costs.map((_,j)=>trades.length?trades.reduce((s,t)=>s+t.netBps[j],0)/trades.length:null),
   meanNetR:costs.map((_,j)=>trades.length?trades.reduce((s,t)=>s+t.netR[j],0)/trades.length:null),warning:''};
 });
}
test('frozen source exclusion detects one influential archive and sign reversal',()=>{
 const r=auditConfluenceSourceInfluence(fixture(5,6,2,100,-10));
 assert.equal(r.status,'DESCRIPTIVE_ONLY');assert.equal(r.trades,30);
 assert.equal(r.activeSources,5);assert.equal(r.eventWeeks,30);
 assert.equal(r.scenarios[0].mostInfluentialDatasetId,'source-2');
 assert.equal(r.scenarios[0].signFlipCount,1);
 assert.ok(r.scenarios[0].pooledMeanNetR!>0);
 assert.ok(r.scenarios[0].worstLeaveOneSourceMeanR!<0);
});
test('equal identical sources are not fragile',()=>{
 const r=auditConfluenceSourceInfluence(fixture());
 assert.ok(Math.abs(r.scenarios[0].largestAbsoluteShiftR!)<1e-12);
 assert.equal(r.scenarios[0].signFlipCount,0);
 assert.equal(r.largestSourceTradeShare,0.2);
});
test('report order cannot change results',()=>{
 const a=fixture(5,6,3,100,-10);
 assert.deepEqual(auditConfluenceSourceInfluence(a),auditConfluenceSourceInfluence([...a].reverse()));
});
test('insufficient independent sources withhold influence',()=>{
 const r=auditConfluenceSourceInfluence(fixture(4,10));
 assert.equal(r.status,'INSUFFICIENT_EVIDENCE');
 assert.equal(r.scenarios[0].mostInfluentialDatasetId,null);
});
test('insufficient paths or weeks withhold influence',()=>{
 assert.equal(auditConfluenceSourceInfluence(fixture(5,5)).status,'INSUFFICIENT_EVIDENCE');
 assert.equal(auditConfluenceSourceInfluence(fixture(5,1)).status,'INSUFFICIENT_EVIDENCE');
});
test('empty valid source reports produce null returns',()=>{
 const r=auditConfluenceSourceInfluence(fixture(2,0));
 assert.equal(r.trades,0);assert.equal(r.largestSourceTradeShare,null);
 assert.equal(r.scenarios[0].pooledMeanNetR,null);
});
test('duplicate archive identity and mixed frozen costs fail closed',()=>{
 const a=fixture();a[1].datasetId=a[0].datasetId;
 assert.throws(()=>auditConfluenceSourceInfluence(a),/Duplicate dataset/);
 const b=fixture();b[1].config.roundTripCostsBps=[0,10];
 b[1].trades.forEach(t=>{t.netBps=[t.grossBps,t.grossBps-10];t.netR=t.netBps.map(x=>x/100)});
 b[1].meanNetBps=[10,0];b[1].meanNetR=[.1,0];
 assert.throws(()=>auditConfluenceSourceInfluence(b),/Mixed instrument or frozen/);
});
test('cross-source duplicate event intervals fail closed',()=>{
 const a=fixture();
 const t=a[0].trades[0],u=a[1].trades[0];
 const offset=t.entryAt-u.entryAt;
 for(const field of ['sweepAt','confirmationAt','entryAt','exitAt'] as const)u[field]+=offset;
 assert.throws(()=>auditConfluenceSourceInfluence(a),/Cross-source overlapping/);
});
test('tampered source report arithmetic fails closed',()=>{
 const a=fixture();a[0].trades[0].netR[0]=999;
 assert.throws(()=>auditConfluenceSourceInfluence(a),/Cost\/R arithmetic mismatch/);
});
test('bounded source input and mixed instrument rejected',()=>{
 assert.throws(()=>auditConfluenceSourceInfluence([]),/Require 1/);
 assert.throws(()=>auditConfluenceSourceInfluence(fixture(101,0)),/Require 1/);
 const a=fixture();a[0].instrument='XAUUSD';
 assert.throws(()=>auditConfluenceSourceInfluence(a),/Mixed instrument/);
});
