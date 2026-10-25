import {test} from 'node:test';
import assert from 'node:assert/strict';
import {assertDeclaredCfdTemporalConsistency} from '../lib/declared-cfd-temporal-consistency.ts';
const quote={asOf:2000};
const financing={openedAt:1000,closedAt:1500,asOf:2000};
const orders=[{submittedAt:990},{submittedAt:1400}];
const fills=[{filledAt:1000},{filledAt:1500}];
const check=(q=quote,o:readonly {submittedAt:number}[]=orders,
  f:readonly {filledAt:number}[]=fills,fin=financing)=>
  assertDeclaredCfdTemporalConsistency(q,o,f,fin);
test('permits pre-open submission and inclusive opening/closing fills',()=>assert.doesNotThrow(()=>check()));
test('rejects a quote snapshot taken before financing close',()=>
  assert.throws(()=>check({...quote,asOf:1499}),/predates/));
test('rejects fills before the financed position opened',()=>
  assert.throws(()=>check(quote,orders,[{filledAt:999}]),/outside/));
test('rejects fills after the financed position closed',()=>
  assert.throws(()=>check(quote,orders,[{filledAt:1501}]),/outside/));
test('rejects unrelated orders submitted after position close',()=>
  assert.throws(()=>check(quote,[{submittedAt:1501}],fills),/after/));
test('rejects a single out-of-window fill in a mixed batch',()=>
  assert.throws(()=>check(quote,orders,[...fills,{filledAt:1999}]),/outside/));
test('does not mutate caller records',()=>{
  const before=structuredClone({quote,financing,orders,fills});
  check();
  assert.deepEqual({quote,financing,orders,fills},before);
});
