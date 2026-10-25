/**
 * Offline, read-only metadata preflight before any pooled archive research.
 * Evidence references are owner declarations, NOT independently verified proof.
 * No market data, orders, broker connections or file reads are performed.
 */
export type ResearchMode = 'PRICE_ONLY' | 'VOLUME_CONFIRMED';
export type ArchivePreflight = {
  archiveId: string;
  instrument: string;
  provider: string;
  format: 'HISTDATA_ASCII_M1' | 'HISTDATA_MT_M1';
  sha256: string;
  rows: number;
  malformedRows: number;
  invalidOhlcRows: number;
  duplicateOrBackwardRows: number;
  zeroVolumeRows: number;
  observedGapsOverMinute: number;
  /** Exact fixed offset, not a daylight-saving-local timezone. */
  fixedUtcOffsetMinutes: number | null;
  /** UTC epoch seconds after independently reviewing the source convention. */
  firstUtc: number | null;
  lastUtc: number | null;
  /** Owner-supplied traceable references; NOT source authentication. */
  sourceEvidenceRef: string | null;
  usageRightsEvidenceRef: string | null;
  timebaseEvidenceRef: string | null;
};
export type ArchiveQuarantineReason =
  | 'MALFORMED_OR_INVALID_PRICE' | 'NON_MONOTONIC_TIMESTAMPS'
  | 'SOURCE_EVIDENCE_MISSING' | 'RIGHTS_EVIDENCE_MISSING'
  | 'TIMEBASE_EVIDENCE_MISSING' | 'UNVERIFIED_UTC_WINDOW'
  | 'ZERO_OR_UNVERIFIED_VOLUME' | 'BYTE_IDENTICAL_DUPLICATE'
  | 'HASH_IDENTITY_CONFLICT' | 'UNRESOLVED_WINDOW_OVERLAP';
