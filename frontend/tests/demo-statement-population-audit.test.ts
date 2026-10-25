import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditDeclaredDemoStatementPopulation} from '../lib/demo-statement-population-audit.ts';
import type {DemoLifecycleScope,DemoLifecycleIntent,DemoLifecycleEvent} from '../lib/demo-order-lifecycle-audit.ts';
const scope:DemoLifecycleScope={provider:'Demo',venue:'paper',instrument:'XAUUSD-CFD',
  accountAlias:'a1',quoteCurrency:'USD',statementSha256:'a'.repeat(64),
  quoteBatchSha256:'b'.repeat(64),asOf:5000,maxQuoteAgeMs:100};
const intent=(id:string):DemoLifecycleIntent=>({clientOrderId:id,side:'BUY',
  requestedContracts:2,submittedAt:1000,expiresAt:4000});
const common=(id:string)=>({clientOrderId:id,provider:'Demo',venue:'paper',
  instrument:'XAUUSD-CFD',accountAlias:'a1',statementSha256:'a'.repeat(64)});
const ack=(id:string,brokerId:string):DemoLifecycleEvent=>({...common(id),kind:'ACK',
  eventId:'ack-'+id,brokerOrderId:brokerId,at:1010,recordedAt:1011});
const fill=(id:string,fillId:string):DemoLifecycleEvent=>({...common(id),kind:'FILL',
  eventId:'evt-'+id,fillId,contracts:1,price:'100.100000',commissionCurrency:'0.20',
  quoteId:'q1',quoteObservedAt:1020,quoteBid:'99.900000',quoteAsk:'100.000000',
  quoteBatchSha256:'b'.repeat(64),at:1050,recordedAt:1051});
const orders=[{intent:intent('o1'),events:[ack('o1','b1'),fill('o1','f1')]},
  {intent:intent('o2'),events:[ack('o2','b2')]}];
const manifest={provider:'Demo',venue:'paper',instrument:'XAUUSD-CFD',
  accountAlias:'a1',statementSha256:'a'.repeat(64),
  expectedClientOrderIds:['o1','o2'],expectedEventIds:['ack-o1','evt-o1','ack-o2'],
  expectedFillIds:['f1'],expectedBrokerOrderIds:['b1','b2']};
const audit=(m=manifest,o:typeof orders=orders)=>auditDeclaredDemoStatementPopulation(scope,m,o);
test('matches all four declared identity sets without claiming authenticated completeness',()=>{
  const r=audit();assert.equal(r.status,'DECLARED_POPULATION_MATCH_UNVERIFIED');
  assert.equal(r.observedOrders,2);assert.equal(r.observedEvents,3);
  assert.equal(r.observedFills,1);assert.equal(r.observedTerminalOrders,0);
  assert.equal(r.orderReviews[0].remainingContracts,1);
  assert.equal(r.mayExecuteOrder,false);
});
test('missing declared fill and event are explicitly identified',()=>{
  const r=audit(manifest,[{...orders[0],events:[ack('o1','b1')]},orders[1]]);
  assert.equal(r.status,'DECLARED_POPULATION_MISMATCH');
  assert.deepEqual(r.differences.fillIds.missingDeclaredIds,['f1']);
  assert.deepEqual(r.differences.eventIds.missingDeclaredIds,['evt-o1']);
});
test('unexpected event, fill, and order are identified, not silently accepted',()=>{
  const r=audit({...manifest,expectedClientOrderIds:['o1'],expectedFillIds:[],
    expectedEventIds:['ack-o1','ack-o2']});
  assert.deepEqual(r.differences.clientOrderIds.unexpectedObservedIds,['o2']);
  assert.deepEqual(r.differences.fillIds.unexpectedObservedIds,['f1']);
  assert.deepEqual(r.differences.eventIds.unexpectedObservedIds,['evt-o1']);
});
test('duplicate fill ID across orders fails even when individual lifecycles pass',()=>{
  const o=[orders[0],{...orders[1],events:[ack('o2','b2'),fill('o2','f1')]}];
  assert.throws(()=>audit(manifest,o),/Duplicate cross-order fill/);
});
test('duplicate event ID across orders fails',()=>{
  const o=[orders[0],{...orders[1],events:[{...ack('o2','b2'),eventId:'ack-o1'}]}];
  assert.throws(()=>audit(manifest,o),/Duplicate cross-order event/);
});
test('duplicate broker order ID across different client orders fails',()=>{
  const o=[orders[0],{...orders[1],events:[ack('o2','b1')]}];
  assert.throws(()=>audit(manifest,o),/Duplicate cross-order broker/);
});
test('duplicate client ID fails and cannot be masked by manifest',()=>{
  assert.throws(()=>audit(manifest,[orders[0],orders[0]]),/Duplicate or invalid cross-order client/);
});
test('source mismatches and malformed manifest fail closed',()=>{
  assert.throws(()=>audit({...manifest,provider:'Other'}),/Cross-source/);
  assert.throws(()=>audit({...manifest,expectedEventIds:['ack-o1','ack-o1']}),/duplicate event/);
  assert.throws(()=>audit({...manifest,hidden:true} as typeof manifest),/schema/);
});
test('inherits individual stale-quote and overfill rejection',()=>{
  const o=[{...orders[0],events:[ack('o1','b1'),{...fill('o1','f1'),
    at:1200,recordedAt:1201,quoteObservedAt:1020}]},orders[1]];
  assert.throws(()=>audit(manifest,o),/fill/);
  const over=[{...orders[0],events:[ack('o1','b1'),{...fill('o1','f1'),contracts:3}]},orders[1]];
  assert.throws(()=>audit(manifest,over),/fill/);
});
test('empty event streams cannot be misrepresented as zero exposure',()=>{
  const r=audit({...manifest,expectedEventIds:[],expectedFillIds:[],expectedBrokerOrderIds:[]},
    orders.map(o=>({...o,events:[]})));
  assert.equal(r.status,'DECLARED_POPULATION_MATCH_UNVERIFIED');
  assert.equal(r.observedFills,0);assert.equal(r.orderReviews[0].status,'SUBMITTED');
  assert.match(r.warnings.join(' '),/missing records remain unknown/);
});
test('input is not mutated and order count must be bounded',()=>{
  const before=structuredClone(orders),m=structuredClone(manifest);
  audit();assert.deepEqual(orders,before);assert.deepEqual(manifest,m);
  assert.throws(()=>audit(manifest,[]),/order population/);
});