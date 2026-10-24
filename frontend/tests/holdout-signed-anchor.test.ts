import {test} from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {createHoldoutCommitment,appendHoldoutAuditEvent} from '../lib/holdout-access-audit.ts';
import {holdoutAnchorSigningMessage,verifySignedHoldoutAnchors,
  type SignedHoldoutAnchor,type TrustedAnchorKey} from '../lib/holdout-signed-anchor.ts';
import type {HoldoutAnchorReceipt} from '../lib/holdout-anchor-verification.ts';

const b64=(bytes:Uint8Array)=>Buffer.from(bytes).toString('base64url');
const start=1_600_000_000, year=365*86400;
const archives=Array.from({length:5},(_,i)=>({
  id:'source-'+i,provider:'offline-provider',instrument:'XAUUSD',venue:'CFD',
  priceSide:'bid_ask' as const,utcConvention:'UTC' as const,
  archiveSha256:(i+1).toString(16).repeat(64),start:start+i*year,end:start+(i+1)*year
}));
const protocol={developmentEnd:start+3*year,validationEnd:start+4*year,
  holdoutEnd:start+5*year,embargoSeconds:86400,strategyVersion:'frozen-v1',configSha256:'a'.repeat(64)};
async function fixture(){
  const commitment=await createHoldoutCommitment(archives,protocol,'researcher',start+2*year);
  const entries=await appendHoldoutAuditEvent(commitment,[],{
    eventId:'v1',action:'VALIDATION_ACCESS',archiveId:'source-3',occurredAt:start+3*year+100
  });
  const pair=await webcrypto.subtle.generateKey('Ed25519',true,['sign','verify']) as CryptoKeyPair;
  const pub=new Uint8Array(await webcrypto.subtle.exportKey('raw',pair.publicKey));
  const trusted:TrustedAnchorKey={keyId:'anchor-1',authority:'pinned-auditor',publicKeyBase64url:b64(pub)};
  const receipt:HoldoutAnchorReceipt={schema:'holdout-anchor-receipt-v1',
    commitmentDigest:commitment.digest,sequence:1,headDigest:entries[0].digest,
    anchoredAt:entries[0].occurredAt+10,authority:trusted.authority,reference:'independent-001'};
  const sign=async(r:HoldoutAnchorReceipt,keyId=trusted.keyId):Promise<SignedHoldoutAnchor>=>({
    receipt:r,keyId,signatureBase64url:b64(new Uint8Array(await webcrypto.subtle.sign(
      'Ed25519',pair.privateKey,holdoutAnchorSigningMessage(keyId,r))))
  });
  return {commitment,entries,trusted,receipt,sign};
}
test('no signed receipt never implies a pinned head',async()=>{
  const f=await fixture(),out=await verifySignedHoldoutAnchors(f.commitment,f.entries,[],[]);
  assert.equal(out.status,'NO_SIGNED_ANCHOR');assert.equal(out.unanchoredEvents,1);
});
test('pinned Ed25519 receipt verifies but does not certify trusted time',async()=>{
  const f=await fixture(),out=await verifySignedHoldoutAnchors(
    f.commitment,f.entries,[await f.sign(f.receipt)],[f.trusted]);
  assert.equal(out.status,'HEAD_SIGNED_TIME_UNVERIFIED');assert.equal(out.signaturesVerified,1);
  assert.match(out.findings.join(' '),/do not authenticate/);
});
test('signed commitment-only receipt leaves later events unanchored',async()=>{
  const f=await fixture(),r={...f.receipt,sequence:0,headDigest:f.commitment.digest,
    anchoredAt:f.commitment.frozenAt};
  const out=await verifySignedHoldoutAnchors(f.commitment,f.entries,[await f.sign(r)],[f.trusted]);
  assert.equal(out.status,'PARTIALLY_SIGNED_TIME_UNVERIFIED');assert.equal(out.unanchoredEvents,1);
});
test('rejects tampered signed receipt',async()=>{
  const f=await fixture(),signed=await f.sign(f.receipt);
  await assert.rejects(verifySignedHoldoutAnchors(f.commitment,f.entries,
    [{...signed,receipt:{...signed.receipt,reference:'rewritten'}}],[f.trusted]),/Invalid holdout anchor signature/);
});
test('rejects unknown key and signer authority substitution',async()=>{
  const f=await fixture(),signed=await f.sign(f.receipt);
  await assert.rejects(verifySignedHoldoutAnchors(f.commitment,f.entries,[signed],[]),/Untrusted/);
  await assert.rejects(verifySignedHoldoutAnchors(f.commitment,f.entries,
    [signed],[{...f.trusted,authority:'other-auditor'}]),/authority/);
});
test('rejects wrong pinned public key even with same key ID',async()=>{
  const f=await fixture(),signed=await f.sign(f.receipt);
  const other=await webcrypto.subtle.generateKey('Ed25519',true,['sign','verify']) as CryptoKeyPair;
  const replacement={...f.trusted,publicKeyBase64url:b64(
    new Uint8Array(await webcrypto.subtle.exportKey('raw',other.publicKey)))};
  await assert.rejects(verifySignedHoldoutAnchors(f.commitment,f.entries,
    [signed],[replacement]),/Invalid holdout anchor signature/);
});
test('rejects duplicate or reused trusted keys and malformed encoding',async()=>{
  const f=await fixture(),signed=await f.sign(f.receipt);
  await assert.rejects(verifySignedHoldoutAnchors(f.commitment,f.entries,
    [signed],[f.trusted,f.trusted]),/duplicate/);
  await assert.rejects(verifySignedHoldoutAnchors(f.commitment,f.entries,
    [signed],[{...f.trusted,keyId:'anchor-2'},f.trusted]),/reused/);
  await assert.rejects(verifySignedHoldoutAnchors(f.commitment,f.entries,
    [signed],[{...f.trusted,publicKeyBase64url:'abc'}]),/invalid-length/);
});
test('rejects invalid signature encoding and unexpected fields',async()=>{
  const f=await fixture(),signed=await f.sign(f.receipt);
  await assert.rejects(verifySignedHoldoutAnchors(f.commitment,f.entries,
    [{...signed,signatureBase64url:'!!!'}],[f.trusted]),/base64url/);
  await assert.rejects(verifySignedHoldoutAnchors(f.commitment,f.entries,
    [{...signed,profit:123} as unknown as SignedHoldoutAnchor],[f.trusted]),/schema/);
});
test('rejects rewritten audit chain despite original signed head',async()=>{
  const f=await fixture(),signed=await f.sign(f.receipt);
  await assert.rejects(verifySignedHoldoutAnchors(f.commitment,
    [{...f.entries[0],digest:'b'.repeat(64)}],[signed],[f.trusted]),/digest mismatch/);
});
test('recorded early holdout access fails closed',async()=>{
  const f=await fixture();
  const entries=await appendHoldoutAuditEvent(f.commitment,f.entries,{
    eventId:'early-h',action:'HOLDOUT_ACCESS',archiveId:'source-4',occurredAt:f.entries[0].occurredAt+1});
  await assert.rejects(verifySignedHoldoutAnchors(f.commitment,entries,[],[]),/contamination/);
});
test('signature is bound to pinned key ID',async()=>{
  const f=await fixture(),signed=await f.sign(f.receipt);
  await assert.rejects(verifySignedHoldoutAnchors(f.commitment,f.entries,
    [{...signed,keyId:'anchor-2'}],[{...f.trusted,keyId:'anchor-2'}]),/Invalid holdout anchor signature/);
});
