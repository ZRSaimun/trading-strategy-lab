import {test} from 'node:test';
import assert from 'node:assert/strict';
import {reconcilePaperCashflows,type PaperCashflow} from '../lib/paper-cashflow-reconciliation.ts';
import type {PaperOrder,PaperIdentity} from '../lib/paper-execution.ts';
const identity:PaperIdentity={instrument:'XAUUSD-CFD-DEMO',provider:'Demo Broker',venue:'OTC',priceSide:'bid-ask',pointValue:1};
const order:PaperOrder={clientOrderId:'o1',instrument:identity.instrument,side:'BUY',units:2,
 submittedAt:100,expiresAt:500,stop:99,target:102,maxSpread:.5,maxQuoteAgeSeconds:2,
 maxStopRiskCurrency:10,adverseSlippagePerSide:.1,commissionPerUnitSide:.05,
 status:'CLOSED',entry:100.3,entryObservedAt:101,entryReceivedAt:101,
 exit:102,exitObservedAt:110,exitReceivedAt:110,costs:.2,pnl:3.2};
const cash=(changes:Partial<PaperCashflow>={}):PaperCashflow=>({id:'swap-1',orderId:'o1',instrument:identity.instrument,
 provider:identity.provider,venue:identity.venue,at:105,kind:'OVERNIGHT_FINANCING',amountCurrency:-.4,
 reference:'User-declared hypothetical broker swap',...changes});

test('adjusts price-and-commission paper P&L by explicit financing and FX charges',()=>{
 const result=reconcilePaperCashflows(identity,order,115,[cash(),cash({id:'fx-1',kind:'FX_CONVERSION',amountCurrency:-.1})]);
 assert.ok(Math.abs(result.knownCashflowAdjustedPnlCurrency-2.7)<1e-10);
 assert.equal(result.acceptedCashflows,2);
 assert.equal(result.coverage,'PARTIAL_UNVERIFIED');
 assert.equal(result.cashflowCurrency.OVERNIGHT_FINANCING,-.4);
});
test('duplicate event IDs are idempotent but conflicting duplicates are rejected',()=>{
 assert.equal(reconcilePaperCashflows(identity,order,115,[cash(),cash()]).acceptedCashflows,1);
 assert.throws(()=>reconcilePaperCashflows(identity,order,115,[cash(),cash({amountCurrency:-.8})]),/Conflicting duplicate/);
});
test('rejects mismatched identity, unrecognized charges and impossible times',()=>{
 for(const change of [{provider:'other'},{instrument:'NDX'},{venue:'other'},{kind:'OTHER' as PaperCashflow['kind']},
  {at:100},{at:116},{amountCurrency:Infinity},{reference:'  '},{id:''}]){
  assert.throws(()=>reconcilePaperCashflows(identity,order,115,[cash(change)]),/Invalid/);
 }
});
test('refuses unclosed or tampered orders and invalid multipliers',()=>{
 assert.throws(()=>reconcilePaperCashflows(identity,{...order,status:'OPEN'},115,[]),/closed/);
 assert.throws(()=>reconcilePaperCashflows(identity,{...order,pnl:4},115,[]),/reconcile/);
 assert.throws(()=>reconcilePaperCashflows({...identity,pointValue:2},order,115,[]),/reconcile/);
 assert.throws(()=>reconcilePaperCashflows(identity,order,109,[]),/closed/);
});
test('late posted charges require an explicit settlement cutoff and may be credits',()=>{
 const late=cash({at:120,amountCurrency:.25});
 assert.throws(()=>reconcilePaperCashflows(identity,order,115,[late]),/future/);
 const result=reconcilePaperCashflows(identity,order,120,[late]);
 assert.ok(Math.abs(result.knownCashflowAdjustedPnlCurrency-3.45)<1e-10);
});
test('missing cashflows never imply a broker-reconciled net result',()=>{
 const result=reconcilePaperCashflows(identity,order,110,[]);
 assert.equal(result.knownCashflowAdjustedPnlCurrency,3.2);
 assert.equal(result.coverage,'PARTIAL_UNVERIFIED');
 assert.equal(result.acceptedCashflows,0);
});
test('rejects arithmetic overflow rather than exporting an infinite net result',()=>{
 assert.throws(()=>reconcilePaperCashflows(identity,order,115,[cash({amountCurrency:1e308}),cash({id:'swap-2',amountCurrency:1e308})]),/overflow/);
});
test('SELL reconciliation preserves the correct direction and cashflow sign',()=>{
 const short:PaperOrder={...order,side:'SELL',entry:99.9,exit:98,pnl:3.6};
 const result=reconcilePaperCashflows(identity,short,115,[cash({amountCurrency:-.5})]);
 assert.ok(Math.abs(result.knownCashflowAdjustedPnlCurrency-3.1)<1e-10);
});
test('reconciliation is pure and never mutates the order or source cashflow',()=>{
 const original={...order};const entry=cash();const before={...entry};
 reconcilePaperCashflows(identity,order,115,[entry]);
 assert.deepEqual(order,original);assert.deepEqual(entry,before);
});

test('does not accept a forged commission even when net P&L is changed to agree with it',()=>{
 // A forged zero-commission record previously passed because the two
 // caller-controlled fields were checked against each other only.
 const changed={...order,costs:0,pnl:3.4};
 assert.throws(()=>reconcilePaperCashflows(identity,changed,115,[]),/reconcile/);
 assert.throws(()=>reconcilePaperCashflows(identity,{...order,commissionPerUnitSide:0},115,[]),/reconcile/);
 // Correctly recomputed commission-inclusive records still pass.
 assert.equal(reconcilePaperCashflows(identity,order,115,[]).basePaperPnlCurrency,3.2);
});
test('rejects impossible fill chronology and missing observed-time evidence',()=>{
 for(const changed of [
  {entryObservedAt:undefined},{exitObservedAt:undefined},
  {entryObservedAt:100},{entryReceivedAt:100},
  {entryReceivedAt:501},{exitObservedAt:101},
  {exitObservedAt:111},{exitReceivedAt:100},
  {exitReceivedAt:116},{submittedAt:102},
  {expiresAt:100}
 ]){
  assert.throws(()=>reconcilePaperCashflows(identity,{...order,...changed},115,[]),/closed, chronologically valid/);
 }
});
test('rejects non-positive fill prices and malformed trade direction',()=>{
 for(const changed of [
  {entry:0},{exit:-1},{entry:Infinity},{exit:NaN},
  {side:'HOLD' as PaperOrder['side']}
 ]){
  assert.throws(()=>reconcilePaperCashflows(identity,{...order,...changed},115,[]),/closed, chronologically valid/);
 }
});
