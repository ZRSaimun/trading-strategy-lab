import {test} from 'node:test';
import assert from 'node:assert/strict';
import {reviewPositionLinkedDeclaredCfdCosts,type DeclaredPositionLinkage}
  from '../lib/position-linked-cfd-cost-review.ts';
import type {QuoteExecutionScope,DeclaredOrder,DeclaredQuote,DeclaredFill}
  from '../lib/declared-quote-execution-audit.ts';
import type {FinancingScope,FinancingReceipt}
  from '../lib/declared-cfd-financing-audit.ts';
import type {CostStress} from '../lib/declared-cfd-cost-envelope.ts';

const q:QuoteExecutionScope={provider:'Demo',venue:'paper',instrument:'XAUUSD-CFD',
  accountAlias:'test',quoteStreamId:'feed',quoteCurrency:'USD',quoteBatchSha256:'a'.repeat(64),
  asOf:2000,maxQuoteAgeMs:200,cashPerPricePointPerContract:'2'};
const f:FinancingScope={provider:'Demo',venue:'paper',instrument:'XAUUSD-CFD',
  accountAlias:'test',positionId:'p1',settlementCurrency:'USD',statementSha256:'b'.repeat(64),
  openedAt:1000,closedAt:1500,asOf:2000,requiredRolloverTimes:[1100]};
const orders:DeclaredOrder[]=[{orderId:'o1',side:'BUY',requestedContracts:3,submittedAt:1000}];
const quotes:DeclaredQuote[]=[{quoteId:'q1',provider:'Demo',venue:'paper',instrument:'XAUUSD-CFD',
  quoteStreamId:'feed',quoteBatchSha256:'a'.repeat(64),observedAt:1010,bid:'99.90',ask:'100.10'}];
const fills:DeclaredFill[]=[{fillId:'fill',orderId:'o1',provider:'Demo',venue:'paper',
  instrument:'XAUUSD-CFD',accountAlias:'test',quoteId:'q1',filledAt:1050,
  filledContracts:3,price:'100.15',commissionCurrency:'0.20'}];
const receipts:FinancingReceipt[]=[{receiptId:'r1',provider:'Demo',venue:'paper',
  instrument:'XAUUSD-CFD',accountAlias:'test',positionId:'p1',settlementCurrency:'USD',
  statementSha256:'b'.repeat(64),rolloverAt:1100,recordedAt:1200,amountCurrency:'0.20'}];
const stress:CostStress[]=[{id:'stress',extraHalfSpreadCurrency:'0.50',
  extraSlippageCurrency:'0.25',extraCommissionCurrency:'0.10',extraFinancingCurrency:'0.15'}];
const links:DeclaredPositionLinkage={provider:'Demo',venue:'paper',instrument:'XAUUSD-CFD',
  accountAlias:'test',positionId:'p1',quoteBatchSha256:'a'.repeat(64),
  financingStatementSha256:'b'.repeat(64),executionStatementSha256:'c'.repeat(64),
  evidenceSource:'PAPER_LEDGER',asOf:1900,
  orderLinks:[{orderId:'o1',positionId:'p1',recordedAt:1020}],
  fillLinks:[{fillId:'fill',orderId:'o1',positionId:'p1',recordedAt:1060}]};
const run=(l:DeclaredPositionLinkage=links,o:readonly DeclaredOrder[]=orders,
  fs:readonly DeclaredFill[]=fills,qq=q,ff=f,rr:readonly FinancingReceipt[]=receipts)=>
  reviewPositionLinkedDeclaredCfdCosts(qq,o,quotes,fs,ff,rr,l,'2.00',stress);

