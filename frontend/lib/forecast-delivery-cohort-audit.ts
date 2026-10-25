/**
 * Offline completeness audit for a separately declared cohort of forecast
 * review candidates. It cannot prove that the supplied cohort is complete,
 * authenticate clocks/receipts, or deliver an alert.
 */
import {replayForecastDeliveryJournal} from './forecast-delivery-journal.ts';
import type {DeliveryJournalEvent,DeliveryJournalEntry} from './forecast-delivery-journal.ts';

export type DeclaredReviewCandidate={id:string;latestTargetClose:number};
export type DeliveryCohortPolicy={maxQueueLagSeconds:number;maxResolutionLagSeconds:number};
export type DeliveryCohortRow={
 id:string;latestTargetClose:number;queuedAt:number|null;queueLagSeconds:number|null;
 status:DeliveryJournalEntry['status']|'MISSING_QUEUE';
 lateQueue:boolean;overdueWithoutSelfAck:boolean;
};
export type DeliveryCohortAudit={
 mode:'UNVERIFIED_LOCAL_RESEARCH';live:false;transportConnected:false;
 independentlyVerifiedDelivery:false;cohortAuthenticated:false;
 expected:number;queued:number;missing:number;lateQueued:number;
 pending:number;inFlight:number;selfAttestedAck:number;cancelled:number;
 overdueWithoutSelfAck:number;
 queueCoverage:number|null;selfAttestedAckCoverage:number|null;
 rows:DeliveryCohortRow[];
};
const epoch=(v:number)=>Number.isSafeInteger(v)&&v>=0;
const token=(v:unknown)=>typeof v==='string'&&v.length>0&&v.length<=256&&v.trim()===v;
const positiveBound=(v:number)=>Number.isSafeInteger(v)&&v>0&&v<=7*86400;
/**
 * Validate the canonical source/model/horizon ID emitted by the existing
 * review outbox; a string-shaped ID is not proof of source authenticity.
 */
function parseDeclared(candidate:DeclaredReviewCandidate):string{
 if(!candidate||!token(candidate.id)||!epoch(candidate.latestTargetClose))
  throw Error('Invalid declared candidate');
 let outer:unknown,source:unknown;
 try{
  outer=JSON.parse(candidate.id);
  if(!Array.isArray(outer)||outer.length!==4||typeof outer[0]!=='string')
   throw Error('Bad review ID');
  source=JSON.parse(outer[0]);
 }catch{throw Error('Invalid canonical review candidate ID');}
 if(!Array.isArray(source)||source.length!==6||
    !source.slice(0,4).every(token)||!['bid','ask','mid'].includes(source[4])||
    !epoch(source[5])||source[5]<60||source[5]%60!==0||
    !token(outer[1])||![1,3,12].includes(outer[2])||
    outer[3]!==candidate.latestTargetClose||
    candidate.latestTargetClose%source[5]!==0||
    candidate.id!==JSON.stringify(outer)||outer[0]!==JSON.stringify(source))
  throw Error('Malformed source, model, horizon, or target-close identity');
 return JSON.stringify(outer.slice(0,3));
}
/**
 * Requires an externally predeclared, ordered candidate cohort. Missing
 * records remain in the denominator. An ACK is self-attested, never verified
 * external delivery. No sending, claiming, storage, or broker action occurs.
 */
export function auditForecastDeliveryCohort(
 declared:readonly DeclaredReviewCandidate[],
 events:readonly DeliveryJournalEvent[],asOf:number,policy:DeliveryCohortPolicy,
):DeliveryCohortAudit{
 if(!epoch(asOf)||!policy||!positiveBound(policy.maxQueueLagSeconds)||
    !positiveBound(policy.maxResolutionLagSeconds)||declared.length>50000)
  throw Error('Invalid offline cohort audit bounds');
 const ids=new Set<string>();
 let prefix:string|null=null,lastClose=-1;
 for(const candidate of declared){
  const currentPrefix=parseDeclared(candidate);
  if(prefix!==null&&currentPrefix!==prefix)
   throw Error('Mixed source, model, or horizon in declared cohort');
  if(ids.has(candidate.id)||candidate.latestTargetClose<=lastClose||
     candidate.latestTargetClose>asOf)
   throw Error('Duplicate, unordered, or future declared candidate');
  prefix=currentPrefix;lastClose=candidate.latestTargetClose;ids.add(candidate.id);
 }
 const replay=replayForecastDeliveryJournal(events,asOf);
 const queued=new Map<string,DeliveryJournalEntry>();
 const receipts=new Set<string>();
 for(const entry of replay.entries){
  if(!ids.has(entry.id))throw Error('Undeclared candidate queued in journal');
  queued.set(entry.id,entry);
  if(entry.receiptId!==null){
   if(receipts.has(entry.receiptId))throw Error('Receipt ID reused across candidates');
   receipts.add(entry.receiptId);
  }
 }
 // Replay validates each QUEUED candidate. Also bind its declared target close
 // to the independently supplied cohort record, not only its opaque ID.
 const targets=new Map(declared.map(c=>[c.id,c.latestTargetClose]));
 for(const event of events){
  if(event.action==='QUEUED'&&event.candidate?.latestTargetClose!==targets.get(event.id))
   throw Error('Declared target close differs from journal candidate');
 }
 const rows:DeliveryCohortRow[]=declared.map(c=>{
  const entry=queued.get(c.id);
  const lag=entry?entry.queuedAt-c.latestTargetClose:null;
  const status=entry?.status??'MISSING_QUEUE';
  return {id:c.id,latestTargetClose:c.latestTargetClose,
   queuedAt:entry?.queuedAt??null,queueLagSeconds:lag,status,
   lateQueue:lag!==null&&lag>policy.maxQueueLagSeconds,
   overdueWithoutSelfAck:status!=='ACK_RECORDED_UNVERIFIED'&&
    asOf-c.latestTargetClose>policy.maxResolutionLagSeconds};
 });
 const count=(fn:(r:DeliveryCohortRow)=>boolean)=>rows.filter(fn).length;
 const queuedCount=count(r=>r.status!=='MISSING_QUEUE');
 const selfAttestedAck=count(r=>r.status==='ACK_RECORDED_UNVERIFIED');
 return {mode:'UNVERIFIED_LOCAL_RESEARCH',live:false,transportConnected:false,
  independentlyVerifiedDelivery:false,cohortAuthenticated:false,
  expected:rows.length,queued:queuedCount,missing:rows.length-queuedCount,
  lateQueued:count(r=>r.lateQueue),pending:count(r=>r.status==='PENDING'),
  inFlight:count(r=>r.status==='IN_FLIGHT_NEEDS_RECONCILIATION'),
  selfAttestedAck,cancelled:count(r=>r.status==='CANCELLED'),
  overdueWithoutSelfAck:count(r=>r.overdueWithoutSelfAck),
  queueCoverage:rows.length?queuedCount/rows.length:null,
  selfAttestedAckCoverage:rows.length?selfAttestedAck/rows.length:null,
  rows};
}
