import {test} from 'node:test';
import assert from 'node:assert/strict';
import {comparePaperWithDemoFills,type DemoFill} from '../lib/demo-fill-reconciliation.ts';
import type {PaperOrder} from '../lib/paper-execution.ts';
const identity={instrument:'XAUUSD-DEMO',provider:'Provider A',venue:'OTC Demo',priceSide:'bid-ask' as const,pointValue:1};
const source={brokerOrderId:'demo-order-7',accountAlias:'sandbox-1',statementSha256:'a'.repeat(64),currency:'GBP'};
const paper:PaperOrder={clientOrderId:'paper-1',instrument:identity.instrument,side:'BUY',units:2,
  submittedAt:100,expiresAt:300,stop:99,target:103,maxSpread:1,maxQuoteAgeSeconds:2,
  maxStopRiskCurrency:10,adverseSlippagePerSide:.1,commissionPerUnitSide:.05,
  status:'CLOSED',entry:100.3,exit:102,entryObservedAt:101,entryReceivedAt:101,
  exitObservedAt:102,exitReceivedAt:102,costs:.2,pnl:3.2,initialStopRisk:3};
const fill=(executionId:string,leg:'ENTRY'|'EXIT',units:number,price:number,changes:Partial<DemoFill>={}):DemoFill=>({
  executionId,brokerOrderId:source.brokerOrderId,clientOrderId:paper.clientOrderId,
  instrument:identity.instrument,provider:identity.provider,venue:identity.venue,
  accountAlias:source.accountAlias,statementSha256:source.statementSha256,currency:source.currency,
  leg,side:leg==='ENTRY'?'BUY':'SELL',units,price,executedAt:leg==='ENTRY'?101:102,
  receivedAt:leg==='ENTRY'?101:102,feeCurrency:.05,...changes});
const compare=(fills:readonly DemoFill[],skew=2,order=paper)=>comparePaperWithDemoFills(identity,order,source,200,skew,fills);
test('compares complete partial demo fills by weighted prices and explicit fees',()=>{
 const r=compare([fill('e1','ENTRY',1,100.2),fill('e2','ENTRY',1,100.4),
  fill('x1','EXIT',.5,102),fill('x2','EXIT',1.5,101.8)]);
 assert.equal(r.status,'COMPARABLE_UNVERIFIED');
 assert.equal(r.uniqueFills,4);assert.equal(r.entryUnits,2);assert.equal(r.exitUnits,2);
 assert.ok(Math.abs(r.demoGrossPnlCurrency!-3.1)<1e-10);
 assert.ok(Math.abs(r.demoKnownNetPnlCurrency!-2.9)<1e-10);
 assert.ok(Math.abs(r.knownNetDeltaCurrency!+0.3)<1e-10);
 assert.equal(r.coverage,'DECLARED_SOURCE_ONLY_FINANCING_UNKNOWN');
});
test('incomplete demo entry/exit never fabricates closed P&L',()=>{
 const r=compare([fill('e1','ENTRY',1,100.2),fill('x1','EXIT',.5,102)]);
 assert.equal(r.status,'INCOMPLETE');assert.equal(r.demoKnownNetPnlCurrency,null);
 assert.equal(r.knownNetDeltaCurrency,null);
});
test('identical duplicate execution IDs are idempotent; conflicting duplicates fail',()=>{
 const a=fill('e1','ENTRY',2,100.3),b=fill('x1','EXIT',2,102);
 assert.equal(compare([a,a,b]).uniqueFills,2);
 assert.throws(()=>compare([a,{...a,price:100.4},b]),/Conflicting duplicate/);
});
test('source isolation blocks account, venue, digest, order and currency mixing',()=>{
 const a=fill('e1','ENTRY',2,100.3),b=fill('x1','EXIT',2,102);
 for(const patch of [{accountAlias:'other'},{venue:'other'},{statementSha256:'b'.repeat(64)},
   {clientOrderId:'other'},{currency:'USD'},{provider:'other'}])
   assert.throws(()=>compare([{...a,...patch},b]),/unprovenanced|unmatched/);
});
test('rejects future-dated, impossible and inverted-side fills',()=>{
 const a=fill('e1','ENTRY',2,100.3),b=fill('x1','EXIT',2,102);
 for(const patch of [{receivedAt:201},{executedAt:203},{side:'SELL' as const},
   {price:0},{units:-1},{feeCurrency:-1}])
   assert.throws(()=>compare([{...a,...patch},b]),/Invalid/);
});
test('overfills, exit before entry and numerical overflow fail closed',()=>{
 assert.throws(()=>compare([fill('e1','ENTRY',3,100),fill('x1','EXIT',2,102)]),/bounds/);
 assert.throws(()=>compare([fill('x1','EXIT',2,102),fill('e1','ENTRY',2,100.3,
   {executedAt:103,receivedAt:103})]),/preceding entry/);
 assert.throws(()=>compare([fill('e1','ENTRY',2,1e308),fill('x1','EXIT',2,102)]),/bounds/);
});
test('timing mismatch is explicitly noncomparable, not a simulated win',()=>{
 const r=compare([fill('e1','ENTRY',2,100.3,{executedAt:120,receivedAt:120}),
  fill('x1','EXIT',2,102,{executedAt:121,receivedAt:121})],2);
 assert.equal(r.status,'TIMING_MISMATCH');assert.equal(r.knownNetDeltaCurrency,null);
 assert.equal(r.maxExecutionSkewSeconds,19);
});
test('forged paper P&L, commission and nonfinite order values are rejected',()=>{
 const fills=[fill('e1','ENTRY',2,100.3),fill('x1','EXIT',2,102)];
 for(const patch of [{pnl:99},{costs:0},{entry:Infinity},{commissionPerUnitSide:Infinity}])
   assert.throws(()=>compare(fills,2,{...paper,...patch}),/Invalid|does not reconcile/);
});
test('strict schema rejects unknown demo fields instead of accepting credentials',()=>{
 const a={...fill('e1','ENTRY',2,100.3),brokerPassword:'should-never-be-stored'};
 assert.throws(()=>compare([a,fill('x1','EXIT',2,102)]),/Invalid/);
});
