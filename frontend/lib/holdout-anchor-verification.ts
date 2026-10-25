/**
 * Offline comparison of independently retained holdout audit-head receipts.
 * IMPORTANT: matching an untrusted receipt does not authenticate the receipt,
 * its timestamp, the archive source, or the completeness of recorded accesses.
 * First call verifyHoldoutAudit() to validate the underlying audit chain.
 * No network, persistence, orders, or market-data access occurs here.
 */
export type HoldoutAnchorReceipt = {
  schema: 'holdout-anchor-receipt-v1';
  commitmentDigest: string;
  sequence: number;
  headDigest: string;
  anchoredAt: number;
  authority: string;
  reference: string;
};

export type HoldoutAnchorReview = {
  status: 'NO_ANCHOR' | 'PARTIALLY_ANCHORED_UNVERIFIED' | 'HEAD_MATCH_UNVERIFIED';
  lastAnchoredSequence: number;
  unanchoredEvents: number;
  findings: string[];
};

const SHA = /^[0-9a-f]{64}$/;
const keys = ['schema', 'commitmentDigest', 'sequence', 'headDigest', 'anchoredAt', 'authority', 'reference'];
const safeInt = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const nonempty = (value: unknown): value is string =>
  typeof value === 'string' && value.length >= 1 && value.length <= 200 &&
  /^[a-zA-Z0-9._:/@-]+$/.test(value);

/**
 * Compare a *previously integrity-verified* audit against externally retained
 * receipts. This function cannot determine whether a receipt is genuine.
 * The independent authority must authenticate each receipt outside this code.
 */
export function verifyHoldoutAnchorReceipts(
  commitment: { digest: string; frozenAt: number },
  entries: ReadonlyArray<{ sequence: number; digest: string; occurredAt: number }>,
  receipts: ReadonlyArray<HoldoutAnchorReceipt>
): HoldoutAnchorReview {
  if (!commitment || !SHA.test(commitment.digest) || !safeInt(commitment.frozenAt))
    throw Error('Invalid holdout commitment identity');
  if (!Array.isArray(entries) || entries.length > 100000 ||
      !Array.isArray(receipts) || receipts.length > 10000)
    throw Error('Invalid or excessive holdout audit/anchor records');
  let lastEventAt = commitment.frozenAt;
  for (let i = 0; i < entries.length; i++) {
    const e = entries[i];
    if (!e || e.sequence !== i + 1 || !SHA.test(e.digest) ||
        !safeInt(e.occurredAt) || e.occurredAt < lastEventAt)
      throw Error('Invalid audit entry chronology or identity; verify underlying audit first');
    lastEventAt = e.occurredAt;
  }
  if (!receipts.length) return {
    status: 'NO_ANCHOR', lastAnchoredSequence: 0, unanchoredEvents: entries.length,
    findings: ['No independent anchor receipt supplied; the audit can be rewritten or truncated.']
  };
  let lastSequence = -1;
  let lastAnchorTime = commitment.frozenAt;
  const references = new Set<string>();
  for (const receipt of receipts) {
    if (!receipt || typeof receipt !== 'object' || Array.isArray(receipt) ||
        Object.keys(receipt).length !== keys.length ||
        Object.keys(receipt).some(key => !keys.includes(key)))
      throw Error('Invalid anchor receipt schema; unexpected fields are forbidden');
    if (receipt.schema !== 'holdout-anchor-receipt-v1' ||
        !SHA.test(receipt.commitmentDigest) || !SHA.test(receipt.headDigest) ||
        receipt.commitmentDigest !== commitment.digest ||
        !safeInt(receipt.sequence) || receipt.sequence <= lastSequence ||
        receipt.sequence > entries.length || !safeInt(receipt.anchoredAt) ||
        receipt.anchoredAt < lastAnchorTime ||
        !nonempty(receipt.authority) || !nonempty(receipt.reference))
      throw Error('Invalid, reordered, or mismatched external anchor receipt');
    const expectedHead = receipt.sequence === 0 ? commitment.digest : entries[receipt.sequence - 1].digest;
    const eventTime = receipt.sequence === 0 ? commitment.frozenAt : entries[receipt.sequence - 1].occurredAt;
    if (receipt.headDigest !== expectedHead)
      throw Error('Anchored audit head mismatch: history may have been truncated or rewritten');
    if (receipt.anchoredAt < eventTime)
      throw Error('Anchor timestamp predates the event it claims to include');
    const referenceKey = receipt.authority + '\u0000' + receipt.reference;
    if (references.has(referenceKey)) throw Error('Duplicate external anchor reference');
    references.add(referenceKey);
    lastSequence = receipt.sequence;
    lastAnchorTime = receipt.anchoredAt;
  }
  const unanchoredEvents = entries.length - lastSequence;
  return {
    status: unanchoredEvents ? 'PARTIALLY_ANCHORED_UNVERIFIED' : 'HEAD_MATCH_UNVERIFIED',
    lastAnchoredSequence: lastSequence,
    unanchoredEvents,
    findings: [
      unanchoredEvents ? unanchoredEvents + ' trailing event(s) have no supplied external anchor.' :
        'The complete supplied chain matches the supplied external anchor head.',
      'Receipt authenticity, independent timestamping, storage immutability, omitted access events and data licensing are NOT verified.'
    ]
  };
}
