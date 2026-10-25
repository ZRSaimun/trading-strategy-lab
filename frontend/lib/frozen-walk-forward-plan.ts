/** Offline, source-bound, metadata-only expanding walk-forward schedule.
 * This never reads candles, labels, returns, broker quotes or orders. A schedule
 * digest is NOT an external preregistration, immutable access log or proof of edge.
 */
import type {OutcomeTiming, PurgedPlan} from './purged-holdout-plan.ts';

export type ForwardWindow = Readonly<{
  id: string;
  trainingStart: number;
  trainingEnd: number;
  testingStart: number;
  testingEnd: number;
}>;
export type FrozenForwardSpecification = Readonly<{
  folds: readonly ForwardWindow[];
  embargoSeconds: number;
  minTrainingObservations: number;
  minTestingObservations: number;
}>;
export type ForwardWindowReview = Readonly<{
  id: string;
  trainingIds: readonly string[];
  testingIds: readonly string[];
  trainingExcluded: number;
  testingExcluded: number;
  status: 'TIMING_ONLY' | 'INSUFFICIENT_TIMING_COUNTS';
}>;
export type FrozenForwardReview = Readonly<{
  schema: 'frozen-walk-forward-v1';
  scheduleSha256: string;
  source: PurgedPlan['source'];
  folds: readonly ForwardWindowReview[];
  coverage: 'UNVERIFIED_METADATA_ONLY';
  warnings: readonly string[];
}>;

const SHA = /^[a-f0-9]{64}$/;
const epoch = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0;
const ident = (v: unknown): v is string => typeof v === 'string' && /^[A-Za-z0-9._:-]{1,100}$/.test(v);
const nonblank = (v: unknown): v is string => typeof v === 'string' && v.length > 0 && v.trim() === v && v.length <= 200;
function exact(value: unknown, fields: readonly string[], kind: string): void {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      Object.keys(value).length !== fields.length || Object.keys(value).some(k => !fields.includes(k)))
    throw Error(`Invalid ${kind} schema: extra outcome fields and missing metadata are forbidden`);
}
function checkPlan(plan: PurgedPlan): void {
  exact(plan, ['source','archiveLineage','protocol','eligible','excluded','warnings'], 'purged plan');
  exact(plan.source, ['provider','instrument','venue','priceSide','utcConvention'], 'source');
  exact(plan.protocol, ['developmentEnd','validationEnd','holdoutEnd','embargoSeconds','strategyVersion','configSha256'], 'protocol');
  exact(plan.eligible, ['development','validation','holdout'], 'eligible partitions');
  if (!['provider','instrument','venue'].every(k => {
        const s = plan.source[k as 'provider' | 'instrument' | 'venue'];
        return typeof s === 'string' && s.trim() === s && s.length > 0 && s.length <= 200;
      }) || !['bid','ask','mid','bid_ask'].includes(plan.source.priceSide) ||
      plan.source.utcConvention !== 'UTC' || !SHA.test(plan.protocol.configSha256) ||
      !nonblank(plan.protocol.strategyVersion) ||
      ![plan.protocol.developmentEnd,plan.protocol.validationEnd,plan.protocol.holdoutEnd,
        plan.protocol.embargoSeconds].every(epoch) ||
      !(plan.protocol.developmentEnd < plan.protocol.validationEnd &&
        plan.protocol.validationEnd < plan.protocol.holdoutEnd) ||
      plan.protocol.embargoSeconds > 30 * 86400 ||
      !Array.isArray(plan.eligible.development) || !Array.isArray(plan.eligible.validation) ||
      !Array.isArray(plan.eligible.holdout) || !Array.isArray(plan.excluded) ||
      !Array.isArray(plan.warnings) || !Array.isArray(plan.archiveLineage) ||
      plan.archiveLineage.length < 1 || plan.archiveLineage.length > 10000)
    throw Error('Invalid source, archive, partition or protocol identity');
  const archiveIds = new Set<string>(), hashes = new Set<string>();
  let lastEnd = -1;
  for (const a of [...plan.archiveLineage].sort((x,y) => x.start-y.start)) {
    exact(a, ['id','archiveSha256','start','end'], 'archive lineage');
    if (!nonblank(a.id) || !SHA.test(a.archiveSha256) || !epoch(a.start) || !epoch(a.end) ||
        a.start >= a.end || a.start < lastEnd || archiveIds.has(a.id) || hashes.has(a.archiveSha256))
      throw Error('Invalid, overlapping or duplicated archive lineage');
    archiveIds.add(a.id); hashes.add(a.archiveSha256); lastEnd = a.end;
  }
  if (Math.min(...plan.archiveLineage.map(a=>a.start)) >= plan.protocol.developmentEnd ||
      lastEnd < plan.protocol.holdoutEnd)
    throw Error('Archive lineage does not cover the frozen research period');
  for (const part of ['development','validation','holdout'] as const) {
    if (plan.eligible[part].some(id=>!nonblank(id)) ||
        new Set(plan.eligible[part]).size !== plan.eligible[part].length)
      throw Error('Invalid or duplicate partition observation ID');
  }
  const allIds = [...plan.eligible.development,...plan.eligible.validation,...plan.eligible.holdout];
  if (new Set(allIds).size !== allIds.length) throw Error('Observation appears in multiple chronological partitions');
}

