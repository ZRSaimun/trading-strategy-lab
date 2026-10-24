import {test} from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {createHoldoutCommitment,appendHoldoutAuditEvent} from '../lib/holdout-access-audit.ts';
import {holdoutAnchorSigningMessage,
  type SignedHoldoutAnchor,type TrustedAnchorKey} from '../lib/holdout-signed-anchor.ts';
import type {HoldoutAnchorReceipt} from '../lib/holdout-anchor-verification.ts';
import {reviewHoldoutAnchorQuorum} from '../lib/holdout-quorum-review.ts';

const b64=(b:Uint8Array)=>Buffer.from(b).toString('base64url');
const start=1_600_000_000,year=365*86400;
const archives=Array.from({length:5},(_,i)=>({
  id:'source-'+i,provider:'offline-provider',instrument:'XAUUSD',venue:'CFD',
  priceSide:'bid_ask' as const,utcConvention:'UTC' as const,
  archiveSha256:(i+1).toString(16).repeat(64),start:start+i*year,end:start+(i+1)*year
}));
const protocol={developmentEnd:start+3*year,validationEnd:start+4*year,
  holdoutEnd:start+5*year,embargoSeconds:86400,
  strategyVersion:'frozen-v1',configSha256:'a'.repeat(64)};
async function fixture(){
  const commitment=await createHoldoutCommitment(archives,protocol,'researcher',start+2*year);
  const entries=await appendHoldoutAuditEvent(commitment,[],{
    eventId:'v1',action:'VALIDATION_ACCESS',archiveId:'source-3',occurredAt:start+3*year+100
  });
  const makeSigner=async(id:string,authority=id)=>{
    const pair=await webcrypto.subtle.generateKey('Ed25519',true,['sign','verify']) as CryptoKeyPair;
    const trusted:TrustedAnchorKey={keyId:id,authority,
      publicKeyBase64url:b64(new Uint8Array(await webcrypto.subtle.exportKey('raw',pair.publicKey)))};
    const sign=async(receipt:HoldoutAnchorReceipt):Promise<SignedHoldoutAnchor>=>({
      receipt,keyId:id,signatureBase64url:b64(new Uint8Array(await webcrypto.subtle.sign(
        'Ed25519',pair.privateKey,holdoutAnchorSigningMessage(id,receipt))))
    });
    return {trusted,sign};
  };
  const a=await makeSigner('a'),b=await makeSigner('b');
  const receipt=(authority:string,sequence:number,anchoredAt:number):HoldoutAnchorReceipt=>({
    schema:'holdout-anchor-receipt-v1',commitmentDigest:commitment.digest,sequence,
    headDigest:sequence===0?commitment.digest:entries[sequence-1].digest,
    anchoredAt,authority,reference:authority+'-'+sequence
  });
  const freeze=commitment.frozenAt+100,head=entries[0].occurredAt+100;
  const a0=await a.sign(receipt(a.trusted.authority,0,freeze));
  const a1=await a.sign(receipt(a.trusted.authority,1,head));
  const b0=await b.sign(receipt(b.trusted.authority,0,freeze));
  const b1=await b.sign(receipt(b.trusted.authority,1,head));
  return {commitment,entries,a,b,a0,a1,b0,b1,receipt,makeSigner};
}
test('two distinct pinned authority labels sign both freeze and final head',async()=>{
  const f=await fixture();
  const out=await reviewHoldoutAnchorQuorum(f.commitment,f.entries,
    [f.a0,f.b0,f.a1,f.b1],[f.a.trusted,f.b.trusted],2);
  assert.equal(out.status,'QUORUM_CLAIM_TIME_UNVERIFIED');
  assert.equal(out.matchingAuthorities,2);
  assert.match(out.findings.join(' '),/UNVERIFIED/);
});
test('one signer never satisfies two-authority quorum',async()=>{
  const f=await fixture();
  const out=await reviewHoldoutAnchorQuorum(f.commitment,f.entries,
    [f.a0,f.a1],[f.a.trusted],2);
  assert.equal(out.status,'INSUFFICIENT_QUORUM');
  assert.equal(out.matchingAuthorities,1);
});
test('head signatures without matching freeze signatures fail closed',async()=>{
  const f=await fixture();
  const out=await reviewHoldoutAnchorQuorum(f.commitment,f.entries,
    [f.a0,f.a1,f.b1],[f.a.trusted,f.b.trusted],2);
  assert.equal(out.status,'INSUFFICIENT_QUORUM');
  assert.equal(out.freezeAuthorities,1);
});
test('late claimed freeze receipt cannot count as preregistration',async()=>{
  const f=await fixture();
  const late=await f.b.sign(f.receipt('b',0,protocol.validationEnd+1));
  const out=await reviewHoldoutAnchorQuorum(f.commitment,f.entries,
    [f.a0,f.a1,late,f.b1],[f.a.trusted,f.b.trusted],2);
  assert.equal(out.status,'INSUFFICIENT_QUORUM');
});
test('freeze signed after validation begins cannot count even before first validation read',async()=>{
  const f=await fixture();
  const late=await f.b.sign(f.receipt('b',0,protocol.developmentEnd+1));
  const out=await reviewHoldoutAnchorQuorum(f.commitment,f.entries,
    [f.a0,f.a1,late,f.b1],[f.a.trusted,f.b.trusted],2);
  assert.equal(out.status,'INSUFFICIENT_QUORUM');
  assert.equal(out.matchingAuthorities,1);
});
test('a recorded validation read before freeze attestation disqualifies the freeze',async()=>{
  const f=await fixture();
  const earlyEntries=await appendHoldoutAuditEvent(f.commitment,[],{
    eventId:'early-validation-read',action:'VALIDATION_ACCESS',archiveId:'source-3',
    occurredAt:f.commitment.frozenAt+50
  });
  const aHead=await f.a.sign({...f.a0.receipt,sequence:1,
    headDigest:earlyEntries[0].digest,anchoredAt:f.commitment.frozenAt+150,
    reference:'a-early-head'});
  const bHead=await f.b.sign({...f.b0.receipt,sequence:1,
    headDigest:earlyEntries[0].digest,anchoredAt:f.commitment.frozenAt+150,
    reference:'b-early-head'});
  const out=await reviewHoldoutAnchorQuorum(f.commitment,earlyEntries,
    [f.a0,f.b0,aHead,bHead],[f.a.trusted,f.b.trusted],2);
  assert.equal(out.status,'INSUFFICIENT_QUORUM');
  assert.equal(out.freezeAuthorities,0);
});
test('invalid signature and duplicate signer are rejected',async()=>{
  const f=await fixture();
  await assert.rejects(reviewHoldoutAnchorQuorum(f.commitment,f.entries,
    [f.a0,f.a1,{...f.b0,signatureBase64url:f.a0.signatureBase64url},f.b1],
    [f.a.trusted,f.b.trusted],2),/Invalid holdout anchor signature/);
  await assert.rejects(reviewHoldoutAnchorQuorum(f.commitment,f.entries,
    [f.a0,f.a0],[f.a.trusted],2),/Duplicate signing key/);
});
test('two pinned keys claiming the same authority are not independent',async()=>{
  const f=await fixture();
  const c=await f.makeSigner('c','a');
  const c0=await c.sign(f.receipt('a',0,f.commitment.frozenAt+100));
  const c1=await c.sign(f.receipt('a',1,f.entries[0].occurredAt+100));
  const out=await reviewHoldoutAnchorQuorum(f.commitment,f.entries,
    [f.a0,f.a1,c0,c1],[f.a.trusted,c.trusted],2);
  assert.equal(out.status,'INSUFFICIENT_QUORUM');
  assert.equal(out.matchingAuthorities,1);
});
test('recorded premature holdout access and invalid thresholds are rejected',async()=>{
  const f=await fixture();
  const contaminated=await appendHoldoutAuditEvent(f.commitment,f.entries,{
    eventId:'early',action:'HOLDOUT_ACCESS',archiveId:'source-4',
    occurredAt:f.entries[0].occurredAt+1
  });
  await assert.rejects(reviewHoldoutAnchorQuorum(f.commitment,contaminated,
    [],[],2),/contamination/);
  await assert.rejects(reviewHoldoutAnchorQuorum(f.commitment,f.entries,
    [],[],1),/threshold/);
});

test('zero-event audit cannot double-count freeze as the final head',async()=>{
  const f=await fixture();
  await assert.rejects(reviewHoldoutAnchorQuorum(f.commitment,[],
    [f.a0,f.b0],[f.a.trusted,f.b.trusted],2),
    /nonempty audit trail/);
  await assert.rejects(reviewHoldoutAnchorQuorum(f.commitment,[],
    [],[],2),/nonempty audit trail/);
});
