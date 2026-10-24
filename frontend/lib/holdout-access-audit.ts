/** Offline, self-attested holdout commitment and hash-chained access receipts.
 * A locally rewriteable chain is NOT trusted time-stamping, access control,
 * source authentication, or proof that outcomes were never inspected.
 * No market prices, P&L, broker access, or orders are accepted here.
 */
import {planPurgedHoldout, type ArchiveLineage, type HoldoutProtocol} from './purged-holdout-plan.ts';

export type HoldoutCommitment = {
  schema: 'holdout-commitment-v1';
  operatorId: string;
  frozenAt: number;
  protocol: HoldoutProtocol;
  archives: ArchiveLineage[];
  digest: string;
};
export type HoldoutAction = 'VALIDATION_ACCESS' | 'HOLDOUT_ACCESS' | 'HOLDOUT_EVALUATION' | 'PROTOCOL_CHANGED';
export type HoldoutAccessEvent = {
  eventId: string;
  occurredAt: number;
  action: HoldoutAction;
  archiveId: string | null;
};
export type HoldoutAuditEntry = HoldoutAccessEvent & {
  sequence: number;
  commitmentDigest: string;
  previousDigest: string;
  digest: string;
};
export type HoldoutAuditReview = {
  eventCount: number;
  integrity: 'HASH_CHAIN_VALID';
  recordedStatus: 'NO_CONTAMINATION_RECORDED' | 'CONTAMINATION_RECORDED';
  findings: string[];
};

const SHA = /^[a-f0-9]{64}$/;
const eventKeys = ['eventId', 'occurredAt', 'action', 'archiveId'];
const entryKeys = [...eventKeys, 'sequence', 'commitmentDigest', 'previousDigest', 'digest'];
const commitmentKeys = ['schema', 'operatorId', 'frozenAt', 'protocol', 'archives', 'digest'];
const epoch = (n: unknown): n is number => typeof n === 'number' && Number.isSafeInteger(n) && n >= 0;
const identifier = (n: unknown): n is string => typeof n === 'string' && /^[A-Za-z0-9._:@/-]{1,100}$/.test(n);
function exactKeys(value: unknown, allowed: string[], kind: string): void {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      Object.keys(value).length !== allowed.length ||
      Object.keys(value).some(k => !allowed.includes(k)))
    throw Error('Invalid ' + kind + ' schema: no outcomes or additional fields permitted');
}
async function digest(value: unknown): Promise<string> {
  if (!globalThis.crypto?.subtle) throw Error('SHA-256 WebCrypto unavailable; fail closed');
  const hash = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(value)));
  return [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2, '0')).join('');
}
function canonicalProtocol(p: HoldoutProtocol): HoldoutProtocol {
  return {developmentEnd:p.developmentEnd,validationEnd:p.validationEnd,holdoutEnd:p.holdoutEnd,
    embargoSeconds:p.embargoSeconds,strategyVersion:p.strategyVersion,configSha256:p.configSha256};
}
function canonicalArchives(archives: ArchiveLineage[]): ArchiveLineage[] {
  return [...archives].sort((a,b) => a.start-b.start || a.id.localeCompare(b.id)).map(a => ({
    id:a.id,provider:a.provider,instrument:a.instrument,venue:a.venue,priceSide:a.priceSide,
    utcConvention:a.utcConvention,archiveSha256:a.archiveSha256,start:a.start,end:a.end
  }));
}

