/** Offline pinned-key Ed25519 verification of holdout audit anchors.
 * A signature cannot prove trusted time, complete access logging, archive
 * authenticity or an untouched holdout. No broker, network or order access.
 */
import {verifyHoldoutAudit, type HoldoutCommitment, type HoldoutAuditEntry} from './holdout-access-audit.ts';
import {verifyHoldoutAnchorReceipts, type HoldoutAnchorReceipt} from './holdout-anchor-verification.ts';

export type TrustedAnchorKey = {keyId:string; authority:string; publicKeyBase64url:string};
export type SignedHoldoutAnchor = {receipt:HoldoutAnchorReceipt; keyId:string; signatureBase64url:string};
export type SignedAnchorReview = {
  status:'NO_SIGNED_ANCHOR'|'PARTIALLY_SIGNED_TIME_UNVERIFIED'|'HEAD_SIGNED_TIME_UNVERIFIED';
  signaturesVerified:number; lastAnchoredSequence:number; unanchoredEvents:number; findings:string[];
};
const identifier = (s:unknown):s is string =>
  typeof s === 'string' && /^[A-Za-z0-9._:@/-]{1,100}$/.test(s);
function exactKeys(v:unknown, keys:string[], kind:string):void {
  if (!v || typeof v !== 'object' || Array.isArray(v) ||
      Object.keys(v).length !== keys.length || Object.keys(v).some(k=>!keys.includes(k)))
    throw Error('Invalid '+kind+' schema');
}
function decode64(s:unknown, length:number):Uint8Array {
  if (typeof s !== 'string' || !/^[A-Za-z0-9_-]+$/.test(s) || !globalThis.atob || !globalThis.btoa)
    throw Error('Invalid base64url encoding');
  let raw:string;
  try { raw=atob(s.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-s.length%4)%4)); }
  catch { throw Error('Invalid base64url encoding'); }
  if (raw.length!==length ||
      btoa(raw).replace(/=/g,'').replace(/\+/g,'-').replace(/\//g,'_')!==s)
    throw Error('Noncanonical or invalid-length Ed25519 key/signature');
  return Uint8Array.from(raw,c=>c.charCodeAt(0));
}
/** Domain-separated fixed-order bytes for an independent external signer. */
export function holdoutAnchorSigningMessage(keyId:string, r:HoldoutAnchorReceipt):Uint8Array {
  if (!identifier(keyId)) throw Error('Invalid anchor signing key ID');
  exactKeys(r,['schema','commitmentDigest','sequence','headDigest','anchoredAt','authority','reference'],'receipt');
  return new TextEncoder().encode('trading-strategy-lab/holdout-anchor/ed25519/v1\n'+JSON.stringify({
    keyId,schema:r.schema,commitmentDigest:r.commitmentDigest,sequence:r.sequence,
    headDigest:r.headDigest,anchoredAt:r.anchoredAt,authority:r.authority,reference:r.reference
  }));
}
/** The caller must pin public keys independently, never trust keys from receipts. */
export async function verifySignedHoldoutAnchors(
  commitment:HoldoutCommitment, entries:HoldoutAuditEntry[],
  signedAnchors:SignedHoldoutAnchor[], trustedKeys:TrustedAnchorKey[]
):Promise<SignedAnchorReview> {
  const audit=await verifyHoldoutAudit(commitment,entries);
  if (audit.recordedStatus!=='NO_CONTAMINATION_RECORDED')
    throw Error('Recorded holdout contamination: signatures cannot restore an untouched holdout');
  if (!Array.isArray(signedAnchors) || signedAnchors.length>10000 ||
      !Array.isArray(trustedKeys) || trustedKeys.length>1000)
    throw Error('Invalid or excessive signed anchors / trust registry');
  const keys=new Map<string,{authority:string; bytes:Uint8Array}>();
  const seenKeys=new Set<string>();
  for (const key of trustedKeys) {
    exactKeys(key,['keyId','authority','publicKeyBase64url'],'trusted key');
    if (!identifier(key.keyId) || !identifier(key.authority) || keys.has(key.keyId) ||
        seenKeys.has(key.publicKeyBase64url))
      throw Error('Invalid, duplicate or reused trusted signing identity');
    const bytes=decode64(key.publicKeyBase64url,32);
    keys.set(key.keyId,{authority:key.authority,bytes});
    seenKeys.add(key.publicKeyBase64url);
  }
  const receipts:HoldoutAnchorReceipt[]=[];
  for (const signed of signedAnchors) {
    exactKeys(signed,['receipt','keyId','signatureBase64url'],'signed anchor');
    if (!identifier(signed.keyId) || !keys.has(signed.keyId))
      throw Error('Untrusted or missing pinned anchor signing key');
    if (signed.receipt?.authority!==keys.get(signed.keyId)!.authority)
      throw Error('Anchor signer authority does not match pinned key');
    receipts.push(signed.receipt);
  }
  const heads=verifyHoldoutAnchorReceipts(commitment,entries,receipts);
  if (signedAnchors.length && !globalThis.crypto?.subtle)
    throw Error('WebCrypto Ed25519 unavailable; fail closed');
  for (const signed of signedAnchors) {
    const signature=decode64(signed.signatureBase64url,64);
    const trusted=keys.get(signed.keyId)!;
    let valid=false;
    try {
      const key=await globalThis.crypto.subtle.importKey('raw',Uint8Array.from(trusted.bytes),
        {name:'Ed25519'},false,['verify']);
      valid=await globalThis.crypto.subtle.verify({name:'Ed25519'},key,Uint8Array.from(signature),
        holdoutAnchorSigningMessage(signed.keyId,signed.receipt));
    } catch { throw Error('Ed25519 verification unavailable or failed closed'); }
    if (!valid) throw Error('Invalid holdout anchor signature');
  }
  return {
    status:!signedAnchors.length?'NO_SIGNED_ANCHOR':heads.unanchoredEvents?
      'PARTIALLY_SIGNED_TIME_UNVERIFIED':'HEAD_SIGNED_TIME_UNVERIFIED',
    signaturesVerified:signedAnchors.length,lastAnchoredSequence:heads.lastAnchoredSequence,
    unanchoredEvents:heads.unanchoredEvents,
    findings:[...heads.findings,
      'Pinned-key signatures do not authenticate key distribution, timestamps, omitted access events, archive bytes or independent retention.']
  };
}
