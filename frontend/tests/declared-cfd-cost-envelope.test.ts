import {test} from 'node:test';
import assert from 'node:assert/strict';
import {reviewDeclaredCfdCostEnvelope,type CostStress} from '../lib/declared-cfd-cost-envelope.ts';
import type {QuoteExecutionScope,DeclaredOrder,DeclaredQuote,DeclaredFill} from '../lib/declared-quote-execution-audit.ts';
import type {FinancingScope,FinancingReceipt} from '../lib/declared-cfd-financing-audit.ts';
const qScope:QuoteExecutionScope={provider:'Demo',venue:'paper',instrument:'XAUUSD-CFD',
  accountAlias:'test',quoteStreamId:'feed',quoteCurrency:'USD',quoteBatchSha256:'a'.repeat(64),
  asOf:2000,maxQuoteAgeMs:200,cashPerPricePointPerContract:'2'};
const fScope:FinancingScope={provider:'Demo',venue:'paper',instrument:'XAUUSD-CFD',
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
const stress:CostStress={id:'widened',extraHalfSpreadCurrency:'0.50',
  extraSlippageCurrency:'0.25',extraCommissionCurrency:'0.10',extraFinancingCurrency:'0.15'};
const run=(q=qScope,o:readonly DeclaredOrder[]=orders,qs:readonly DeclaredQuote[]=quotes,
  fs:readonly DeclaredFill[]=fills,f=fScope,rs:readonly FinancingReceipt[]=receipts,
  budget='2.00',grid:readonly CostStress[]=[stress])=>
  reviewDeclaredCfdCostEnvelope(q,o,qs,fs,f,rs,budget,grid);
test('combines one-sided quote friction with financing and incremental stresses',()=>{
  const result=run();
  assert.equal(result.baseCostCurrency,'1.3000000000000');
  assert.equal(result.declaredCostBudgetCurrency,'2.0000000000000');
  assert.deepEqual(result.scenarios,[{id:'widened',stressedCostCurrency:'2.3000000000000',
    status:'EXCEEDS_DECLARED_COST_BUDGET'}]);
});
test('equal cost budget is within tolerance, not proof of trading safety',()=>{
  const result=run(qScope,orders,quotes,fills,fScope,receipts,'2.30');
  assert.equal(result.scenarios[0].status,'WITHIN_DECLARED_COST_BUDGET');
  assert.match(result.warnings.join(' '),/not authenticated/);
});
test('missing rollover or partial fill withholds ALL totals',()=>{
  for(const result of [run(qScope,orders,quotes,fills,fScope,[]),
    run(qScope,orders,quotes,[{...fills[0],filledContracts:1}])]){
    assert.equal(result.baseCostCurrency,null);
    assert.equal(result.scenarios[0].stressedCostCurrency,null);
    assert.equal(result.scenarios[0].status,'INCOMPLETE_DECLARED_EVIDENCE');
  }
});
test('empty financing schedule cannot be interpreted as free financing',()=>{
  assert.equal(run(qScope,orders,quotes,fills,{...fScope,requiredRolloverTimes:[]},[]).baseCostCurrency,null);
});
test('rejects provider, venue, instrument, account and currency mixing',()=>{
  for(const f of [{...fScope,provider:'Other'},{...fScope,venue:'live'},
    {...fScope,instrument:'WTI'},{...fScope,accountAlias:'other'},
    {...fScope,settlementCurrency:'GBP'}]){
    const rs=receipts.map(r=>({...r,provider:f.provider,venue:f.venue,
      instrument:f.instrument,accountAlias:f.accountAlias,settlementCurrency:f.settlementCurrency}));
    assert.throws(()=>run(qScope,orders,quotes,fills,f,rs),/Cross-source/);
  }
});
test('rejects duplicate scenarios, malformed decimal and hidden outcome fields',()=>{
  assert.throws(()=>run(qScope,orders,quotes,fills,fScope,receipts,'2',[stress,stress]),/duplicate/);
  assert.throws(()=>run(qScope,orders,quotes,fills,fScope,receipts,'-1'),/budget/);
  assert.throws(()=>run(qScope,orders,quotes,fills,fScope,receipts,'1e6'),/budget/);
  assert.throws(()=>run(qScope,orders,quotes,fills,fScope,receipts,'2',
    [{...stress,extraSlippageCurrency:'-0.1'}]),/slippage/);
  assert.throws(()=>run(qScope,orders,quotes,fills,fScope,receipts,'2',
    [{...stress,profit:'100'} as CostStress]),/schema/);
});
test('rejects empty or excessive stress grids',()=>{
  assert.throws(()=>run(qScope,orders,quotes,fills,fScope,receipts,'2',[]),/bounded/);
  assert.throws(()=>run(qScope,orders,quotes,fills,fScope,receipts,'2',
    Array.from({length:13},(_,i)=>({...stress,id:'s'+i}))),/bounded/);
});
test('financing credits and favorable slippage remain signed, not clipped',()=>{
  const credit=receipts.map(r=>({...r,amountCurrency:'-2.00'}));
  const improved=fills.map(f=>({...f,price:'99.80'}));
  const result=run(qScope,orders,quotes,improved,fScope,credit,'0');
  assert.equal(result.baseCostCurrency,'-3.0000000000000');
  assert.equal(result.scenarios[0].stressedCostCurrency,'-2.0000000000000');
});
test('source objects remain unmodified and no network is required',()=>{
  const before=structuredClone({qScope,orders,quotes,fills,fScope,receipts,stress});
  run();
  assert.deepEqual({qScope,orders,quotes,fills,fScope,receipts,stress},before);
});
