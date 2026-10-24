/** Offline, metadata-only chronological research partitioning.
 * No outcomes, prices, broker calls, or trading orders are accepted.
 * A hash/partition plan does not attest that a holdout was truly untouched.
 */
export type ArchiveLineage = {
  id: string;
  provider: string;
  instrument: string;
  venue: string;
  priceSide: 'bid' | 'ask' | 'mid' | 'bid_ask';
  utcConvention: 'UTC';
  archiveSha256: string;
  start: number; // inclusive UTC epoch seconds
  end: number; // exclusive UTC epoch seconds
};
export type OutcomeTiming = {
  id: string;
  archiveId: string;
  featureStart: number;
  decisionAt: number;
  labelAvailableAt: number; // outcome is not usable before this timestamp
};
export type HoldoutProtocol = {
  developmentEnd: number;
  validationEnd: number;
  holdoutEnd: number;
  embargoSeconds: number;
  strategyVersion: string;
  configSha256: string;
};
export type Partition = 'development' | 'validation' | 'holdout';
export type PurgedPlan = {
  source: {provider: string; instrument: string; venue: string; priceSide: ArchiveLineage['priceSide']; utcConvention: 'UTC'};
  archiveLineage: {id: string; archiveSha256: string; start: number; end: number}[];
  protocol: HoldoutProtocol;
  eligible: Record<Partition, string[]>;
  excluded: {id: string; reason: 'EMBARGO_OR_UNSETTLED' | 'CROSS_BOUNDARY_FEATURES' | 'OUTSIDE_PERIOD'}[];
  warnings: string[];
};
const SHA = /^[a-f0-9]{64}$/;
const SEC_YEAR = 365 * 86400;
const keys = (obj: object, allowed: string[], kind: string) => {
  if (Object.keys(obj).some(k => !allowed.includes(k))) throw Error(kind + ' contains unsupported fields; outcome data must not enter the partition planner');
};
const epoch = (x: number) => Number.isSafeInteger(x) && x >= 0;
const nonblank = (x: unknown) => typeof x === 'string' && x.length > 0 && x.trim() === x && x.length <= 200;

/** All partitions are specified *before* reading labels. Caller must separately
 * enforce an immutable preregistration/audit trail and restrict holdout access.
 */
