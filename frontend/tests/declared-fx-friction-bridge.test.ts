import {test} from 'node:test';
import assert from 'node:assert/strict';
import {reviewDeclaredFxFriction,type FxFrictionPolicy,type DeclaredFillFx}
  from '../lib/declared-fx-friction-bridge.ts';
import type {QuoteExecutionScope,DeclaredOrder,DeclaredQuote,DeclaredFill}
  from '../lib/declared-quote-execution-audit.ts';
const scope:QuoteExecutionScope={provider:'DemoBroker',venue:'paper',instrument:'XAUUSD-CFD',
  accountAlias:'acct1',quoteStreamId:'quotes1',quoteCurrency:'USD',quoteBatchSha256:'a'.repeat(64),
  asOf:2000,maxQuoteAgeMs:200,cashPerPricePointPerContract:'2'};
const orders:DeclaredOrder[]=[{orderId:'o1',side:'BUY',requestedContracts:3,submittedAt:1000}];
const quotes:DeclaredQuote[]=[{quoteId:'q1',provider:'DemoBroker',venue:'paper',instrument:'XAUUSD-CFD',
  quoteStreamId:'quotes1',quoteBatchSha256:'a'.repeat(64),observedAt:1010,bid:'99.90',ask:'100.10'}];
const fills:DeclaredFill[]=[{fillId:'f1',orderId:'o1',provider:'DemoBroker',venue:'paper',
  instrument:'XAUUSD-CFD',accountAlias:'acct1',quoteId:'q1',filledAt:1050,
  filledContracts:3,price:'100.15',commissionCurrency:'0.20'}];
const policy:FxFrictionPolicy={accountCurrency:'GBP',fxSourceId:'fx-feed-1',
  fxBatchSha256:'b'.repeat(64),maxFxAgeMs:100};
const fx:DeclaredFillFx[]=[{fillId:'f1',fxQuoteId:'gbp1',sourceId:'fx-feed-1',
  batchSha256:'b'.repeat(64),fromCurrency:'USD',toCurrency:'GBP',rate:'0.800000',
  observedAt:1020,recordedAt:1030}];
const run=(p:FxFrictionPolicy=policy,x:readonly DeclaredFillFx[]=fx,
  o:readonly DeclaredOrder[]=orders,q:readonly DeclaredQuote[]=quotes,
  f:readonly DeclaredFill[]=fills,s:QuoteExecutionScope=scope)=>
  reviewDeclaredFxFriction(s,o,q,f,p,x);