/** This timestamp is a caller assertion, NOT an independently attested clock. */
export async function createHoldoutCommitment(
  archives: ArchiveLineage[], protocol: HoldoutProtocol, operatorId: string, frozenAt: number
): Promise<HoldoutCommitment> {
  if (!identifier(operatorId) || !epoch(frozenAt) || !protocol || frozenAt >= protocol.validationEnd)
    throw Error('Commitment requires a valid operator and a self-asserted freeze before holdout begins');
  // The existing planner validates source family, coverage, archive fingerprints,
  // protocol fields and chronology. No observations or outcomes are supplied.
  planPurgedHoldout(archives, [], protocol);
  const body = {schema:'holdout-commitment-v1' as const,operatorId,frozenAt,
    protocol:canonicalProtocol(protocol),archives:canonicalArchives(archives)};
  return {...body,digest:await digest(body)};
}
async function validateCommitment(c: HoldoutCommitment): Promise<void> {
  exactKeys(c,commitmentKeys,'commitment');
  if (c.schema !== 'holdout-commitment-v1' || !SHA.test(c.digest))
    throw Error('Unsupported or malformed holdout commitment');
  const recalculated = await createHoldoutCommitment(c.archives,c.protocol,c.operatorId,c.frozenAt);
  if (recalculated.digest !== c.digest) throw Error('Holdout commitment digest mismatch');
}
function validateEvent(event: HoldoutAccessEvent, c: HoldoutCommitment): void {
  exactKeys(event,eventKeys,'access event');
  if (!identifier(event.eventId) || !epoch(event.occurredAt) || event.occurredAt < c.frozenAt ||
      !['VALIDATION_ACCESS','HOLDOUT_ACCESS','HOLDOUT_EVALUATION','PROTOCOL_CHANGED'].includes(event.action))
    throw Error('Invalid access event ID, timestamp or action');
  if (event.action === 'PROTOCOL_CHANGED') {
    if (event.archiveId !== null) throw Error('Protocol change must not name an archive');
  } else if (!identifier(event.archiveId) || !c.archives.some(a => a.id === event.archiveId)) {
    throw Error('Access event must reference an archive in the frozen source lineage');
  }
}
function entryBody(entry: Omit<HoldoutAuditEntry,'digest'>) {
  return {eventId:entry.eventId,occurredAt:entry.occurredAt,action:entry.action,
    archiveId:entry.archiveId,sequence:entry.sequence,
    commitmentDigest:entry.commitmentDigest,previousDigest:entry.previousDigest};
}

/** Verify every link; a valid chain is still rewriteable without external anchoring. */
export async function verifyHoldoutAudit(c: HoldoutCommitment, entries: HoldoutAuditEntry[]): Promise<HoldoutAuditReview> {
  await validateCommitment(c);
  if (!Array.isArray(entries) || entries.length > 100000)
    throw Error('Invalid or excessive audit entries');
  const seen = new Set<string>();
  let previous = c.digest, lastAt = c.frozenAt;
  const findings: string[] = [];
  for (let i=0;i<entries.length;i++) {
    const entry = entries[i];
    exactKeys(entry,entryKeys,'audit entry');
    validateEvent({eventId:entry.eventId,occurredAt:entry.occurredAt,
      action:entry.action,archiveId:entry.archiveId},c);
    if (entry.sequence !== i+1 || entry.commitmentDigest !== c.digest ||
        entry.previousDigest !== previous || !SHA.test(entry.digest) ||
        entry.occurredAt < lastAt || seen.has(entry.eventId))
      throw Error('Broken audit sequence, chronology, commitment, or hash-chain link');
    const expected = await digest(entryBody(entry));
    if (expected !== entry.digest) throw Error('Audit event digest mismatch; possible tampering');
    if ((entry.action === 'HOLDOUT_ACCESS' || entry.action === 'HOLDOUT_EVALUATION') &&
        entry.occurredAt < c.protocol.validationEnd)
      findings.push('Recorded holdout access before preregistered validation end');
    if (entry.action === 'PROTOCOL_CHANGED')
      findings.push('Recorded protocol revision after freeze; original holdout no longer untouched');
    seen.add(entry.eventId);
    previous = entry.digest;
    lastAt = entry.occurredAt;
  }
  if (!entries.length) findings.push('No access events recorded; absence of evidence is not proof of no access');
  findings.push('All timestamps and accesses are self-reported; externally anchor the commitment and every audit head in trusted append-only storage');
  return {eventCount:entries.length,integrity:'HASH_CHAIN_VALID',
    recordedStatus:findings.some(f=>f.startsWith('Recorded'))?'CONTAMINATION_RECORDED':'NO_CONTAMINATION_RECORDED',
    findings:[...new Set(findings)]};
}

/** Returns a new array; caller must persist it atomically and externally anchor its head. */
export async function appendHoldoutAuditEvent(
  c: HoldoutCommitment, entries: HoldoutAuditEntry[], event: HoldoutAccessEvent
): Promise<HoldoutAuditEntry[]> {
  await verifyHoldoutAudit(c,entries);
  validateEvent(event,c);
  if (entries.some(e => e.eventId === event.eventId) ||
      (entries.length && event.occurredAt < entries[entries.length-1].occurredAt))
    throw Error('Duplicate or backdated access event');
  const body = entryBody({...event,sequence:entries.length+1,commitmentDigest:c.digest,
    previousDigest:entries.at(-1)?.digest ?? c.digest});
  return [...entries,{...body,digest:await digest(body)}];
}