/**
 * Caller must supply exactly the DEVELOPMENT-eligible timing metadata from the
 * purged planner. No validation/holdout observations or outcomes are accepted.
 * An independently witnessed freeze must occur before anyone views evaluation
 * data; hashing a post-hoc schedule cannot establish that fact.
 */
export async function planFrozenWalkForward(
  plan: PurgedPlan, developmentObservations: readonly OutcomeTiming[], spec: FrozenForwardSpecification
): Promise<FrozenForwardReview> {
  checkPlan(plan);
  exact(spec, ['folds','embargoSeconds','minTrainingObservations','minTestingObservations'], 'forward specification');
  if (!Array.isArray(spec.folds) || spec.folds.length < 2 || spec.folds.length > 24 ||
      !epoch(spec.embargoSeconds) || spec.embargoSeconds > 30 * 86400 ||
      !Number.isSafeInteger(spec.minTrainingObservations) || spec.minTrainingObservations < 1 ||
      !Number.isSafeInteger(spec.minTestingObservations) || spec.minTestingObservations < 1)
    throw Error('Invalid predeclared fold count, embargo or minimum timing counts');
  if (!Array.isArray(developmentObservations) || developmentObservations.length > 250000 ||
      developmentObservations.length !== plan.eligible.development.length)
    throw Error('Complete development-only eligible timing metadata required');
  const byArchive = new Map(plan.archiveLineage.map(a=>[a.id,a]));
  const required = new Set(plan.eligible.development), seen = new Set<string>();
  const ordered = [...developmentObservations];
  for (const o of ordered) {
    exact(o, ['id','archiveId','featureStart','decisionAt','labelAvailableAt'], 'timing observation');
    const archive = byArchive.get(o.archiveId);
    if (!nonblank(o.id) || !required.has(o.id) || seen.has(o.id) || !archive ||
        ![o.featureStart,o.decisionAt,o.labelAvailableAt].every(epoch) ||
        o.featureStart < archive.start || o.featureStart > o.decisionAt ||
        o.decisionAt >= archive.end || o.decisionAt > o.labelAvailableAt ||
        o.labelAvailableAt >= archive.end ||
        o.decisionAt >= plan.protocol.developmentEnd ||
        o.labelAvailableAt >= plan.protocol.developmentEnd ||
        o.labelAvailableAt > plan.protocol.developmentEnd - plan.protocol.embargoSeconds)
      throw Error('Unknown, duplicate, future, noncausal or non-development observation');
    seen.add(o.id);
  }
  const archiveStart = Math.min(...plan.archiveLineage.map(a=>a.start));
  const windows: ForwardWindow[] = [];
  const foldIds = new Set<string>();
  for (const f of spec.folds) {
    exact(f, ['id','trainingStart','trainingEnd','testingStart','testingEnd'], 'forward fold');
    if (!ident(f.id) || foldIds.has(f.id) ||
        ![f.trainingStart,f.trainingEnd,f.testingStart,f.testingEnd].every(epoch) ||
        f.trainingStart < archiveStart ||
        !(f.trainingStart < f.trainingEnd && f.trainingEnd <= f.testingStart &&
          f.testingStart < f.testingEnd && f.testingEnd <= plan.protocol.developmentEnd) ||
        f.trainingEnd - f.trainingStart < 365 * 86400 ||
        f.testingEnd - f.testingStart < 30 * 86400 ||
        (windows.length > 0 && (
          f.trainingStart !== windows[0].trainingStart ||
          f.trainingEnd < windows.at(-1)!.testingEnd ||
          f.testingStart < windows.at(-1)!.testingEnd)))
      throw Error('Overlapping, nonexpanding, too-short or out-of-development forward fold');
    foldIds.add(f.id); windows.push({...f});
  }
  // Canonical hash is invariant to caller array ordering of source archives and
  // development observations. It is an IDENTIFIER, not a trusted time anchor.
  const lineage = [...plan.archiveLineage].sort((a,b)=>a.start-b.start || a.id.localeCompare(b.id))
    .map(a=>({id:a.id,archiveSha256:a.archiveSha256,start:a.start,end:a.end}));
  const source = {provider:plan.source.provider,instrument:plan.source.instrument,venue:plan.source.venue,
    priceSide:plan.source.priceSide,utcConvention:plan.source.utcConvention};
  const protocol = {developmentEnd:plan.protocol.developmentEnd,validationEnd:plan.protocol.validationEnd,
    holdoutEnd:plan.protocol.holdoutEnd,embargoSeconds:plan.protocol.embargoSeconds,
    strategyVersion:plan.protocol.strategyVersion,configSha256:plan.protocol.configSha256};
  const canonical = {schema:'frozen-walk-forward-v1',source,
    archiveLineage:lineage,protocol,
    specification:{folds:windows.map(f=>({id:f.id,trainingStart:f.trainingStart,trainingEnd:f.trainingEnd,
      testingStart:f.testingStart,testingEnd:f.testingEnd})),embargoSeconds:spec.embargoSeconds,
      minTrainingObservations:spec.minTrainingObservations,
      minTestingObservations:spec.minTestingObservations}};
  if (!globalThis.crypto?.subtle) throw Error('SHA-256 unavailable; fail closed');
  const bytes = await globalThis.crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(canonical)));
  const scheduleSha256 = [...new Uint8Array(bytes)].map(x=>x.toString(16).padStart(2,'0')).join('');
  ordered.sort((a,b)=>a.decisionAt-b.decisionAt || a.id.localeCompare(b.id));
  const reviews = windows.map(f=>{
    const train = ordered.filter(o=>o.decisionAt>=f.trainingStart && o.decisionAt<f.trainingEnd);
    const test = ordered.filter(o=>o.decisionAt>=f.testingStart && o.decisionAt<f.testingEnd);
    const trainIds = train.filter(o=>o.featureStart>=f.trainingStart &&
      o.labelAvailableAt<f.trainingEnd-spec.embargoSeconds).map(o=>o.id);
    const testIds = test.filter(o=>o.featureStart>=f.testingStart &&
      o.labelAvailableAt<f.testingEnd-spec.embargoSeconds).map(o=>o.id);
    return {id:f.id,trainingIds:trainIds,testingIds:testIds,
      trainingExcluded:train.length-trainIds.length,testingExcluded:test.length-testIds.length,
      status:trainIds.length>=spec.minTrainingObservations && testIds.length>=spec.minTestingObservations ?
        'TIMING_ONLY' as const : 'INSUFFICIENT_TIMING_COUNTS' as const};
  });
  return {schema:'frozen-walk-forward-v1',scheduleSha256,source:{...plan.source},folds:reviews,
    coverage:'UNVERIFIED_METADATA_ONLY',warnings:[
      'Only development timing metadata is examined; validation and final holdout outcomes remain inaccessible to this helper.',
      'Fold counts are timing records, not trade counts or independent observations. Training windows overlap and test windows do not.',
      'Schedule digest is not a trusted timestamp, source authentication, access-control proof, or preregistration evidence.',
      'No observed bid/ask spreads, slippage, CFD financing, margin, demo fills, strategy returns or profitability are measured.'
    ]};
}
