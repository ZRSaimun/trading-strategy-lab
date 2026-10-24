/** Offline dual-head multi-authority audit attestation review.
 * Each signature is checked against a caller-pinned key and the complete audit.
 * Authorities, timestamps and retention are caller claims, NOT independently proven.
 * No network, market data, brokerage or orders.
 */
import {verifySignedHoldoutAnchors, type SignedHoldoutAnchor, type TrustedAnchorKey} from './holdout-signed-anchor.ts';
import type {HoldoutCommitment, HoldoutAuditEntry} from './holdout-access-audit.ts';

export type HoldoutQuorumReview = {
  status:'QUORUM_CLAIM_TIME_UNVERIFIED'|'INSUFFICIENT_QUORUM';
  requiredAuthorities:number;
  freezeAuthorities:number;
  headAuthorities:number;
  matchingAuthorities:number;
  findings:string[];
};

/** Require both a claimed pre-validation freeze receipt and the current head,
 * co-signed by distinct pinned authority labels. Does not establish independence.
 * Bounded inputs prevent repeated whole-chain signature verification from exploding.
 */
export async function reviewHoldoutAnchorQuorum(
  commitment:HoldoutCommitment, entries:HoldoutAuditEntry[],
  anchors:SignedHoldoutAnchor[], trustedKeys:TrustedAnchorKey[],
  requiredAuthorities:number
):Promise<HoldoutQuorumReview> {
  if (!Number.isSafeInteger(requiredAuthorities) || requiredAuthorities<2 || requiredAuthorities>6)
    throw Error('Quorum threshold must be an integer from 2 to 6');
  if (!Array.isArray(entries) || entries.length>10000 ||
      !Array.isArray(anchors) || anchors.length>12 ||
      !Array.isArray(trustedKeys) || trustedKeys.length>12)
    throw Error('Invalid or excessive quorum audit/signature input');
  // Validate even an empty set, so invalid or contaminated chains never become NO_QUORUM.
  await verifySignedHoldoutAnchors(commitment,entries,[],trustedKeys);
  const pinned=new Map(trustedKeys.map(k=>[k.keyId,k.authority]));
  const freeze=new Set<string>(), head=new Set<string>(), seen=new Set<string>();
  const finalSequence=entries.length;
  // A frozen protocol must be attested BEFORE validation starts, and before
  // any recorded validation read (including an erroneously early read).
  const firstValidationAt=entries.reduce((first,e)=>
    e.action==='VALIDATION_ACCESS'?Math.min(first,e.occurredAt):first,
    Number.POSITIVE_INFINITY);
  for (const anchor of anchors) {
    if (!anchor || !anchor.receipt || typeof anchor.keyId!=='string')
      throw Error('Invalid signed quorum receipt');
    const seq=anchor.receipt.sequence;
    if (seq!==0 && seq!==finalSequence)
      throw Error('Quorum accepts only commitment-freeze and final audit-head receipts');
    const identity=anchor.keyId+'\\u0000'+seq;
    if (seen.has(identity)) throw Error('Duplicate signing key at the same audit head');
    seen.add(identity);
    // Individual verification allows different authorities to co-sign the SAME sequence,
    // while the underlying chronological receipt verifier forbids duplicate sequences.
    await verifySignedHoldoutAnchors(commitment,entries,[anchor],trustedKeys);
    const authority=pinned.get(anchor.keyId);
    if (!authority) throw Error('Untrusted quorum signer');
    if (seq===0 && anchor.receipt.anchoredAt<commitment.protocol.developmentEnd &&
        anchor.receipt.anchoredAt<firstValidationAt)
      freeze.add(authority);
    if (seq===finalSequence)
      head.add(authority);
  }
  const matching=[...freeze].filter(a=>head.has(a)).length;
  const passed=matching>=requiredAuthorities;
  return {
    status:passed?'QUORUM_CLAIM_TIME_UNVERIFIED':'INSUFFICIENT_QUORUM',
    requiredAuthorities,freezeAuthorities:freeze.size,headAuthorities:head.size,
    matchingAuthorities:matching,
    findings:[
      passed?'Supplied pinned keys signed both claimed freeze and final head.':
        'Insufficient distinct authority labels signed both the claimed freeze and final head.',
      'Signer independence, independent key pinning, trusted timestamps, archive authenticity, completeness of access logs and untouched holdouts remain UNVERIFIED.'
    ]
  };
}
