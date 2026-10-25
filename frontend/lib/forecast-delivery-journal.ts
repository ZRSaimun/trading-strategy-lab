/**
 * Pure, offline replay of self-attested forecast-review delivery events.
 * A caller must transactionally persist events BEFORE acting on them.
 * No notification transport, live feed, broker API, or actual delivery here.
 */
import type {ForecastReviewCandidate} from './forecast-review-outbox.ts';

export type DeliveryJournalEvent = {
  seq:number; at:number; id:string;
  action:'QUEUED'|'CLAIMED'|'ACK_RECORDED'|'RELEASED'|'CANCELLED';
  candidate?:ForecastReviewCandidate;
  attemptId?:string;
  receiptId?:string;
  reason?:string;
};
export type DeliveryJournalEntry = {
  id:string;
  status:'PENDING'|'IN_FLIGHT_NEEDS_RECONCILIATION'|'ACK_RECORDED_UNVERIFIED'|'CANCELLED';
  queuedAt:number;lastEventAt:number;attempts:number;
  activeAttemptId:string|null;receiptId:string|null;
};
export type DeliveryJournalReview = {
  mode:'UNVERIFIED_LOCAL_RESEARCH';live:false;transportConnected:false;
  entries:DeliveryJournalEntry[];
  counts:{pending:number;inFlight:number;ackRecorded:number;cancelled:number};
};
const epoch=(v:number)=>Number.isSafeInteger(v)&&v>=0;
const token=(v:unknown)=>typeof v==='string'&&v.length>0&&v.length<=256&&v.trim()===v;
const sourceKey=(v:ForecastReviewCandidate['identity'])=>JSON.stringify([
  v.instrument,v.provider,v.venue,v.sourceId,v.priceSide,v.seconds,
]);
function verifyCandidate(c:ForecastReviewCandidate,id:string,at:number):void{
  if(!c||c.id!==id||c.kind!=='FORECAST_CALIBRATION_REVIEW'||
     c.mode!=='UNVERIFIED_LOCAL_RESEARCH'||c.live!==false||
     c.delivery!=='NOT_CONNECTED'||c.execution!=='NONE'||c.quoteTimestamp!==null||
     !c.identity||![c.identity.instrument,c.identity.provider,c.identity.venue,c.identity.sourceId].every(token)||
     !['bid','ask','mid'].includes(c.identity.priceSide)||
     !epoch(c.identity.seconds)||c.identity.seconds<60||c.identity.seconds%60!==0||
     !token(c.modelVersion)||![1,3,12].includes(c.horizon)||
     !epoch(c.latestTargetClose)||c.latestTargetClose>at||
     !Number.isFinite(c.earlierBrier)||!Number.isFinite(c.recentBrier)||
     !Number.isFinite(c.deltaBrier)||c.earlierBrier<0||c.earlierBrier>1||
     c.recentBrier<0||c.recentBrier>1||
     Math.abs(c.recentBrier-c.earlierBrier-c.deltaBrier)>1e-10||
     !Array.isArray(c.reasons)||!c.reasons.length||!c.reasons.every(token)||
     id!==JSON.stringify([sourceKey(c.identity),c.modelVersion,c.horizon,c.latestTargetClose]))
    throw Error('Invalid or future-dated offline forecast review candidate');
}
/**
 * Replay only; journal atomicity, authentication, persistence, and transport
 * reconciliation are external requirements. An unacknowledged CLAIMED event
 * remains IN_FLIGHT_NEEDS_RECONCILIATION after restart: never auto-resend it.
 */
export function replayForecastDeliveryJournal(
  events:readonly DeliveryJournalEvent[],asOf:number,
):DeliveryJournalReview{
  if(!epoch(asOf)||events.length>50000)throw Error('Invalid journal replay bounds');
  const entries=new Map<string,DeliveryJournalEntry>();
  const attempts=new Map<string,Set<string>>();
  let lastAt=0;
  for(let i=0;i<events.length;i++){
    const e=events[i];
    if(!e||e.seq!==i+1||!epoch(e.at)||e.at<lastAt||e.at>asOf||
       !token(e.id)||!['QUEUED','CLAIMED','ACK_RECORDED','RELEASED','CANCELLED'].includes(e.action))
      throw Error('Malformed, missing, reordered, or future journal event');
    lastAt=e.at;
    const current=entries.get(e.id);
    if(e.action==='QUEUED'){
      if(current||e.attemptId!==undefined||e.receiptId!==undefined||e.reason!==undefined||!e.candidate)
        throw Error('Duplicate or malformed QUEUED event');
      verifyCandidate(e.candidate,e.id,e.at);
      entries.set(e.id,{id:e.id,status:'PENDING',queuedAt:e.at,lastEventAt:e.at,
        attempts:0,activeAttemptId:null,receiptId:null});
      attempts.set(e.id,new Set());
      continue;
    }
    if(!current||e.candidate!==undefined)throw Error('Unknown candidate or invalid event payload');
    if(e.action==='CLAIMED'){
      if(current.status!=='PENDING'||!token(e.attemptId)||e.receiptId!==undefined||e.reason!==undefined||
         attempts.get(e.id)!.has(e.attemptId!))throw Error('Unsafe or duplicate delivery claim');
      attempts.get(e.id)!.add(e.attemptId!);
      current.status='IN_FLIGHT_NEEDS_RECONCILIATION';
      current.activeAttemptId=e.attemptId!;
      current.attempts++;
    }else if(e.action==='ACK_RECORDED'){
      if(current.status!=='IN_FLIGHT_NEEDS_RECONCILIATION'||e.attemptId!==current.activeAttemptId||
         !token(e.receiptId)||e.reason!==undefined)
        throw Error('Unmatched or unverified delivery receipt event');
      current.status='ACK_RECORDED_UNVERIFIED';
      current.receiptId=e.receiptId!;
      current.activeAttemptId=null;
    }else if(e.action==='RELEASED'){
      if(current.status!=='IN_FLIGHT_NEEDS_RECONCILIATION'||e.attemptId!==current.activeAttemptId||
         e.receiptId!==undefined||!token(e.reason))
        throw Error('Unmatched delivery release');
      current.status='PENDING';
      current.activeAttemptId=null;
    }else{
      if(current.status!=='PENDING'||e.attemptId!==undefined||e.receiptId!==undefined||!token(e.reason))
        throw Error('Cannot cancel claimed or acknowledged delivery');
      current.status='CANCELLED';
    }
    current.lastEventAt=e.at;
  }
  const rows=Array.from(entries.values(),e=>({...e}));
  return {mode:'UNVERIFIED_LOCAL_RESEARCH',live:false,transportConnected:false,
    entries:rows,counts:{
      pending:rows.filter(e=>e.status==='PENDING').length,
      inFlight:rows.filter(e=>e.status==='IN_FLIGHT_NEEDS_RECONCILIATION').length,
      ackRecorded:rows.filter(e=>e.status==='ACK_RECORDED_UNVERIFIED').length,
      cancelled:rows.filter(e=>e.status==='CANCELLED').length,
    }};
}
