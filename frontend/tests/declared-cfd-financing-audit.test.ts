import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditDeclaredCfdFinancing,type FinancingScope,type FinancingReceipt} from '../lib/declared-cfd-financing-audit.ts';
const scope:FinancingScope={provider:'SyntheticBroker',venue:'demo',instrument:'XAUUSD-CFD',
 accountAlias:'paper-1',positionId:'pos-1',settlementCurrency:'GBP',statementSha256:'a'.repeat(64),
 openedAt:100,closedAt:500,asOf:700,requiredRolloverTimes:[200,300,400]};
const receipt=(id:string,t:number,amountCurrency:string,overrides:Partial<FinancingReceipt>={}):FinancingReceipt=>({
 receiptId:id,provider:scope.provider,venue:scope.venue,instrument:scope.instrument,
 accountAlias:scope.accountAlias,positionId:scope.positionId,
 settlementCurrency:scope.settlementCurrency,statementSha256:scope.statementSha256,
 rolloverAt:t,recordedAt:t+5,amountCurrency,...overrides});
const complete=[receipt('a',200,'1.20'),receipt('b',300,'-0.05'),receipt('c',400,'0.30')];
const run=(s=scope,r:readonly FinancingReceipt[]=complete)=>auditDeclaredCfdFinancing(s,r);
test('exact signed decimal receipts sum without float drift',()=>{
 const a=run();assert.equal(a.status,'MATCHED_DECLARED');assert.equal(a.totalChargeCurrency,'1.45');
 assert.equal(a.matchedEvents,3);assert.equal(a.coverage,'SELF_DECLARED_SCHEDULE_AND_RECEIPTS_ONLY');
 assert.ok(a.warnings.some(w=>w.includes('not authenticated')));
});
test('missing financing event withholds aggregate instead of inventing zero',()=>{
 const a=run(scope,complete.slice(0,2));assert.equal(a.status,'MISSING_DECLARED_EVENTS');
 assert.deepEqual(a.missingRolloverTimes,[400]);assert.equal(a.totalChargeCurrency,null);
});
test('empty declared schedule cannot assert zero overnight cost',()=>{
 const a=run({...scope,requiredRolloverTimes:[]},[]);
 assert.equal(a.status,'NO_DECLARED_EVENTS');assert.equal(a.totalChargeCurrency,null);
});
test('rejects extra rollover not declared and duplicate receipts',()=>{
 assert.throws(()=>run(scope,[...complete,receipt('extra',450,'0.20')]),/unmatched/);
 assert.throws(()=>run(scope,[...complete,receipt('other',400,'0.20')]),/Duplicate/);
 assert.throws(()=>run(scope,[...complete,receipt('a',200,'0.20')]),/Duplicate/);
});
test('rejects cross-account, source, position, currency and statement substitutions',()=>{
 for(const change of [{provider:'Other'},{venue:'live'},{instrument:'WTI'},{accountAlias:'other'},
  {positionId:'other'},{settlementCurrency:'USD'},{statementSha256:'b'.repeat(64)}]){
  assert.throws(()=>run(scope,[{...complete[0],...change},...complete.slice(1)]),/cross-source/);
 }
});
test('rejects receipts after audit as-of and before rollover',()=>{
 assert.throws(()=>run(scope,[receipt('a',200,'1.00',{recordedAt:701}),...complete.slice(1)]),/future/);
 assert.throws(()=>run(scope,[receipt('a',200,'1.00',{recordedAt:199}),...complete.slice(1)]),/future/);
});
test('rejects noncanonical, exponential, negative zero and excessive precision',()=>{
 for(const bad of ['1e5','0.001','-0','-0.00','+1','01','NaN','Infinity','-','1000000000']){
  assert.throws(()=>run(scope,[receipt('a',200,bad),...complete.slice(1)]),/decimal/);
 }
});
test('rejects unsorted, repeated, out-of-position or unsafe rollover times',()=>{
 for(const requiredRolloverTimes of [[300,200],[200,200],[99],[500],[NaN],[2**54]]){
  assert.throws(()=>run({...scope,requiredRolloverTimes},[]),/rollover/);
 }
});
test('rejects unknown outcome fields and malformed receipt identity',()=>{
 assert.throws(()=>run({...scope,netProfit:100} as FinancingScope),/schema/);
 assert.throws(()=>run(scope,[{...complete[0],realizedR:10} as FinancingReceipt,...complete.slice(1)]),/schema/);
 assert.throws(()=>run(scope,[receipt('a/b',200,'1.00'),...complete.slice(1)]),/receipt/);
});
test('zero charge requires explicit zero receipt; negative net charge allowed',()=>{
 const a=run(scope,[receipt('a',200,'0'),receipt('b',300,'-2.00'),receipt('c',400,'0.30')]);
 assert.equal(a.totalChargeCurrency,'-1.70');
});
test('does not mutate source or receipts and order of receipts is irrelevant',()=>{
 const s=structuredClone(scope),r=structuredClone(complete),before=structuredClone({s,r});
 assert.deepEqual(run(s,r),run(s,[...r].reverse()));
 assert.deepEqual({s,r},before);
});