test('point-in-time USD to GBP costs preserve exact spread, slippage and commission',()=>{
  const a=run();assert.equal(a.status,'COMPLETE_DECLARED');
  assert.equal(a.completeFrictionAccountCurrency,'0.8800000000000000000');
  assert.equal(a.rows[0].halfSpreadAccountCurrency,'0.4800000000000000000');
  assert.equal(a.rows[0].slippageAccountCurrency,'0.2400000000000000000');
  assert.equal(a.rows[0].commissionAccountCurrency,'0.1600000000000000000');
  assert.equal(a.rows[0].rate,'0.8000000000000000000');
  assert.equal(a.mayExecuteOrder,false);
});
test('native quote/account currency forbids FX evidence and uses exact parity',()=>{
  const p={accountCurrency:'USD',fxSourceId:null,fxBatchSha256:null,maxFxAgeMs:null};
  const a=run(p,[]);assert.equal(a.completeFrictionAccountCurrency,'1.1000000000000000000');
  assert.equal(a.rows[0].fxQuoteId,null);
  assert.throws(()=>run(p,fx),/population/);
  assert.throws(()=>run({...p,fxSourceId:'fx-feed-1'},[]),/Native-currency/);
});
test('partial fills preserve observed cost but withhold complete cost',()=>{
  const a=run(policy,fx,orders,quotes,[{...fills[0],filledContracts:1}]);
  assert.equal(a.status,'PARTIAL_DECLARED');
  assert.equal(a.observedFrictionAccountCurrency,'0.4000000000000000000');
  assert.equal(a.completeFrictionAccountCurrency,null);
});
test('no fills and no FX cannot be called a free order',()=>{
  const a=run(policy,[],orders,[],[]);
  assert.equal(a.status,'NO_DECLARED_FILLS');
  assert.equal(a.observedFrictionAccountCurrency,null);
  assert.equal(a.completeFrictionAccountCurrency,null);
});
test('favorable SELL slippage remains signed negative after conversion',()=>{
  const a=run(policy,fx,[{...orders[0],side:'SELL'}],quotes,[{...fills[0],price:'99.95'}]);
  assert.equal(a.rows[0].slippageAccountCurrency,'-0.2400000000000000000');
  assert.equal(a.completeFrictionAccountCurrency,'0.4000000000000000000');
});
test('micro FX rates preserve sub-cent precision without floats',()=>{
  const a=run(policy,[{...fx[0],rate:'0.000001'}]);
  assert.equal(a.completeFrictionAccountCurrency,'0.0000011000000000000');
});
test('stale, future or late-recorded FX fails closed',()=>{
  assert.throws(()=>run(policy,[{...fx[0],observedAt:900,recordedAt:950}]),/FX observation/);
  assert.throws(()=>run(policy,[{...fx[0],observedAt:1051,recordedAt:1051}]),/FX observation/);
  assert.throws(()=>run(policy,[{...fx[0],recordedAt:1051}]),/FX observation/);
  assert.throws(()=>run(policy,[{...fx[0],recordedAt:1019}]),/FX observation/);
});
test('source, batch, currencies and fill identities cannot be mixed',()=>{
  for(const patch of [{sourceId:'other'},{batchSha256:'c'.repeat(64)},
    {fromCurrency:'EUR'},{toCurrency:'USD'},{fillId:'f-other'}])
    assert.throws(()=>run(policy,[{...fx[0],...patch}]),/FX observation/);
  assert.throws(()=>run(policy,[]),/Missing FX observations/);
  assert.throws(()=>run(policy,[...fx,...fx]),/FX observation/);
});
test('FX policy and rate must be bounded, strict and nonzero',()=>{
  assert.throws(()=>run({...policy,maxFxAgeMs:300001}),/policy/);
  assert.throws(()=>run({...policy,fxBatchSha256:'bad'}),/policy/);
  assert.throws(()=>run({...policy,accountCurrency:'US'}),/currency/);
  for(const rate of ['0','-1','1e3','01','1.1234567','NaN'])
    assert.throws(()=>run(policy,[{...fx[0],rate}]),/FX rate/);
  assert.throws(()=>run(policy,[{...fx[0],extra:1} as DeclaredFillFx]),/schema/);
});
test('reused FX quote ID cannot silently change price or observation time',()=>{
  const f2={...fills[0],fillId:'f2',filledContracts:1,quoteId:'q2',filledAt:1060};
  const f1={...fills[0],filledContracts:2};
  const q2={...quotes[0],quoteId:'q2',observedAt:1020};
  const fx2={...fx[0],fillId:'f2'};
  const a=run(policy,[fx[0],fx2],orders,[quotes[0],q2],[f1,f2]);
  assert.equal(a.rows.length,2);
  assert.throws(()=>run(policy,[fx[0],{...fx2,rate:'0.81'}],orders,
    [quotes[0],q2],[f1,f2]),/Conflicting FX quote/);
  assert.throws(()=>run(policy,[fx[0],{...fx2,observedAt:1021}],orders,
    [quotes[0],q2],[f1,f2]),/Conflicting FX quote/);
});
test('existing quote-side stale, overfill and multiplier validation is inherited',()=>{
  assert.throws(()=>run(policy,fx,orders,quotes,[{...fills[0],filledContracts:4}]),/exceeds/);
  assert.throws(()=>run(policy,fx,orders,quotes,[{...fills[0],filledAt:1300}]),/stale/);
  assert.throws(()=>run(policy,fx,orders,quotes,fills,{...scope,cashPerPricePointPerContract:'0'}),/multiplier/);
});
test('inputs are not mutated and no execution is enabled',()=>{
  const original=structuredClone({scope,orders,quotes,fills,policy,fx});
  run();assert.deepEqual({scope,orders,quotes,fills,policy,fx},original);
});
