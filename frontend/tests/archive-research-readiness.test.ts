import {test} from 'node:test';
import assert from 'node:assert/strict';
import {assessArchiveResearchReadiness} from '../lib/archive-research-readiness.ts';
import type {ArchivePreflight} from '../lib/archive-research-readiness.ts';
const H='a'.repeat(64),K='b'.repeat(64),J='c'.repeat(64);
function archive(id='a',sha=H):ArchivePreflight {
  return {archiveId:id,instrument:'NSXUSD-CFD',provider:'HistData',format:'HISTDATA_ASCII_M1',
    sha256:sha,rows:100,malformedRows:0,invalidOhlcRows:0,duplicateOrBackwardRows:0,
    zeroVolumeRows:100,observedGapsOverMinute:3,fixedUtcOffsetMinutes:-300,
    firstUtc:1704067200,lastUtc:1704073140,sourceEvidenceRef:'owner source receipt',
    usageRightsEvidenceRef:'owner rights review',timebaseEvidenceRef:'fixed-offset documentation'};
}
const audit=(a:ArchivePreflight[],mode:'PRICE_ONLY'|'VOLUME_CONFIRMED'='PRICE_ONLY')=>assessArchiveResearchReadiness(a,mode);
test('clean metadata is a review candidate, never an approved or independently verified backtest',()=>{
  const a=audit([archive()]);
  assert.equal(a.metadataCandidates,1);assert.equal(a.approvedForBacktest,false);
  assert.equal(a.independentlyVerified,false);assert.equal(a.items[0].approvedForBacktest,false);
  assert.equal(a.items[0].observedGapsOverMinute,3);
});
test('unverified timezone or evidence quarantines even otherwise clean OHLC',()=>{
  const x=archive();x.fixedUtcOffsetMinutes=null;x.firstUtc=null;x.lastUtc=null;x.timebaseEvidenceRef=null;
  x.sourceEvidenceRef=null;x.usageRightsEvidenceRef=null;
  const reasons=audit([x]).items[0].reasons;
  for (const expected of ['UNVERIFIED_UTC_WINDOW','TIMEBASE_EVIDENCE_MISSING','SOURCE_EVIDENCE_MISSING','RIGHTS_EVIDENCE_MISSING'])
    assert.ok(reasons.includes(expected as typeof reasons[number]));
});
test('duplicate or backward timestamps and invalid prices quarantine',()=>{
  const x=archive();x.duplicateOrBackwardRows=1;x.invalidOhlcRows=1;
  assert.deepEqual(audit([x]).items[0].reasons,['MALFORMED_OR_INVALID_PRICE','NON_MONOTONIC_TIMESTAMPS']);
});
test('zero volume blocks volume-confirmed research but not price-only review',()=>{
  assert.equal(audit([archive()]).metadataCandidates,1);
  assert.deepEqual(audit([archive()],'VOLUME_CONFIRMED').items[0].reasons,['ZERO_OR_UNVERIFIED_VOLUME']);
});
test('byte-identical ZIPs are deterministically deduplicated regardless of input order',()=>{
  const a=archive('z'),b=archive('a');
  const one=audit([a,b]),two=audit([b,a]);
  assert.deepEqual(one,two);
  assert.equal(one.metadataCandidates,1);
  assert.deepEqual(one.items[1].reasons,['BYTE_IDENTICAL_DUPLICATE']);
});
test('same hash with conflicting identity blocks both rather than choosing an identity',()=>{
  const a=archive('a'),b=archive('b');b.instrument='XAUUSD';
  assert.equal(audit([a,b]).metadataCandidates,0);
  for(const x of audit([a,b]).items) assert.deepEqual(x.reasons,['HASH_IDENTITY_CONFLICT']);
});
test('overlapping different archive bytes cannot be pooled within same provider/instrument',()=>{
  const a=archive('a',H),b=archive('b',K);b.format='HISTDATA_MT_M1';
  const result=audit([a,b]);
  assert.equal(result.metadataCandidates,0);
  assert.deepEqual(result.items.map(x=>x.reasons),[['UNRESOLVED_WINDOW_OVERLAP'],['UNRESOLVED_WINDOW_OVERLAP']]);
});
test('adjacent non-overlapping windows remain separate review candidates',()=>{
  const a=archive('a',H),b=archive('b',K);b.firstUtc=a.lastUtc!+60;b.lastUtc=b.firstUtc+600;
  assert.equal(audit([a,b]).metadataCandidates,2);
});
test('different source identity is not automatically pooled or mislabeled as same-source overlap',()=>{
  const a=archive('a',H),b=archive('b',K);b.provider='Other';
  assert.equal(audit([a,b]).metadataCandidates,2);
});
test('invalid counts, SHA, offsets, UTC bounds, duplicate IDs, and unsupported mode fail closed',()=>{
  const variants=[(x:ArchivePreflight)=>{x.rows=0},(x:ArchivePreflight)=>{x.zeroVolumeRows=101},
    (x:ArchivePreflight)=>{x.sha256='x'},(x:ArchivePreflight)=>{x.fixedUtcOffsetMinutes=900},
    (x:ArchivePreflight)=>{x.lastUtc=x.firstUtc!-1},(x:ArchivePreflight)=>{x.firstUtc=null},
    (x:ArchivePreflight)=>{x.duplicateOrBackwardRows=-1},(x:ArchivePreflight)=>{x.sourceEvidenceRef='x'.repeat(257)}];
  for (const change of variants) {const x=archive();change(x);assert.throws(()=>audit([x]));}
  assert.throws(()=>audit([archive(),archive()] ),/Duplicate archive ID/);
  assert.throws(()=>assessArchiveResearchReadiness([],'INVALID' as 'PRICE_ONLY'));
});
test('quarantines same-instrument overlap only when UTC timebase is declared; missing timebase already blocks',()=>{
  const a=archive('a',H),b=archive('b',J);b.timebaseEvidenceRef=null;
  const out=audit([a,b]);
  assert.deepEqual(out.items[0].reasons,[]);
  assert.ok(out.items[1].reasons.includes('UNVERIFIED_UTC_WINDOW'));
  assert.equal(out.approvedForBacktest,false);
});
