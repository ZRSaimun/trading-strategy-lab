/**
 * Read-only, offline delivery-claim preflight. Never sends, claims, or
 * authenticates an alert. Replay is self-attested and NOT a transactional lock.
 */
import {replayForecastDeliveryJournal} from './forecast-delivery-journal.ts';
import type {DeliveryJournalEvent} from './forecast-delivery-journal.ts';
import type {ForecastReviewCandidate} from './forecast-review-outbox.ts';

export type ForecastClaimPolicy = {
  maxCandidateAgeSeconds:number;
  retryCooldownSeconds:number;
  maxAttempts:number;
};
export type ForecastClaimAssessment = {
  id:string;
  decision:'REHEARSAL_ONLY'|'BLOCKED';
  reason:'PENDING_OFFLINE_ONLY'|'EXPIRED'|'RETRY_COOLDOWN'|'ATTEMPTS_EXHAUSTED'|
    'NEEDS_RECONCILIATION'|'ACK_RECORDED_UNVERIFIED'|'CANCELLED';
  attempts:number;
  candidateTargetClose:number;
};
export type ForecastClaimPreflight = {
  mode:'UNVERIFIED_LOCAL_RESEARCH';
  live:false;
  transportConnected:false;
  claimIsAtomic:false;
  assessments:ForecastClaimAssessment[];
};
const epoch=(v:number)=>Number.isSafeInteger(v)&&v>=0;
const positive=(v:number)=>Number.isSafeInteger(v)&&v>0;

/**
 * An explicit asOf (seconds) is supplied by the caller, not a trusted server
 * receipt clock. "REHEARSAL_ONLY" is NOT permission to deliver: only a
 * future authenticated, transactional worker may make a durable claim.
 */
export function preflightForecastReviewClaims(
  events:readonly DeliveryJournalEvent[],asOf:number,policy:ForecastClaimPolicy,
):ForecastClaimPreflight{
  if(!epoch(asOf)||!policy||!positive(policy.maxCandidateAgeSeconds)||
     policy.maxCandidateAgeSeconds>30*86400||
     !epoch(policy.retryCooldownSeconds)||policy.retryCooldownSeconds>7*86400||
     !positive(policy.maxAttempts)||policy.maxAttempts>10)
    throw Error('Invalid offline claim preflight policy');
  const replay=replayForecastDeliveryJournal(events,asOf);
  const candidates=new Map<string,ForecastReviewCandidate>();
  for(const event of events){
    if(event.action==='QUEUED')candidates.set(event.id,event.candidate!);
  }
  const assessments:ForecastClaimAssessment[]=replay.entries.map(entry=>{
    const candidate=candidates.get(entry.id);
    if(!candidate)throw Error('Missing replayed review candidate');
    let reason:ForecastClaimAssessment['reason'];
    if(entry.status==='IN_FLIGHT_NEEDS_RECONCILIATION')
      reason='NEEDS_RECONCILIATION';
    else if(entry.status==='ACK_RECORDED_UNVERIFIED')
      reason='ACK_RECORDED_UNVERIFIED';
    else if(entry.status==='CANCELLED')
      reason='CANCELLED';
    else if(asOf-candidate.latestTargetClose>policy.maxCandidateAgeSeconds)
      reason='EXPIRED';
    else if(entry.attempts>=policy.maxAttempts)
      reason='ATTEMPTS_EXHAUSTED';
    else if(entry.attempts>0&&asOf-entry.lastEventAt<policy.retryCooldownSeconds)
      reason='RETRY_COOLDOWN';
    else reason='PENDING_OFFLINE_ONLY';
    return {
      id:entry.id,
      decision:reason==='PENDING_OFFLINE_ONLY'?'REHEARSAL_ONLY':'BLOCKED',
      reason,attempts:entry.attempts,candidateTargetClose:candidate.latestTargetClose,
    };
  });
  return {mode:'UNVERIFIED_LOCAL_RESEARCH',live:false,transportConnected:false,
    claimIsAtomic:false,assessments};
}