test('complete position mapping still runs exact spread, slippage, commission and financing audits',()=>{
  const result=run();
  assert.equal(result.linkageStatus,'COMPLETE_SELF_DECLARED_POSITION_LINKAGE');
  assert.equal(result.positionId,'p1');
  assert.equal(result.cost.baseCostCurrency,'1.3000000000000');
  assert.equal(result.cost.scenarios[0].stressedCostCurrency,'2.3000000000000');
  assert.match(result.warnings.join(' '),/not verified source bytes/);
});
test('broker export label cannot be mistaken for authenticated evidence',()=>{
  const result=run({...links,evidenceSource:'BROKER_EXPORT'});
  assert.equal(result.evidenceSource,'BROKER_EXPORT');
  assert.match(result.warnings.join(' '),/not verified source bytes/);
});
test('rejects wrong source, account and position identities',()=>{
  for(const l of [{...links,provider:'Other'},{...links,venue:'live'},
    {...links,instrument:'WTI'},{...links,accountAlias:'other'},
    {...links,positionId:'p2'}])
    assert.throws(()=>run(l),/mismatches/);
});
test('rejects mismatched quote and financing statement digests',()=>{
  assert.throws(()=>run({...links,quoteBatchSha256:'d'.repeat(64)}),/mismatches/);
  assert.throws(()=>run({...links,financingStatementSha256:'d'.repeat(64)}),/mismatches/);
  assert.throws(()=>run({...links,executionStatementSha256:'NOT-A-SHA'}),/provenance/);
});
test('missing or extra order link fails closed',()=>{
  assert.throws(()=>run({...links,orderLinks:[]}),/coverage/);
  assert.throws(()=>run({...links,orderLinks:[...links.orderLinks,...links.orderLinks]}),/coverage/);
});
test('missing or extra fill link fails closed',()=>{
  assert.throws(()=>run({...links,fillLinks:[]}),/coverage/);
  assert.throws(()=>run({...links,fillLinks:[...links.fillLinks,...links.fillLinks]}),/coverage/);
});
test('same-length foreign order and fill links fail closed',()=>{
  assert.throws(()=>run({...links,orderLinks:[{orderId:'foreign',positionId:'p1',recordedAt:1020}]}),/order-position/);
  assert.throws(()=>run({...links,fillLinks:[{fillId:'foreign',orderId:'o1',positionId:'p1',recordedAt:1060}]}),/fill-position/);
});
test('link position and fill-order association cannot silently change',()=>{
  assert.throws(()=>run({...links,orderLinks:[{...links.orderLinks[0],positionId:'p2'}]}),/order-position/);
  assert.throws(()=>run({...links,fillLinks:[{...links.fillLinks[0],positionId:'p2'}]}),/fill-position/);
  assert.throws(()=>run({...links,fillLinks:[{...links.fillLinks[0],orderId:'other'}]}),/fill-position/);
});
test('links cannot be recorded before corresponding order or fill',()=>{
  assert.throws(()=>run({...links,orderLinks:[{...links.orderLinks[0],recordedAt:999}]}),/order-position/);
  assert.throws(()=>run({...links,fillLinks:[{...links.fillLinks[0],recordedAt:1049}]}),/fill-position/);
});
test('link evidence cannot be future-dated or outside both audit snapshots',()=>{
  assert.throws(()=>run({...links,asOf:2001}),/clock/);
  assert.throws(()=>run({...links,asOf:1050}),/fill-position/);
  assert.throws(()=>run({...links,asOf:1900.5}),/clock/);
});
test('rejects hidden fields and unsupported evidence source',()=>{
  assert.throws(()=>run({...links,realizedProfit:'100'} as DeclaredPositionLinkage),/schema/);
  assert.throws(()=>run({...links,evidenceSource:'AUTHENTICATED'} as unknown as DeclaredPositionLinkage),/provenance/);
  assert.throws(()=>run({...links,fillLinks:[{...links.fillLinks[0],pnl:'5'}]} as unknown as DeclaredPositionLinkage),/schema/);
});
test('partial fill and missing financing still withhold all totals',()=>{
  const partial=run(links,orders,[{...fills[0],filledContracts:1}]);
  assert.equal(partial.cost.baseCostCurrency,null);
  assert.equal(partial.cost.scenarios[0].stressedCostCurrency,null);
  const missing=run(links,orders,fills,q,f,[]);
  assert.equal(missing.cost.baseCostCurrency,null);
});
test('declared linkage never mutates input records',()=>{
  const before=structuredClone({links,orders,quotes,fills,receipts});
  run();
  assert.deepEqual({links,orders,quotes,fills,receipts},before);
});
test('duplicated order IDs and duplicated fill IDs fail before cost aggregation',()=>{
  const o=[orders[0],orders[0]];
  const l={...links,orderLinks:[links.orderLinks[0],links.orderLinks[0]]};
  assert.throws(()=>run(l,o),/Duplicate declared order/);
  const fs=[fills[0],fills[0]];
  const ll={...links,fillLinks:[links.fillLinks[0],links.fillLinks[0]]};
  assert.throws(()=>run(ll,orders,fs),/Duplicate declared order or fill/);
});
