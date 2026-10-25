import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditDeclaredDemoQuoteIdentity} from '../lib/demo-quote-identity-audit.ts';
import type {DemoLifecycleScope,DemoLifecycleEvent,DemoLifecycleIntent} from '../lib/demo-order-lifecycle-audit.ts';
import type {DemoStatementOrder,DemoStatementPopulationManifest} from '../lib/demo-statement-population-audit.ts';

const scope:DemoLifecycleScope={provider:'Demo',venue:'paper',instrument:'XAUUSD-CFD',
  accountAlias:'research',quoteCurrency:'USD',statementSha256:'a'.repeat(64),
  quoteBatchSha256:'b'.repeat(64),asOf:5000,maxQuoteAgeMs:100};
const base=(id:string)=>({clientOrderId:id,provider:scope.provider,venue:scope.venue,
  instrument:scope.instrument,accountAlias:scope.accountAlias,
  statementSha256:scope.statementSha256});
const intent=(id:string,side:'BUY'|'SELL'='BUY'):DemoLifecycleIntent=>({
  clientOrderId:id,side,requestedContracts:2,submittedAt:1000,expiresAt:4000
});
const ack=(id:string):DemoLifecycleEvent=>({...base(id),eventId:'ack-'+id,
  kind:'ACK',brokerOrderId:'broker-'+id,at:1010,recordedAt:1011});
type Fill=Extract<DemoLifecycleEvent,{kind:'FILL'}>;
const fill=(id:string,changes:Partial<Fill>={}):Fill=>({...base(id),
  eventId:'fill-'+id,kind:'FILL',fillId:'fill-'+id,contracts:1,
  price:'100.100000',commissionCurrency:'0.20',quoteId:'shared',
  quoteObservedAt:1020,quoteBid:'99.900000',quoteAsk:'100.000000',
  quoteBatchSha256:scope.quoteBatchSha256,at:1050,recordedAt:1051,...changes});
const order=(id:string,events:DemoLifecycleEvent[],side:'BUY'|'SELL'='BUY'):DemoStatementOrder=>
  ({intent:intent(id,side),events});
function manifest(orders:readonly DemoStatementOrder[]):DemoStatementPopulationManifest {
  return {provider:scope.provider,venue:scope.venue,instrument:scope.instrument,
    accountAlias:scope.accountAlias,statementSha256:scope.statementSha256,
    expectedClientOrderIds:orders.map(o=>o.intent.clientOrderId),
    expectedEventIds:orders.flatMap(o=>o.events.map(e=>e.eventId)),
    expectedFillIds:orders.flatMap(o=>o.events.filter(e=>e.kind==='FILL').map(e=>e.fillId)),
    expectedBrokerOrderIds:orders.flatMap(o=>o.events.filter(e=>e.kind==='ACK').map(e=>e.brokerOrderId))};
}
const review=(orders:DemoStatementOrder[],m=manifest(orders))=>
  auditDeclaredDemoQuoteIdentity(scope,m,orders);
const two=(other:Partial<Fill>={})=>[
  order('a',[ack('a'),fill('a')]),
  order('b',[ack('b'),fill('b',other)],'SELL')
];

