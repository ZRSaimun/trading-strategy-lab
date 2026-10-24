import {test} from 'node:test';
import assert from 'node:assert/strict';
import {stressConfluenceFriction} from '../lib/sweep-risk-path-friction-scenarios.ts';
import type {RiskPathReport,RiskPathTrade} from '../lib/sweep-confluence-risk-path.ts';
const assumptions=[
 {id:'low',roundTripSpreadBps:2,entrySlippageBps:1,exitSlippageBps:1,roundTripCommissionBps:1,financingBpsPer24Hours:8},
 {id:'high',roundTripSpreadBps:12,entrySlippageBps:4,exitSlippageBps:4,roundTripCommissionBps:5,financingBpsPer24Hours:24}
];
function fixture():RiskPathReport{
 const entryAt=Date.parse('2024-01-02T10:00:00Z')/1000;
 const costs=[0,5,15],grossBps=20;
 const trade:RiskPathTrade={sweepAt:entryAt-7200,confirmationAt:entryAt,entryAt,
  exitAt:entryAt+10800,direction:'bullish',entry:100,stop:99,target:102,
  exit:100.2,reason:'TIME',grossBps,netBps:costs.map(c=>grossBps-c),
  netR:costs.map(c=>(grossBps-c)/100)};
 return {engine:'sweep-confluence-ohlc-risk-path-v1',
  datasetId:'private-source-id',instrument:'NSXUSD-CFD',
  sourceEngine:'sweep-mss-fvg-same-close-v1',
  config:{atrPeriod:14,stopAtrMultiple:1,rewardRisk:2,maxHoldBars:3,roundTripCostsBps:costs},
  inputSignals:1,closed:1,pending:0,gapExcluded:0,warmupExcluded:0,overlapExcluded:0,priceExcluded:0,
  trades:[trade],meanNetBps:[20,15,5],meanNetR:[.2,.15,.05],warning:''};
}
test('explicit components replace, not stack on top of, source flat cost',()=>{
 const r=stressConfluenceFriction(fixture(),assumptions);
 assert.equal(r.status,'SENSITIVITY_ONLY');
 assert.equal(r.datasetId,'private-source-id');
 assert.equal(r.scenarios[0].meanAssumedCostBps,6);
 assert.ok(Math.abs(r.scenarios[0].meanNetBps!-14)<1e-8);
 assert.ok(Math.abs(r.scenarios[0].meanNetR!-.14)<1e-8);
});
test('funding scales with UTC elapsed time, not inferred broker cutoffs',()=>{
 const f=fixture();f.trades[0].exitAt=f.trades[0].entryAt+3600;
 const r=stressConfluenceFriction(f,[assumptions[0]]);
 assert.ok(Math.abs(r.scenarios[0].meanAssumedCostBps!-(5+8/24))<1e-8);
});
test('higher assumed friction can turn positive gross into net loss',()=>{
 const r=stressConfluenceFriction(fixture(),assumptions);
 assert.ok(r.scenarios[1].meanNetBps!<0);
 assert.equal(r.scenarios[1].netPositiveFraction,0);
});
test('deterministic results for frozen inputs',()=>{
 assert.deepEqual(stressConfluenceFriction(fixture(),assumptions),stressConfluenceFriction(fixture(),assumptions));
});
test('empty completed reports return null, never a fictitious zero return',()=>{
 const f=fixture();f.trades=[];f.closed=0;f.inputSignals=0;
 f.meanNetBps=[null,null,null];f.meanNetR=[null,null,null];
 const r=stressConfluenceFriction(f,assumptions);
 assert.equal(r.scenarios[0].trades,0);
 assert.equal(r.scenarios[0].meanNetBps,null);
 assert.equal(r.scenarios[0].netPositiveFraction,null);
});
test('reject duplicate names, unbounded and negative costs',()=>{
 assert.throws(()=>stressConfluenceFriction(fixture(),[assumptions[0],assumptions[0]]),/scenario ID/);
 assert.throws(()=>stressConfluenceFriction(fixture(),[{...assumptions[0],entrySlippageBps:-1}]),/friction component/);
 assert.throws(()=>stressConfluenceFriction(fixture(),[{...assumptions[0],financingBpsPer24Hours:Infinity}]),/friction component/);
 assert.throws(()=>stressConfluenceFriction(fixture(),[]),/1–10/);
});
test('reject implausible holding durations and malformed timestamps',()=>{
 const f=fixture();f.trades[0].exitAt+=3600;
 assert.throws(()=>stressConfluenceFriction(f,assumptions),/holding interval/);
 const g=fixture();g.trades[0].exitAt=g.trades[0].entryAt;
 assert.throws(()=>stressConfluenceFriction(g,assumptions),/chronology|holding interval/);
});
test('independent source report auditor detects tampering',()=>{
 const f=fixture();f.trades[0].netBps[1]=100;
 assert.throws(()=>stressConfluenceFriction(f,assumptions),/Cost\/R/);
});
test('does not accept mixed or unsupported research engine identities',()=>{
 const f=fixture();f.sourceEngine='unsupported' as RiskPathReport['sourceEngine'];
 assert.throws(()=>stressConfluenceFriction(f,assumptions),/identity/);
});
