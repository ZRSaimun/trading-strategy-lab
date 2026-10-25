import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditDeclaredDemoQuoteDeviations} from '../lib/demo-quote-deviation-audit.ts';
import type {DemoLifecycleScope,DemoLifecycleIntent,DemoLifecycleEvent} from '../lib/demo-order-lifecycle-audit.ts';
const scope:DemoLifecycleScope={provider:'Demo',venue:'paper',instrument:'XAUUSD-CFD',
  accountAlias:'test',quoteCurrency:'USD',statementSha256:'a'.repeat(64),
  quoteBatchSha256:'b'.repeat(64),asOf:3000,maxQuoteAgeMs:100};
const buy:DemoLifecycleIntent={clientOrderId:'o1',side:'BUY',requestedContracts:3,
  submittedAt:1000,expiresAt:2500};
const common={clientOrderId:'o1',provider:'Demo',venue:'paper',instrument:'XAUUSD-CFD',
  accountAlias:'test',statementSha256:'a'.repeat(64)};
const ack:DemoLifecycleEvent={...common,kind:'ACK',eventId:'ack',brokerOrderId:'b1',at:1010,recordedAt:1011};
const fill:DemoLifecycleEvent={...common,kind:'FILL',eventId:'f1',fillId:'fill1',
  at:1100,recordedAt:1101,contracts:2,price:'100.150000',commissionCurrency:'0.10',
  quoteId:'q1',quoteObservedAt:1050,quoteBid:'99.900000',quoteAsk:'100.100000',
  quoteBatchSha256:'b'.repeat(64)};
const policy={maxAdversePerContract:'0.100000',maxFavorablePerContract:'0.100000'};
const audit=(intent=buy,events:readonly DemoLifecycleEvent[]=[ack,fill],p=policy)=>
  auditDeclaredDemoQuoteDeviations(scope,intent,events,p);
test('buy: positive adverse deviation plus half-spread, exact integer arithmetic',()=>{
  const r=audit();assert.equal(r.status,'IN_RANGE_UNVERIFIED');
  assert.equal(r.totalSignedSlippagePriceUnits,'0.100000');
  assert.equal(r.totalHalfSpreadPriceUnits,'0.2000000');
  assert.equal(r.totalSignedMidpointImpactPriceUnits,'0.3000000');
  assert.equal(r.remainingContracts,1);assert.equal(r.mayExecuteOrder,false);
});
test('sell: adverse deviation relative to bid uses reversed sign',()=>{
  const r=audit({...buy,side:'SELL'},[ack,{...fill,price:'99.800000'}]);
  assert.equal(r.totalSignedSlippagePriceUnits,'0.200000');
  assert.equal(r.totalSignedMidpointImpactPriceUnits,'0.4000000');
});
test('favorable fill is negative signed slippage, even if midpoint impact negative',()=>{
  const r=audit(buy,[ack,{...fill,price:'99.800000'}],
    {...policy,maxFavorablePerContract:'0.500000'});
  assert.equal(r.totalSignedSlippagePriceUnits,'-0.600000');
  assert.equal(r.totalSignedMidpointImpactPriceUnits,'-0.4000000');
});
test('flags but does not invent currency loss for out-of-policy fills',()=>{
  const r=audit(buy,[ack,{...fill,price:'100.250000'}]);
  assert.equal(r.status,'OUT_OF_RANGE_UNVERIFIED');
  assert.equal(r.rows[0].outsideDeclaredPolicy,true);
  assert.equal(r.mayExecuteOrder,false);
});
test('no fills are unknown, not zero price impact',()=>{
  const r=audit(buy,[ack]);assert.equal(r.status,'NO_DECLARED_FILLS');
  assert.equal(r.totalSignedSlippagePriceUnits,null);
  assert.equal(r.totalHalfSpreadPriceUnits,null);
});
test('invalid policy or hidden fields fail closed',()=>{
  assert.throws(()=>audit(buy,[ack,fill],{...policy,maxAdversePerContract:'-1'}),/decimal/);
  assert.throws(()=>audit(buy,[ack,fill],{...policy,secret:'abc'} as typeof policy),/schema/);
});
test('lifecycle source and fill checks run before quote deviation calculation',()=>{
  assert.throws(()=>audit(buy,[ack,{...fill,quoteBatchSha256:'c'.repeat(64)}]),/fill/);
  assert.throws(()=>audit(buy,[ack,{...fill,contracts:4}]),/fill/);
});
test('quote midpoint can be half of a micro price unit, without rounding loss',()=>{
  const r=audit(buy,[ack,{...fill,contracts:1,price:'100.000001',
    quoteBid:'100.000000',quoteAsk:'100.000001'}]);
  assert.equal(r.totalHalfSpreadPriceUnits,'0.0000005');
  assert.equal(r.totalSignedMidpointImpactPriceUnits,'0.0000005');
});
test('does not mutate declared event population or policy',()=>{
  const events=[ack,fill];const before=structuredClone(events);const p=structuredClone(policy);
  audit(buy,events,policy);assert.deepEqual(events,before);assert.deepEqual(policy,p);
});
