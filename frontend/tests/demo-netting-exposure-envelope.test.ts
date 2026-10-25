import {test} from 'node:test';
import assert from 'node:assert/strict';
import {reviewDeclaredDemoNettingEnvelope} from '../lib/demo-netting-exposure-envelope.ts';
import type {DeclaredNettingPolicy} from '../lib/demo-netting-exposure-envelope.ts';
import type {DemoLifecycleScope,DemoLifecycleIntent,DemoLifecycleEvent} from '../lib/demo-order-lifecycle-audit.ts';
import type {DemoStatementOrder,DemoStatementPopulationManifest} from '../lib/demo-statement-population-audit.ts';

const scope:DemoLifecycleScope={provider:'Demo',venue:'paper',instrument:'XAUUSD-CFD',
  accountAlias:'research',quoteCurrency:'USD',statementSha256:'a'.repeat(64),
  quoteBatchSha256:'b'.repeat(64),asOf:5000,maxQuoteAgeMs:100};
const policy:DeclaredNettingPolicy={positionMode:'NETTING',startingNetContracts:0,maxAbsContracts:2};
const intent=(id:string,side:'BUY'|'SELL',requestedContracts=2):DemoLifecycleIntent=>
  ({clientOrderId:id,side,requestedContracts,submittedAt:1000,expiresAt:4000});
const base=(id:string)=>({clientOrderId:id,provider:'Demo',venue:'paper',
  instrument:'XAUUSD-CFD',accountAlias:'research',statementSha256:'a'.repeat(64)});
const ack=(id:string):DemoLifecycleEvent=>({...base(id),eventId:'ack-'+id,kind:'ACK',
  brokerOrderId:'broker-'+id,at:1010,recordedAt:1011});
const fill=(id:string,contracts=1):Extract<DemoLifecycleEvent,{kind:'FILL'}>=>({...base(id),eventId:'evt-'+id,
  kind:'FILL',fillId:'fill-'+id,contracts,price:'100.100000',
  commissionCurrency:'0.20',quoteId:'quote-'+id,quoteObservedAt:1020,
  quoteBid:'99.900000',quoteAsk:'100.000000',
  quoteBatchSha256:'b'.repeat(64),at:1050,recordedAt:1051});
const event=(id:string,kind:'CANCEL_REQUESTED'|'CANCELED'|'EXPIRED'|'REJECTED',
  at:number):DemoLifecycleEvent=>({...base(id),eventId:kind+'-'+id,
    kind,at,recordedAt:at+1});
const order=(id:string,side:'BUY'|'SELL',events:DemoLifecycleEvent[],
  requestedContracts=2):DemoStatementOrder=>({intent:intent(id,side,requestedContracts),events});
