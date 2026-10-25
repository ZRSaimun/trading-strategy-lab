import {test} from 'node:test';
import assert from 'node:assert/strict';
import {verifyHoldoutAnchorReceipts, type HoldoutAnchorReceipt} from '../lib/holdout-anchor-verification.ts';

const commitment = {digest: 'a'.repeat(64), frozenAt: 100};
const entries = [
  {sequence: 1, digest: 'b'.repeat(64), occurredAt: 120},
  {sequence: 2, digest: 'c'.repeat(64), occurredAt: 140},
  {sequence: 3, digest: 'd'.repeat(64), occurredAt: 160}
];
const receipt = (sequence: number, anchoredAt = 200): HoldoutAnchorReceipt => ({
  schema: 'holdout-anchor-receipt-v1', commitmentDigest: commitment.digest,
  sequence, headDigest: sequence ? entries[sequence - 1].digest : commitment.digest,
  anchoredAt, authority: 'independent-log', reference: 'receipt-' + sequence
});

test('no receipt never claims an anchored holdout', () => {
  const result = verifyHoldoutAnchorReceipts(commitment, entries, []);
  assert.equal(result.status, 'NO_ANCHOR');
  assert.equal(result.unanchoredEvents, 3);
});
test('verified head comparison still explicitly disclaims receipt authenticity', () => {
  const result = verifyHoldoutAnchorReceipts(commitment, entries, [receipt(0, 100), receipt(2), receipt(3, 201)]);
  assert.equal(result.status, 'HEAD_MATCH_UNVERIFIED');
  assert.equal(result.lastAnchoredSequence, 3);
  assert.match(result.findings.join(' '), /NOT verified/);
});
test('a legitimate but incomplete anchored prefix leaves trailing events unanchored', () => {
  const result = verifyHoldoutAnchorReceipts(commitment, entries, [receipt(2)]);
  assert.equal(result.status, 'PARTIALLY_ANCHORED_UNVERIFIED');
  assert.equal(result.unanchoredEvents, 1);
});
test('rejects audit truncation relative to a previously pinned receipt', () => {
  assert.throws(() => verifyHoldoutAnchorReceipts(commitment, entries.slice(0, 2), [receipt(3)]), /mismatched external anchor/);
});
test('rejects rewriting an anchored historical head', () => {
  const changed = entries.map(e => ({...e}));
  changed[1].digest = 'e'.repeat(64);
  assert.throws(() => verifyHoldoutAnchorReceipts(commitment, changed, [receipt(2)]), /head mismatch/);
});
test('rejects foreign commitment and extra outcome fields', () => {
  assert.throws(() => verifyHoldoutAnchorReceipts(commitment, entries, [{...receipt(3), commitmentDigest: 'f'.repeat(64)}]), /mismatched external anchor/);
  assert.throws(() => verifyHoldoutAnchorReceipts(commitment, entries, [{...receipt(3), realizedPnl: 999} as unknown as HoldoutAnchorReceipt]), /unexpected fields/);
});
test('rejects reordered and repeated anchor sequences', () => {
  assert.throws(() => verifyHoldoutAnchorReceipts(commitment, entries, [receipt(2), receipt(1)]), /reordered/);
  assert.throws(() => verifyHoldoutAnchorReceipts(commitment, entries, [receipt(2), {...receipt(2), reference:'different'}]), /reordered/);
});
test('rejects fake anchor chronology and event chronology', () => {
  assert.throws(() => verifyHoldoutAnchorReceipts(commitment, entries, [receipt(3, 150)]), /predates/);
  assert.throws(() => verifyHoldoutAnchorReceipts(commitment, entries, [receipt(2, 200), receipt(3, 199)]), /reordered/);
  assert.throws(() => verifyHoldoutAnchorReceipts(commitment, [{...entries[0], occurredAt: 99}], []), /audit entry chronology/);
});
test('rejects duplicate references and invalid authority identity', () => {
  assert.throws(() => verifyHoldoutAnchorReceipts(commitment, entries, [receipt(1), {...receipt(2), reference:'receipt-1'}]), /Duplicate external/);
  assert.throws(() => verifyHoldoutAnchorReceipts(commitment, entries, [{...receipt(3), authority:'not a verified authority'}]), /mismatched external anchor/);
});
test('commitment-only anchor uses commitment digest as head', () => {
  const result = verifyHoldoutAnchorReceipts(commitment, [], [receipt(0, 100)]);
  assert.equal(result.status, 'HEAD_MATCH_UNVERIFIED');
  assert.equal(result.unanchoredEvents, 0);
});