test('no declared fills is unknown, not proof of zero risk or costs',()=>{
  const r=review([order('a',[ack('a')])]);
  assert.equal(r.status,'NO_DECLARED_FILLS');
  assert.equal(r.fillEvents,0);
  assert.equal(r.distinctQuoteIds,0);
  assert.equal(r.mayExecuteOrder,false);
});
test('one declared fill is consistent but unverified',()=>{
  const r=review([order('a',[ack('a'),fill('a')])]);
  assert.equal(r.status,'CONSISTENT_DECLARED_QUOTE_IDS_UNVERIFIED');
  assert.equal(r.fillEvents,1);
  assert.equal(r.distinctQuoteIds,1);
  assert.equal(r.reusedQuoteIds,0);
});
test('same quote ID across opposing orders may refer to identical snapshot',()=>{
  const r=review(two());
  assert.equal(r.status,'CONSISTENT_DECLARED_QUOTE_IDS_UNVERIFIED');
  assert.equal(r.fillEvents,2);
  assert.equal(r.distinctQuoteIds,1);
  assert.equal(r.reusedQuoteIds,1);
  assert.deepEqual(r.conflictingQuoteIds,[]);
});
test('equivalent decimal representations are not a false conflict',()=>{
  const r=review(two({quoteBid:'99.9',quoteAsk:'100'}));
  assert.equal(r.status,'CONSISTENT_DECLARED_QUOTE_IDS_UNVERIFIED');
});
test('changed bid under reused quote ID fails closed',()=>{
  const r=review(two({quoteBid:'99.800000'}));
  assert.equal(r.status,'CONFLICTING_DECLARED_QUOTE_ID');
  assert.deepEqual(r.conflictingQuoteIds,['shared']);
  assert.deepEqual(r.conflicts,[{quoteId:'shared',
    firstEventId:'fill-a',conflictingEventId:'fill-b'}]);
});
test('changed ask under reused quote ID fails closed',()=>{
  const r=review(two({quoteAsk:'100.010000'}));
  assert.equal(r.status,'CONFLICTING_DECLARED_QUOTE_ID');
  assert.equal(r.conflicts.length,1);
});
test('changed observation timestamp under reused quote ID fails closed',()=>{
  const r=review(two({quoteObservedAt:1021}));
  assert.equal(r.status,'CONFLICTING_DECLARED_QUOTE_ID');
});
test('different quote IDs can legitimately have different bid/ask snapshots',()=>{
  const r=review(two({quoteId:'other',quoteBid:'99.8',quoteAsk:'100.1'}));
  assert.equal(r.status,'CONSISTENT_DECLARED_QUOTE_IDS_UNVERIFIED');
  assert.equal(r.distinctQuoteIds,2);
});
test('missing manifest record suppresses consistent status',()=>{
  const orders=two(),m={...manifest(orders),expectedFillIds:['fill-a']};
  const r=review(orders,m);
  assert.equal(r.status,'DECLARED_POPULATION_MISMATCH');
  assert.equal(r.statementPopulation,'DECLARED_POPULATION_MISMATCH');
});
test('quote conflicts remain visible even if declared population mismatches',()=>{
  const orders=two({quoteBid:'99.8'});
  const m={...manifest(orders),expectedFillIds:[]};
  const r=review(orders,m);
  assert.equal(r.status,'CONFLICTING_DECLARED_QUOTE_ID');
  assert.equal(r.statementPopulation,'DECLARED_POPULATION_MISMATCH');
});
test('upstream cross-order duplicate fill ID is rejected',()=>{
  const orders=two({fillId:'fill-a'});
  assert.throws(()=>review(orders),/duplicate fill/i);
});
test('upstream cross-source and stale quote evidence is rejected',()=>{
  const changed=[order('a',[ack('a'),fill('a',{accountAlias:'other'})])];
  assert.throws(()=>review(changed),/cross-source/i);
  const stale=[order('a',[ack('a'),fill('a',{quoteObservedAt:900})])];
  assert.throws(()=>review(stale),/fill/i);
});
test('input manifests, orders and scope remain unchanged',()=>{
  const orders=two(),m=manifest(orders);
  const snapshot=structuredClone({scope,orders,m});
  review(orders,m);
  assert.deepEqual({scope,orders,m},snapshot);
});
test('consistent records do not authorize execution or prove source authenticity',()=>{
  const r=review(two());
  assert.equal(r.mayExecuteOrder,false);
  assert.match(r.warnings.join(' '),/not authenticated broker evidence/);
  assert.match(r.warnings.join(' '),/No real\/demo broker adapter/);
});