function manifest(orders:readonly DemoStatementOrder[]):DemoStatementPopulationManifest {
  return {provider:scope.provider,venue:scope.venue,instrument:scope.instrument,
    accountAlias:scope.accountAlias,statementSha256:scope.statementSha256,
    expectedClientOrderIds:orders.map(o=>o.intent.clientOrderId),
    expectedEventIds:orders.flatMap(o=>o.events.map(e=>e.eventId)),
    expectedFillIds:orders.flatMap(o=>o.events.filter(e=>e.kind==='FILL').map(e=>e.fillId)),
    expectedBrokerOrderIds:orders.flatMap(o=>o.events.filter(e=>e.kind==='ACK').map(e=>e.brokerOrderId))};
}
function review(orders:DemoStatementOrder[],p=policy,m=manifest(orders)){
  return reviewDeclaredDemoNettingEnvelope(scope,m,orders,p);
}
test('opposing partial fills produce signed reachable NETTING envelope',()=>{
  const orders=[order('buy','BUY',[ack('buy'),fill('buy')]),
    order('sell','SELL',[ack('sell'),fill('sell')],3)];
  const r=review(orders);
  assert.equal(r.status,'WITHIN_DECLARED_CAP_UNVERIFIED');
  assert.equal(r.netFilledPositionContracts,0);
  assert.equal(r.grossBuyFilledContracts,1);
  assert.equal(r.grossSellFilledContracts,1);
  assert.equal(r.pendingBuyContracts,1);
  assert.equal(r.pendingSellContracts,2);
  assert.equal(r.minimumReachableNetContracts,-2);
  assert.equal(r.maximumReachableNetContracts,1);
  assert.equal(r.worstCaseAbsoluteContracts,2);
  assert.equal(r.mayExecuteOrder,false);
});
test('cancel request does not release unfilled quantity',()=>{
  const orders=[order('buy','BUY',[ack('buy'),fill('buy'),
    event('buy','CANCEL_REQUESTED',1100)])];
  const r=review(orders);
  assert.equal(r.cancelPendingOrders,1);
  assert.equal(r.netFilledPositionContracts,1);
  assert.equal(r.pendingBuyContracts,1);
  assert.equal(r.maximumReachableNetContracts,2);
});
test('confirmed cancellation releases remaining order but retains filled position',()=>{
  const orders=[order('buy','BUY',[ack('buy'),fill('buy'),
    event('buy','CANCEL_REQUESTED',1100),event('buy','CANCELED',1200)])];
  const r=review(orders);
  assert.equal(r.pendingBuyContracts,0);
  assert.equal(r.netFilledPositionContracts,1);
  assert.equal(r.minimumReachableNetContracts,1);
  assert.equal(r.maximumReachableNetContracts,1);
});
test('unacknowledged submitted orders conservatively remain outstanding',()=>{
  const r=review([order('buy','BUY',[])]);
  assert.equal(r.submittedUnacknowledgedOrders,1);
  assert.equal(r.pendingBuyContracts,2);
  assert.equal(r.worstCaseAbsoluteContracts,2);
});
test('intent expiry clock alone does not imply broker expiry',()=>{
  const r=review([order('buy','BUY',[ack('buy')])]);
  assert.equal(r.pendingBuyContracts,2);
  assert.equal(r.status,'WITHIN_DECLARED_CAP_UNVERIFIED');
});
test('explicit expiry event removes remaining exposure but retains partial fill',()=>{
  const r=review([order('buy','BUY',[ack('buy'),fill('buy'),
    event('buy','EXPIRED',4000)])]);
  assert.equal(r.pendingBuyContracts,0);
  assert.equal(r.netFilledPositionContracts,1);
});
test('rejected order has no remaining executable quantity',()=>{
  const r=review([order('sell','SELL',[event('sell','REJECTED',1010)])]);
  assert.equal(r.pendingSellContracts,0);
  assert.equal(r.netFilledPositionContracts,0);
});
test('declared cap breaches include pending orders even without fills',()=>{
  const r=review([order('buy','BUY',[],3)]);
  assert.equal(r.status,'DECLARED_CAP_EXCEEDED');
  assert.equal(r.worstCaseAbsoluteContracts,3);
});
test('signed starting inventory changes reachable net range',()=>{
  const r=review([order('sell','SELL',[],2)],{...policy,startingNetContracts:-2,maxAbsContracts:3});
  assert.equal(r.netFilledPositionContracts,-2);
  assert.equal(r.minimumReachableNetContracts,-4);
  assert.equal(r.status,'DECLARED_CAP_EXCEEDED');
});
test('missing expected records suppress within-cap conclusion',()=>{
  const orders=[order('buy','BUY',[ack('buy')])];
  const m={...manifest(orders),expectedEventIds:['ack-buy','missing']};
  const r=review(orders,policy,m);
  assert.equal(r.statementPopulation,'DECLARED_POPULATION_MISMATCH');
  assert.equal(r.status,'DECLARED_POPULATION_UNVERIFIABLE');
});
test('extra observed records also suppress within-cap conclusion',()=>{
  const orders=[order('buy','BUY',[ack('buy')])];
  const m={...manifest(orders),expectedEventIds:[]};
  assert.equal(review(orders,policy,m).status,'DECLARED_POPULATION_UNVERIFIABLE');
});
test('rejects unsupported hedging, fractional, negative, excessive and hidden policy fields',()=>{
  const orders=[order('buy','BUY',[])];
  assert.throws(()=>review(orders,{...policy,positionMode:'HEDGING'} as unknown as DeclaredNettingPolicy),/mode/);
  assert.throws(()=>review(orders,{...policy,maxAbsContracts:0}),/cap/);
  assert.throws(()=>review(orders,{...policy,maxAbsContracts:1.5}),/cap/);
  assert.throws(()=>review(orders,{...policy,startingNetContracts:Infinity}),/cap/);
  assert.throws(()=>review(orders,{...policy,startingNetContracts:1_000_000_001}),/cap/);
  assert.throws(()=>review(orders,{...policy,liveTrading:true} as DeclaredNettingPolicy),/schema/);
});
test('inherits cross-order duplicate and cross-source failures',()=>{
  const orders=[order('a','BUY',[ack('a')]),order('b','SELL',[ack('b')])];
  const duplicate=[orders[0],order('b','SELL',[{...ack('b'),eventId:'ack-a'}])];
  assert.throws(()=>review(duplicate),/duplicate event/i);
  const changed=[order('a','BUY',[{...ack('a'),accountAlias:'other'}])];
  assert.throws(()=>review(changed),/cross-source/);
});
test('inherits stale quote and overfill rejection before reporting exposure',()=>{
  const stale=[order('a','BUY',[ack('a'),{...fill('a'),quoteObservedAt:900}])];
  assert.throws(()=>review(stale),/fill/);
  const over=[order('a','BUY',[ack('a'),fill('a',3)])];
  assert.throws(()=>review(over),/fill/);
});
test('does not mutate source statements, policy or order records',()=>{
  const orders=[order('buy','BUY',[ack('buy'),fill('buy')])];
  const m=manifest(orders),snapshot=structuredClone({orders,m,policy});
  review(orders,policy,m);
  assert.deepEqual({orders,m,policy},snapshot);
});
test('status is never a real broker limit or trading approval',()=>{
  const r=review([order('buy','BUY',[ack('buy')])]);
  assert.equal(r.mayExecuteOrder,false);
  assert.match(r.warnings.join(' '),/not authenticated broker evidence/);
  assert.match(r.warnings.join(' '),/never an execution approval/);
});