export type ArchiveReadiness = {
  archiveId: string;
  instrument: string;
  provider: string;
  reasons: ArchiveQuarantineReason[];
  metadataCandidateForIndependentReview: boolean;
  /** Never set true based solely on self-reported metadata. */
  independentlyVerified: false;
  approvedForBacktest: false;
  observedGapsOverMinute: number;
};
export type ArchivePortfolioReadiness = {
  engine: 'archive-research-readiness-v1';
  mode: ResearchMode;
  inputArchives: number;
  metadataCandidates: number;
  quarantined: number;
  items: ArchiveReadiness[];
  approvedForBacktest: false;
  independentlyVerified: false;
  warning: string;
};
const MAX_ARCHIVES = 2000;
const REF_LIMIT = 256;
function reference(x: string | null): boolean {
  return typeof x === 'string' && x.trim().length > 0 && x.length <= REF_LIMIT;
}
function validate(x: ArchivePreflight): void {
  if (!x || typeof x !== 'object') throw Error('Invalid archive metadata');
  for (const key of ['archiveId','instrument','provider'] as const) {
    const s=x[key];
    if (typeof s !== 'string' || !s.trim() || s.length > 128) throw Error(`Invalid ${key}`);
  }
  if (!['HISTDATA_ASCII_M1','HISTDATA_MT_M1'].includes(x.format)) throw Error('Unsupported archive format');
  if (!/^[a-f0-9]{64}$/i.test(x.sha256)) throw Error('SHA-256 metadata must be 64 hex characters');
  for (const key of ['rows','malformedRows','invalidOhlcRows','duplicateOrBackwardRows','zeroVolumeRows','observedGapsOverMinute'] as const) {
    if (!Number.isSafeInteger(x[key]) || x[key] < 0) throw Error(`Invalid ${key}`);
  }
  if (x.rows === 0 || x.zeroVolumeRows > x.rows || x.malformedRows > x.rows ||
      x.invalidOhlcRows > x.rows || x.duplicateOrBackwardRows > x.rows ||
      x.observedGapsOverMinute > x.rows) throw Error('Inconsistent row counters');
  const hasOffset=x.fixedUtcOffsetMinutes !== null;
  if (hasOffset && (!Number.isSafeInteger(x.fixedUtcOffsetMinutes) ||
      x.fixedUtcOffsetMinutes! < -840 || x.fixedUtcOffsetMinutes! > 840))
    throw Error('Invalid fixed UTC offset');
  const hasFirst=x.firstUtc !== null,hasLast=x.lastUtc !== null;
  if (hasFirst !== hasLast) throw Error('Incomplete UTC window');
  if (hasFirst && (!Number.isSafeInteger(x.firstUtc) || !Number.isSafeInteger(x.lastUtc) ||
      x.firstUtc! < 0 || x.lastUtc! < x.firstUtc!)) throw Error('Invalid UTC window');
  for (const key of ['sourceEvidenceRef','usageRightsEvidenceRef','timebaseEvidenceRef'] as const) {
    const v=x[key];
    if (v !== null && (typeof v !== 'string' || v.length > REF_LIMIT))
      throw Error(`Invalid ${key}`);
  }
}
/** Returns conservative, order-independent quarantine results. Never authorizes backtesting. */
export function assessArchiveResearchReadiness(
  archives: readonly ArchivePreflight[],mode: ResearchMode
): ArchivePortfolioReadiness {
  if (!['PRICE_ONLY','VOLUME_CONFIRMED'].includes(mode)) throw Error('Unsupported frozen research mode');
  if (!Array.isArray(archives) || archives.length > MAX_ARCHIVES) throw Error('Bounded archive inventory required');
  const byId=new Map<string,ArchivePreflight>();
  for (const x of archives) {
    validate(x);
    if (byId.has(x.archiveId)) throw Error('Duplicate archive ID');
    byId.set(x.archiveId,x);
  }
  const sorted=[...archives].sort((a,b)=>a.archiveId < b.archiveId ? -1 : a.archiveId > b.archiveId ? 1 : 0);
  const reasons=new Map(sorted.map(x=>[x.archiveId,new Set<ArchiveQuarantineReason>()]));
  const mark=(x:ArchivePreflight,why:ArchiveQuarantineReason)=>reasons.get(x.archiveId)!.add(why);
  for (const x of sorted) {
    if (x.malformedRows || x.invalidOhlcRows) mark(x,'MALFORMED_OR_INVALID_PRICE');
    if (x.duplicateOrBackwardRows) mark(x,'NON_MONOTONIC_TIMESTAMPS');
    if (!reference(x.sourceEvidenceRef)) mark(x,'SOURCE_EVIDENCE_MISSING');
    if (!reference(x.usageRightsEvidenceRef)) mark(x,'RIGHTS_EVIDENCE_MISSING');
    if (!reference(x.timebaseEvidenceRef)) mark(x,'TIMEBASE_EVIDENCE_MISSING');
    if (x.fixedUtcOffsetMinutes === null || x.firstUtc === null || x.lastUtc === null ||
        !reference(x.timebaseEvidenceRef)) mark(x,'UNVERIFIED_UTC_WINDOW');
    if (mode==='VOLUME_CONFIRMED' && x.zeroVolumeRows>0) mark(x,'ZERO_OR_UNVERIFIED_VOLUME');
  }
  // Deduplicate byte-identical ZIPs deterministically. Conflicting labels for
  // the same bytes are not evidence that the instrument/provider is correct.
  const hashes=new Map<string,ArchivePreflight[]>();
  for (const x of sorted) hashes.set(x.sha256.toLowerCase(),[...(hashes.get(x.sha256.toLowerCase())||[]),x]);
  for (const group of hashes.values()) {
    if (group.length<2) continue;
    const first=group[0];
    const sameIdentity=group.every(x=>x.instrument===first.instrument&&x.provider===first.provider&&x.format===first.format);
    if (!sameIdentity) for (const x of group) mark(x,'HASH_IDENTITY_CONFLICT');
    else for (const x of group.slice(1)) mark(x,'BYTE_IDENTICAL_DUPLICATE');
  }
  // Different ZIP bytes covering the same source/instrument/UTC minutes may
  // be alternative formats or revised exports. Never silently pool them.
  // Exact duplicates are already accounted for above; ignore their overlap.
  for (let i=0;i<sorted.length;i++) for (let j=i+1;j<sorted.length;j++) {
    const a=sorted[i],b=sorted[j];
    if (a.sha256.toLowerCase()===b.sha256.toLowerCase()) continue;
    if (a.provider!==b.provider || a.instrument!==b.instrument ||
        a.firstUtc===null || a.lastUtc===null || b.firstUtc===null || b.lastUtc===null ||
        a.fixedUtcOffsetMinutes===null || b.fixedUtcOffsetMinutes===null ||
        !reference(a.timebaseEvidenceRef) || !reference(b.timebaseEvidenceRef)) continue;
    if (a.firstUtc<=b.lastUtc && b.firstUtc<=a.lastUtc) {
      mark(a,'UNRESOLVED_WINDOW_OVERLAP');mark(b,'UNRESOLVED_WINDOW_OVERLAP');
    }
  }
  const items=sorted.map(x=>{
    const why=[...reasons.get(x.archiveId)!].sort();
    return {archiveId:x.archiveId,instrument:x.instrument,provider:x.provider,
      reasons:why,metadataCandidateForIndependentReview:why.length===0,
      independentlyVerified:false as const,approvedForBacktest:false as const,
      observedGapsOverMinute:x.observedGapsOverMinute};
  });
  const metadataCandidates=items.filter(x=>x.metadataCandidateForIndependentReview).length;
  return {engine:'archive-research-readiness-v1',mode,inputArchives:items.length,
    metadataCandidates,quarantined:items.length-metadataCandidates,items,
    approvedForBacktest:false,independentlyVerified:false,
    warning:'Metadata references are owner assertions, not independent verification. No backtest, volume signal, live execution or pooled archive research is authorized. Gaps may be session closures.'};
}
