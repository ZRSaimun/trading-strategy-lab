import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditDeclaredQuoteExecutions,type QuoteExecutionScope,type DeclaredOrder,
  type DeclaredQuote,type DeclaredFill} from '../lib/declared-quote-execution-audit.ts';
const scope:QuoteExecutionScope={provider:'SyntheticBroker',venue:'demo',instrument:'XAUUSD-CFD',
  accountAlias:'paper-1',quoteStreamId:'feed-A',quoteCurrency:'USD',quoteBatchSha256:'a'.repeat(64),
  asOf:2000,maxQuoteAgeMs:200,cashPerPricePointPerContract:'2'};
const orders:DeclaredOrder[]=[{orderId:'o1',side:'BUY',requestedContracts:3,submittedAt:1000}];
const quote:DeclaredQuote={quoteId:'q1',provider:scope.provider,venue:scope.venue,
  instrument:scope.instrument,quoteStreamId:scope.quoteStreamId,
  quoteBatchSha256:scope.quoteBatchSha256,observedAt:1010,bid:'99.90',ask:'100.10'};
const fill:DeclaredFill={fillId:'f1',orderId:'o1',provider:scope.provider,venue:scope.venue,
  instrument:scope.instrument,accountAlias:scope.accountAlias,quoteId:'q1',
  filledAt:1050,filledContracts:3,price:'100.15',commissionCurrency:'0.20'};
const run=(s=scope,o:readonly DeclaredOrder[]=orders,q:readonly DeclaredQuote[]=[quote],
  f:readonly DeclaredFill[]=[fill])=>auditDeclaredQuoteExecutions(s,o,q,f);
