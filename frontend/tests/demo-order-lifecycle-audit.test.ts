import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditDeclaredDemoOrderLifecycle,type DemoLifecycleScope,type DemoLifecycleIntent,
  type DemoLifecycleEvent} from '../lib/demo-order-lifecycle-audit.ts';
const scope:DemoLifecycleScope={provider:'Demo',venue:'paper',instrument:'XAUUSD-CFD',
  accountAlias:'test',quoteCurrency:'USD',statementSha256:'a'.repeat(64),
  quoteBatchSha256:'b'.repeat(64),asOf:3000,maxQuoteAgeMs:100};
const intent:DemoLifecycleIntent={clientOrderId:'order1',side:'BUY',
  requestedContracts:3,submittedAt:1000,expiresAt:2500};
const base={clientOrderId:'order1',provider:'Demo',venue:'paper',
  instrument:'XAUUSD-CFD',accountAlias:'test',statementSha256:'a'.repeat(64)};
const ack:DemoLifecycleEvent={...base,eventId:'a1',kind:'ACK',at:1010,recordedAt:1011,brokerOrderId:'broker1'};
const fill1:DemoLifecycleEvent={...base,eventId:'f1',kind:'FILL',at:1100,recordedAt:1101,
  fillId:'fill1',contracts:1,price:'100.10',commissionCurrency:'0.10',
  quoteId:'q1',quoteObservedAt:1050,quoteBid:'99.90',quoteAsk:'100.00',
  quoteBatchSha256:'b'.repeat(64)};
const fill2:DemoLifecycleEvent={...base,eventId:'f2',kind:'FILL',at:1200,recordedAt:1201,
  fillId:'fill2',contracts:2,price:'100.40',commissionCurrency:'0.20',
  quoteId:'q2',quoteObservedAt:1150,quoteBid:'100.10',quoteAsk:'100.30',
  quoteBatchSha256:'b'.repeat(64)};
const event=(kind:'CANCEL_REQUESTED'|'CANCELED'|'EXPIRED'|'REJECTED',id:string,at:number):DemoLifecycleEvent=>
  ({...base,kind,eventId:id,at,recordedAt:at+1});
const run=(events:readonly DemoLifecycleEvent[],s=scope,i=intent)=>
  auditDeclaredDemoOrderLifecycle(s,i,events);