export function planPurgedHoldout(archives: ArchiveLineage[], observations: OutcomeTiming[], protocol: HoldoutProtocol): PurgedPlan {
  if (!Array.isArray(archives) || !archives.length || !Array.isArray(observations) || !protocol)
    throw Error('Explicit archive lineage, timing metadata and protocol are required');
  keys(protocol, ['developmentEnd','validationEnd','holdoutEnd','embargoSeconds','strategyVersion','configSha256'], 'Protocol');
  const {developmentEnd, validationEnd, holdoutEnd, embargoSeconds} = protocol;
  if (![developmentEnd, validationEnd, holdoutEnd, embargoSeconds].every(epoch) ||
      !(developmentEnd < validationEnd && validationEnd < holdoutEnd) ||
      embargoSeconds < 0 || embargoSeconds > 30 * 86400 ||
      !nonblank(protocol.strategyVersion) || !SHA.test(protocol.configSha256))
    throw Error('Invalid preregistered chronological boundaries, embargo or strategy identity');
  const lineage = [...archives].sort((a,b) => a.start-b.start);
  const ids = new Set<string>();
  // The same immutable archive bytes cannot legitimately describe two different
  // disjoint UTC coverage windows. Reject digest reuse rather than trusting
  // inconsistent metadata and silently double-counting source evidence.
  const archiveDigests = new Set<string>();
  let source: PurgedPlan['source'] | null = null;
  let previousEnd = -1;
  const warnings: string[] = [];
  for (const a of lineage) {
    if (!a || typeof a !== 'object') throw Error('Malformed archive lineage');
    keys(a, ['id','provider','instrument','venue','priceSide','utcConvention','archiveSha256','start','end'], 'Archive');
    if (![a.id,a.provider,a.instrument,a.venue].every(nonblank) || !SHA.test(a.archiveSha256) ||
        !epoch(a.start) || !epoch(a.end) || a.end <= a.start ||
        !['bid','ask','mid','bid_ask'].includes(a.priceSide) || a.utcConvention !== 'UTC' ||
        ids.has(a.id) || archiveDigests.has(a.archiveSha256))
      throw Error('Invalid or duplicate source-identified archive');
    if (a.start < previousEnd) throw Error('Overlapping archive coverage; no silent source stitching');
    if (previousEnd >= 0 && a.start > previousEnd) warnings.push('Archive coverage has gaps; no candles or trading sessions were inferred.');
    previousEnd = a.end;
    ids.add(a.id);
    archiveDigests.add(a.archiveSha256);
    const identity = {provider:a.provider,instrument:a.instrument,venue:a.venue,priceSide:a.priceSide,utcConvention:a.utcConvention};
    if (source && Object.keys(identity).some(k => identity[k as keyof typeof identity] !== source![k as keyof typeof source]))
      throw Error('Source family changed across archives; do not mix instruments, venues, quote sides or timestamp conventions');
    source = identity;
  }
  if (developmentEnd - lineage[0].start < 2 * SEC_YEAR)
    throw Error('Development span must cover at least two elapsed years; this does not establish continuous market coverage');
  if (lineage.at(-1)!.end < holdoutEnd || lineage[0].start >= developmentEnd)
    throw Error('Archive lineage does not span the preregistered evaluation period');
  const byId = new Map(lineage.map(a => [a.id,a]));
  const seen = new Set<string>();
  const eligible: PurgedPlan['eligible'] = {development:[],validation:[],holdout:[]};
  const excluded: PurgedPlan['excluded'] = [];
  for (const o of observations) {
    if (!o || typeof o !== 'object') throw Error('Malformed timing observation');
    keys(o, ['id','archiveId','featureStart','decisionAt','labelAvailableAt'], 'Observation');
    const a = byId.get(o.archiveId);
    if (!nonblank(o.id) || seen.has(o.id) || !a ||
        ![o.featureStart,o.decisionAt,o.labelAvailableAt].every(epoch) ||
        o.featureStart > o.decisionAt || o.decisionAt > o.labelAvailableAt ||
        // Archive coverage is [start, end): a label at end is not evidenced by
        // this archive. Do not silently borrow the next archive's observation.
        o.featureStart < a.start || o.decisionAt >= a.end || o.labelAvailableAt >= a.end)
      throw Error('Duplicate, noncausal or unverified observation timing/lineage');
    seen.add(o.id);
    if (o.decisionAt >= holdoutEnd) {excluded.push({id:o.id,reason:'OUTSIDE_PERIOD'});continue;}
    const partition: Partition = o.decisionAt < developmentEnd ? 'development' : o.decisionAt < validationEnd ? 'validation' : 'holdout';
    const lower = partition === 'development' ? lineage[0].start : partition === 'validation' ? developmentEnd : validationEnd;
    const upper = partition === 'development' ? developmentEnd : partition === 'validation' ? validationEnd : holdoutEnd;
    // Conservative: no features from before the evaluation segment are allowed.
    if (o.featureStart < lower) {excluded.push({id:o.id,reason:'CROSS_BOUNDARY_FEATURES'});continue;}
    // Labels must be fully known *before* the segment ends, plus a fixed purge/embargo.
    if (o.labelAvailableAt > upper - embargoSeconds) {excluded.push({id:o.id,reason:'EMBARGO_OR_UNSETTLED'});continue;}
    eligible[partition].push(o.id);
  }
  if (!eligible.development.length || !eligible.validation.length || !eligible.holdout.length)
    warnings.push('At least one chronological partition has zero eligible observations; no performance inference is possible.');
  warnings.push('Partition plan reads no outcomes. Archive hashes are identifiers, not authenticity, licensing or proof of an untouched holdout.');
  warnings.push('No executable bid/ask quotes, broker charges, financing, fill quality or statistical edge are established.');
  return {source:source!,archiveLineage:lineage.map(({id,archiveSha256,start,end})=>({id,archiveSha256,start,end})),
    protocol:{...protocol},eligible,excluded,warnings:[...new Set(warnings)]};
}