test('exact midpoint half-spread, side slippage, commission and total',()=>{
  const a=run();assert.equal(a.status,'COMPLETE_DECLARED');
  assert.equal(a.coverage,'SELF_DECLARED_QUOTE_AND_FILL_EVIDENCE_ONLY');
  assert.equal(a.completeFrictionCurrency,'1.1000000000000');
  assert.deepEqual(a.fillFriction.map(f=>[f.halfSpreadCurrency,f.slippageCurrency,
    f.commissionCurrency,f.quoteAgeMs]),[['0.6000000000000','0.3000000000000','0.2000000000000',40]]);
});
test('sell fill compares against bid and supports favorable slippage',()=>{
  const a=run(scope,[{...orders[0],side:'SELL'}],[quote],[{...fill,price:'99.95'}]);
  assert.equal(a.fillFriction[0].slippageCurrency,'-0.3000000000000');
  assert.equal(a.completeFrictionCurrency,'0.5000000000000');
});
test('zero-spread and microprice costs retain half-micro precision',()=>{
  const a=run({...scope,cashPerPricePointPerContract:'0.000001'},orders,
    [{...quote,bid:'1.000000',ask:'1.000001'}],[{...fill,price:'1.000001',commissionCurrency:'0'}]);
  assert.equal(a.fillFriction[0].halfSpreadCurrency,'0.0000000000015');
  assert.equal(a.completeFrictionCurrency,'0.0000000000015');
});
test('partial fill withholds complete friction; no fill never means zero cost',()=>{
  const a=run(scope,orders,[quote],[{...fill,filledContracts:1}]);
  assert.equal(a.status,'PARTIAL_DECLARED');assert.equal(a.completeFrictionCurrency,null);
  assert.deepEqual(a.unfilledOrderIds,['o1']);
  const b=run(scope,orders,[],[]);
  assert.equal(b.status,'NO_DECLARED_FILLS');assert.equal(b.completeFrictionCurrency,null);
});
test('multiple partial fills reconcile exactly to requested contracts',()=>{
  const q2={...quote,quoteId:'q2',observedAt:1020};
  const f1={...fill,filledContracts:1};
  const f2={...fill,fillId:'f2',quoteId:'q2',filledContracts:2};
  const a=run(scope,orders,[quote,q2],[f1,f2]);
  assert.equal(a.status,'COMPLETE_DECLARED');assert.equal(a.filledContracts,3);
  assert.equal(a.completeFrictionCurrency,'1.3000000000000');
});
test('rejects overfills, orphan fills, duplicate fill IDs and duplicate order IDs',()=>{
  assert.throws(()=>run(scope,orders,[quote],[{...fill,filledContracts:4}]),/exceeds/);
  assert.throws(()=>run(scope,orders,[quote],[{...fill,orderId:'missing'}]),/fill/);
  assert.throws(()=>run(scope,orders,[quote],[fill,fill]),/duplicate/);
  assert.throws(()=>run(scope,[...orders,...orders],[quote],[fill]),/duplicate/);
});
test('rejects stale quotes, quotes after fills and fills before order submission',()=>{
  assert.throws(()=>run({...scope,maxQuoteAgeMs:20}),/stale/);
  assert.throws(()=>run(scope,orders,[{...quote,observedAt:1051}]),/stale/);
  assert.throws(()=>run(scope,orders,[quote],[{...fill,filledAt:999}]),/stale/);
});
test('rejects future quote, future fill and future order',()=>{
  assert.throws(()=>run(scope,orders,[{...quote,observedAt:2001}]),/future/);
  assert.throws(()=>run(scope,orders,[quote],[{...fill,filledAt:2001}]),/future/);
  assert.throws(()=>run(scope,[{...orders[0],submittedAt:2001}],[quote],[fill]),/future/);
});
test('rejects crossed markets and nonpositive quote/fill/multiplier prices',()=>{
  assert.throws(()=>run(scope,orders,[{...quote,bid:'100.11'}]),/Crossed/);
  assert.throws(()=>run(scope,orders,[{...quote,bid:'0'}]),/Zero bid/);
  assert.throws(()=>run(scope,orders,[quote],[{...fill,price:'0'}]),/Zero fill/);
  assert.throws(()=>run({...scope,cashPerPricePointPerContract:'0'}),/Zero cash/);
});
test('rejects cross-provider, venue, instrument, stream, hash and account mixing',()=>{
  for(const patch of [{provider:'Other'},{venue:'live'},{instrument:'WTI-CFD'},
    {quoteStreamId:'other'},{quoteBatchSha256:'b'.repeat(64)}])
    assert.throws(()=>run(scope,orders,[{...quote,...patch}]),/cross-source/);
  for(const patch of [{provider:'Other'},{venue:'live'},{instrument:'WTI-CFD'},
    {accountAlias:'other'}])
    assert.throws(()=>run(scope,orders,[quote],[{...fill,...patch}]),/cross-source/);
});
test('rejects unmatched or duplicate quote snapshots, including cherry-picked extras',()=>{
  assert.throws(()=>run(scope,orders,[quote,{...quote,quoteId:'unused'}]),/Unmatched/);
  assert.throws(()=>run(scope,orders,[quote,quote]),/duplicate/);
  assert.throws(()=>run(scope,orders,[],[fill]),/fill/);
});
test('rejects fabricated P&L fields and unknown schemas',()=>{
  assert.throws(()=>run({...scope,netReturn:5} as QuoteExecutionScope),/schema/);
  assert.throws(()=>run(scope,[{...orders[0],profit:10} as DeclaredOrder]),/schema/);
  assert.throws(()=>run(scope,orders,[{...quote,realizedR:4} as DeclaredQuote]),/schema/);
  assert.throws(()=>run(scope,orders,[quote],[{...fill,realizedR:4} as DeclaredFill]),/schema/);
});
test('rejects malformed decimal, unsafe timestamp and invalid contract sizes',()=>{
  for(const bad of ['1e4','-1','1.1234567','01','NaN','+1','1000000000']){
    assert.throws(()=>run(scope,orders,[{...quote,bid:bad}]),/decimal/);
    assert.throws(()=>run(scope,orders,[quote],[{...fill,commissionCurrency:bad}]),/decimal/);
  }
  assert.throws(()=>run(scope,[{...orders[0],requestedContracts:1.5}]),/order/);
  assert.throws(()=>run(scope,orders,[quote],[{...fill,filledContracts:0}]),/fill/);
  assert.throws(()=>run({...scope,maxQuoteAgeMs:300001}),/freshness/);
  assert.throws(()=>run(scope,orders,[{...quote,observedAt:Number.MAX_SAFE_INTEGER+1}]),/quote/);
});
test('empty evidence never reports a complete free trade',()=>{
  const a=run(scope,[],[],[]);assert.equal(a.status,'NO_DECLARED_FILLS');
  assert.equal(a.completeFrictionCurrency,null);assert.equal(a.requestedContracts,0);
});
test('source objects are not mutated; no broker network dependencies',()=>{
  const input=structuredClone({scope,orders,quotes:[quote],fills:[fill]});
  run(input.scope,input.orders,input.quotes,input.fills);
  assert.deepEqual(input,{scope,orders,quotes:[quote],fills:[fill]});
});