test('no events remain submitted; no fabricated fills',()=>{
  const r=run([]);assert.equal(r.status,'SUBMITTED');assert.equal(r.filledContracts,0);
  assert.equal(r.remainingContracts,3);assert.equal(r.averageFillPrice,null);assert.equal(r.terminal,false);
});
test('acknowledged without fills remains open',()=>{
  const r=run([ack]);assert.equal(r.status,'ACKNOWLEDGED');assert.equal(r.brokerOrderId,'broker1');
});
test('partial then full fill computes exact weighted price and commissions',()=>{
  const r=run([ack,fill1,fill2]);assert.equal(r.status,'FILLED');assert.equal(r.terminal,true);
  assert.equal(r.filledContracts,3);assert.equal(r.remainingContracts,0);
  assert.equal(r.averageFillPrice,'100.300000');assert.equal(r.totalCommissionCurrency,'0.30');
});
test('partial fill then cancellation retains exposure',()=>{
  const r=run([ack,fill1,event('CANCEL_REQUESTED','c1',1110),event('CANCELED','c2',1130)]);
  assert.equal(r.status,'CANCELED');assert.equal(r.filledContracts,1);assert.equal(r.remainingContracts,2);
});
test('cancel request does not imply broker cancellation; late partial fill accepted',()=>{
  const r=run([ack,event('CANCEL_REQUESTED','c1',1020),fill1]);
  assert.equal(r.status,'CANCEL_PENDING');assert.equal(r.filledContracts,1);assert.equal(r.terminal,false);
});
test('cancel pending can still become fully filled',()=>{
  const r=run([ack,event('CANCEL_REQUESTED','c1',1020),fill1,fill2]);
  assert.equal(r.status,'FILLED');assert.equal(r.remainingContracts,0);
});
test('pre-acceptance reject is terminal; no acknowledgment required',()=>{
  const r=run([event('REJECTED','r1',1010)]);assert.equal(r.status,'REJECTED');
  assert.equal(r.brokerOrderId,null);
});
test('expiry must occur at deadline and retains partial fills',()=>{
  assert.throws(()=>run([ack,event('EXPIRED','e1',2499)]),/expiry/);
  const r=run([ack,fill1,event('EXPIRED','e1',2500)]);
  assert.equal(r.status,'EXPIRED');assert.equal(r.filledContracts,1);
});
test('rejects fill without ack and fills after terminal state',()=>{
  assert.throws(()=>run([fill1]),/fill/);
  assert.throws(()=>run([ack,fill1,fill2,event('CANCELED','c1',1210)]),/terminal/);
  assert.throws(()=>run([ack,event('CANCELED','c1',1110),fill2]),/terminal/);
});
test('rejects duplicate event and fill identifiers',()=>{
  assert.throws(()=>run([ack,{...fill1,eventId:'a1'}]),/Duplicate/);
  assert.throws(()=>run([ack,fill1,{...fill2,fillId:'fill1'}]),/fill/);
});
test('rejects overfill and zero or fractional contracts',()=>{
  assert.throws(()=>run([ack,fill1,{...fill2,contracts:3}]),/fill/);
  assert.throws(()=>run([ack,{...fill1,contracts:0}]),/fill/);
  assert.throws(()=>run([ack,{...fill1,contracts:0.5}]),/fill/);
});
test('rejects stale, pre-order, future and wrong-source quotes',()=>{
  assert.throws(()=>run([ack,{...fill1,quoteObservedAt:999}]),/fill/);
  assert.throws(()=>run([ack,{...fill1,quoteObservedAt:900}]),/fill/);
  assert.throws(()=>run([ack,{...fill1,quoteObservedAt:1101}]),/fill/);
  assert.throws(()=>run([ack,{...fill1,quoteBatchSha256:'c'.repeat(64)}]),/fill/);
});
test('rejects crossed or zero quote and invalid price or commission',()=>{
  assert.throws(()=>run([ack,{...fill1,quoteBid:'100.10',quoteAsk:'100.00'}]),/bid\/ask/);
  assert.throws(()=>run([ack,{...fill1,price:'0'}]),/price/);
  assert.throws(()=>run([ack,{...fill1,commissionCurrency:'-0.10'}]),/commission/);
});
test('rejects cross-account, instrument, statement and extra hidden fields',()=>{
  assert.throws(()=>run([ack,{...fill1,accountAlias:'other'}]),/cross-source/);
  assert.throws(()=>run([ack,{...fill1,statementSha256:'c'.repeat(64)}]),/cross-source/);
  assert.throws(()=>run([ack,{...fill1,realizedProfit:'500'} as DemoLifecycleEvent]),/schema/);
});
test('rejects retroactive, future, or non-monotonic event and receipt times',()=>{
  assert.throws(()=>run([ack,{...fill1,at:1009}]),/out-of-order/);
  assert.throws(()=>run([ack,{...fill1,recordedAt:1100},{...fill2,recordedAt:1099}]),/out-of-order/);
  assert.throws(()=>run([ack,{...fill1,recordedAt:3001}]),/future/);
  assert.throws(()=>run([ack,{...fill1,recordedAt:1099}]),/out-of-order/);
});
test('rejects repeated ACK, repeated cancellation request and unsupported transitions',()=>{
  assert.throws(()=>run([ack,{...ack,eventId:'a2',at:1020,recordedAt:1021}]),/acknowledgment/);
  assert.throws(()=>run([ack,event('CANCEL_REQUESTED','c1',1020),event('CANCEL_REQUESTED','c2',1030)]),/cancel request/);
  assert.throws(()=>run([ack,event('REJECTED','r1',1020)]),/rejection/);
});
test('source metadata and clock must be explicit and bounded',()=>{
  assert.throws(()=>run([],{...scope,quoteCurrency:'USDT'}),/source/);
  assert.throws(()=>run([],{...scope,asOf:999}),/intent/);
  assert.throws(()=>run([],{...scope,maxQuoteAgeMs:0}),/source/);
  assert.throws(()=>run([],{...scope,extra:'ignored'} as DemoLifecycleScope),/schema/);
});
test('does not mutate source events',()=>{
  const before=structuredClone([ack,fill1,fill2]);run([ack,fill1,fill2]);
  assert.deepEqual([ack,fill1,fill2],before);
});
