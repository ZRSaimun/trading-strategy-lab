import {test} from 'node:test';
import assert from 'node:assert/strict';
import {assessPaperMarginScenario,type PaperMarginScenario} from '../lib/paper-margin-scenarios.ts';
import type {PaperIdentity,PaperOrder,PaperQuote} from '../lib/paper-execution.ts';
import type {PaperCashflow} from '../lib/paper-cashflow-reconciliation.ts';
const identity:PaperIdentity={instrument:'XAUUSD-DEMO',provider:'Source A',venue:'OTC',priceSide:'bid-ask',pointValue:1};
const order:PaperOrder={clientOrderId:'paper-1',instrument:identity.instrument,side:'BUY',units:2,
 submittedAt:100,expiresAt:200,stop:99,target:102,maxSpread:1,maxQuoteAgeSeconds:3,
 maxStopRiskCurrency:10,adverseSlippagePerSide:.1,commissionPerUnitSide:.05,
 status:'OPEN',entry:100.3,entryObservedAt:101,entryReceivedAt:101,initialStopRisk:3};
const quote:PaperQuote={instrument:identity.instrument,provider:identity.provider,venue:identity.venue,
 observedAt:102,receivedAt:103,bid:99,ask:99.2};
const scenario:PaperMarginScenario={label:'illustrative maintenance',asOf:103,
 cashEquityBeforePositionCurrency:20,assumedMaintenanceRequirementCurrency:15,
 otherReservedMarginCurrency:1,maxQuoteAgeSeconds:3,postedCashflows:[]};
const flow=(changes:Partial<PaperCashflow>={}):PaperCashflow=>({id:'fee-1',orderId:order.clientOrderId,
 instrument:identity.instrument,provider:identity.provider,venue:identity.venue,at:102,
 kind:'OVERNIGHT_FINANCING',amountCurrency:-.4,reference:'Declared example',...changes});

test('marks a long on bid, subtracts round-trip commission and explicit posted financing',()=>{
 const x=assessPaperMarginScenario(identity,order,quote,{...scenario,postedCashflows:[flow()]});
 assert.equal(x.markSide,'bid');assert.equal(x.markPrice,99);
 assert.ok(Math.abs(x.grossUnrealizedPnlCurrency+2.6)<1e-10);
 assert.ok(Math.abs(x.estimatedAccountEquityCurrency-16.8)<1e-10);
 assert.ok(Math.abs(x.headroomCurrency-.8)<1e-10);
 assert.equal(x.state,'ABOVE_ASSUMED_MAINTENANCE');
 assert.equal(x.coverage,'DECLARED_UNVERIFIED_SCENARIO');
});
test('shorts mark on ask; an adverse gap can breach the assumed margin threshold',()=>{
 const short={...order,side:'SELL' as const,entry:99.9};
 const x=assessPaperMarginScenario(identity,short,{...quote,bid:104,ask:104.2},scenario);
 assert.equal(x.markSide,'ask');
 assert.ok(Math.abs(x.grossUnrealizedPnlCurrency+8.6)<1e-10);
 assert.equal(x.state,'AT_OR_BELOW_ASSUMED_MAINTENANCE');
 assert.ok(x.headroomCurrency<0);
});
test('margin thresholds are supplied assumptions, not automatically inferred from quote',()=>{
 const high=assessPaperMarginScenario(identity,order,quote,{...scenario,assumedMaintenanceRequirementCurrency:17});
 const low=assessPaperMarginScenario(identity,order,quote,{...scenario,assumedMaintenanceRequirementCurrency:14});
 assert.equal(high.state,'AT_OR_BELOW_ASSUMED_MAINTENANCE');
 assert.equal(low.state,'ABOVE_ASSUMED_MAINTENANCE');
});
test('refuses stale, future, old, crossed or mismatched quote identity',()=>{
 for(const bad of [{provider:'other'},{venue:'other'},{instrument:'NQ'},
  {observedAt:100},{receivedAt:104},{bid:101,ask:100},{bid:0},{observedAt:104,receivedAt:103}]){
  assert.throws(()=>assessPaperMarginScenario(identity,order,{...quote,...bad},scenario),/quote/);
 }
 assert.throws(()=>assessPaperMarginScenario(identity,order,quote,{...scenario,asOf:110}),/quote/);
});
test('duplicate posted event IDs are idempotent but conflicting duplicates fail',()=>{
 const x=assessPaperMarginScenario(identity,order,quote,{...scenario,postedCashflows:[flow(),flow()]});
 assert.equal(x.knownPostedCashflowsCurrency,-.4);
 assert.throws(()=>assessPaperMarginScenario(identity,order,quote,
  {...scenario,postedCashflows:[flow(),flow({amountCurrency:-1})]}),/Conflicting/);
});
test('rejects unprovenanced and future posted cashflows',()=>{
 for(const bad of [{provider:'other'},{at:104},{at:100},{id:''},{amountCurrency:Infinity},{kind:'OTHER' as PaperCashflow['kind']}]){
  assert.throws(()=>assessPaperMarginScenario(identity,order,quote,
   {...scenario,postedCashflows:[flow(bad)]}),/Invalid/);
 }
});
test('refuses closed positions, zero/negative margin assumptions and overflow',()=>{
 assert.throws(()=>assessPaperMarginScenario(identity,{...order,status:'CLOSED'},quote,scenario),/open/);
 assert.throws(()=>assessPaperMarginScenario(identity,order,quote,{...scenario,assumedMaintenanceRequirementCurrency:0}),/maintenance/);
 assert.throws(()=>assessPaperMarginScenario(identity,order,quote,{...scenario,otherReservedMarginCurrency:-1}),/maintenance/);
 assert.throws(()=>assessPaperMarginScenario({...identity,pointValue:1e308},order,quote,scenario),/Non-finite/);
 assert.throws(()=>assessPaperMarginScenario(identity,order,quote,{...scenario,cashEquityBeforePositionCurrency:Infinity}),/maintenance/);
});
test('pure scenario comparison does not mutate quote, position, cashflows or assumptions',()=>{
 const originalOrder={...order},originalQuote={...quote},originalScenario={...scenario,postedCashflows:[flow()]};
 const originalCashflow={...originalScenario.postedCashflows[0]};
 assessPaperMarginScenario(identity,order,quote,originalScenario);
 assert.deepEqual(order,originalOrder);assert.deepEqual(quote,originalQuote);
 assert.deepEqual(originalScenario.postedCashflows[0],originalCashflow);
});
