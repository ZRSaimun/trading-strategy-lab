/**
 * Offline, deterministic review candidates for a source-isolated forward ledger.
 * This does NOT authenticate candles, deliver notifications, or place orders.
 */
import type {ForecastRecord,FeedIdentity} from './forward-forecast-ledger.ts';
export type ForecastReview={
 status:'INSUFFICIENT'|'NO_FLAG'|'REVIEW';modelVersion:string;horizon:1|3|12;
 selected:number;required:number;earlierBrier:number|null;recentBrier:number|null;
 deltaBrier:number|null;latestTargetClose:number|null;reasons:string[];
};
export type ForecastReviewCandidate={
 id:string;kind:'FORECAST_CALIBRATION_REVIEW';mode:'UNVERIFIED_LOCAL_RESEARCH';
 live:false;delivery:'NOT_CONNECTED';execution:'NONE';quoteTimestamp:null;
 identity:FeedIdentity;modelVersion:string;horizon:1|3|12;
 latestTargetClose:number;earlierBrier:number;recentBrier:number;deltaBrier:number;reasons:string[];
};
const epoch=(v:number)=>Number.isSafeInteger(v)&&v>=0;
const sourceKey=(v:FeedIdentity)=>JSON.stringify([v.instrument,v.provider,v.venue,v.sourceId,v.priceSide,v.seconds]);
const mean=(xs:ForecastRecord[])=>xs.reduce((sum,r)=>sum+(r.probability-Number(r.outcomeUp))**2,0)/xs.length;
/**
 * Use a fixed UTC-aligned phase and one settled outcome per horizon, rather
 * than treating overlapping h>1 outcomes as independent samples. A missing
 * aligned forecast or voided interval prevents a two-window comparison.
 */
export function reviewForwardCalibration(records:readonly ForecastRecord[],identity:FeedIdentity,modelVersion:string,horizon:1|3|12,window=20):ForecastReview{
 if(!modelVersion.trim()||modelVersion.length>80||![1,3,12].includes(horizon)||
    !Number.isSafeInteger(identity.seconds)||identity.seconds<60||identity.seconds%60!==0||
    !Number.isSafeInteger(window)||window<10||window>500||records.length>50000)
  throw Error('Invalid forecast review configuration');
 const expected=sourceKey(identity),matching:ForecastRecord[]=[];
 const bases=new Set<number>();
 for(const r of records){
  if(sourceKey(r)!==expected)throw Error('Mixed or mismatched forecast source');
  if(r.modelVersion!==modelVersion||r.horizon!==horizon)continue;
  if(!epoch(r.baseStart)||r.baseStart%identity.seconds!==0||
     !epoch(r.targetStart)||r.targetStart!==r.baseStart+horizon*identity.seconds||
     !epoch(r.issuedAt)||r.issuedAt<r.baseStart+identity.seconds||r.issuedAt>=r.baseStart+2*identity.seconds||!Number.isFinite(r.probability)||r.probability<=0||r.probability>=1||
     !['PENDING','SETTLED','VOID_GAP'].includes(r.status)||
     (r.status==='SETTLED'&&(!epoch(r.resolvedAt!)||r.resolvedAt!<r.targetStart+identity.seconds||typeof r.outcomeUp!=='boolean'))||
     (r.status!=='SETTLED'&&r.outcomeUp!==null))
   throw Error('Malformed forward forecast record');
  if(bases.has(r.baseStart))throw Error('Duplicate model/horizon base candle');
  bases.add(r.baseStart);
  if(r.baseStart/identity.seconds%horizon===0)matching.push(r);
 }
 matching.sort((a,b)=>a.baseStart-b.baseStart);
 const required=2*window;
 const insufficient=(reason:string):ForecastReview=>({status:'INSUFFICIENT',modelVersion,horizon,
  selected:matching.length,required,earlierBrier:null,recentBrier:null,
  deltaBrier:null,latestTargetClose:null,reasons:[reason]});
 if(matching.length<required)return insufficient('Insufficient UTC-phase-aligned forward forecasts.');
 const selected=matching.slice(-required);
 for(let i=0;i<selected.length;i++){
  if(selected[i].status!=='SETTLED')return insufficient('Pending or gap-voided outcome within the comparison windows.');
  if(i&&selected[i].baseStart-selected[i-1].baseStart!==horizon*identity.seconds)
   return insufficient('Non-contiguous non-overlapping outcome windows.');
 }
 const earlierBrier=mean(selected.slice(0,window));
 const recentBrier=mean(selected.slice(window));
 const deltaBrier=recentBrier-earlierBrier;
 const reasons:string[]=[];
 if(deltaBrier>=0.02)reasons.push('Recent Brier loss deteriorated by at least 0.02.');
 if(recentBrier>0.25)reasons.push('Recent Brier loss exceeds the fixed 50% baseline.');
 return {status:reasons.length?'REVIEW':'NO_FLAG',modelVersion,horizon,
  selected:required,required,earlierBrier,recentBrier,deltaBrier,
  latestTargetClose:selected.at(-1)!.targetStart+identity.seconds,reasons};
}
/** A bounded, in-memory idempotency guard; not a durable notification queue. */
export class ForecastReviewOutbox{
 private readonly seen=new Set<string>();
 private readonly identity:FeedIdentity;
 private readonly modelVersion:string;
 private readonly horizon:1|3|12;
 private readonly window:number;
 constructor(identity:FeedIdentity,modelVersion:string,horizon:1|3|12,window=20){
  this.identity={...identity};this.modelVersion=modelVersion;this.horizon=horizon;this.window=window;
 }
 evaluate(records:readonly ForecastRecord[]):ForecastReviewCandidate[]{
  const review=reviewForwardCalibration(records,this.identity,this.modelVersion,this.horizon,this.window);
  if(review.status!=='REVIEW'||review.latestTargetClose===null||review.earlierBrier===null||
     review.recentBrier===null||review.deltaBrier===null)return [];
  const id=JSON.stringify([sourceKey(this.identity),this.modelVersion,this.horizon,review.latestTargetClose]);
  if(this.seen.has(id))return [];
  if(this.seen.size>=10000)throw Error('In-memory review deduplication capacity exhausted');
  this.seen.add(id);
  return [{id,kind:'FORECAST_CALIBRATION_REVIEW',mode:'UNVERIFIED_LOCAL_RESEARCH',
   live:false,delivery:'NOT_CONNECTED',execution:'NONE',quoteTimestamp:null,
   identity:{...this.identity},modelVersion:this.modelVersion,horizon:this.horizon,
   latestTargetClose:review.latestTargetClose,earlierBrier:review.earlierBrier,
   recentBrier:review.recentBrier,deltaBrier:review.deltaBrier,reasons:[...review.reasons]}];
 }
}
