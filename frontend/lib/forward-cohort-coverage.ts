/**
 * Fail-closed, OFFLINE forecast cohort completeness audit.
 * The caller declares the intended UTC issue slots; these are not proof that
 * the slots were actually attempted, received, or durably persisted.
 * This module does not score accuracy or enable alert/broker execution.
 */
import type {FeedIdentity,ForecastRecord} from './forward-forecast-ledger.ts';

export type CohortCoverage = {
  mode:'UNVERIFIED_LOCAL_RESEARCH';live:false;authenticated:false;persisted:false;
  alertsEnabled:false;execution:'NONE';
  status:'NOT_YET_MATURE'|'COMPLETE_DESCRIPTIVE'|'INCOMPLETE';
  modelVersion:string;horizon:1|3|12;expectedStart:number;expectedEnd:number;
  asOf:number;expectedSlots:number;maturedSlots:number;
  timelySettled:number;lateSettled:number;voidGap:number;
  overduePending:number;immaturePending:number;
  missingMatured:number;missingImmature:number;
  matureTimelyCoverage:number|null;
  // Missing issues and voided outcomes are NOT forecast errors. Coverage is
  // about observation/issuance quality, not directional accuracy or P&L.
  reasons:string[];
};
const epoch=(n:number)=>Number.isSafeInteger(n)&&n>=0;
const key=(x:FeedIdentity)=>JSON.stringify([x.instrument,x.provider,x.venue,x.sourceId,x.priceSide,x.seconds]);
const idOk=(s:string)=>typeof s==='string'&&s.trim().length>0&&s.length<=160;
/**
 * Check a bounded, predeclared cohort of fixed-phase, non-overlapping forecasts.
 * Each expectedStart/expectedEnd is a BASE candle start (inclusive). A record
 * outside the declared cohort for the chosen model/horizon is rejected, rather
 * than quietly discarded. Mixed feeds always fail closed.
 */
export function auditForwardCohortCoverage(
  records:readonly ForecastRecord[],identity:FeedIdentity,modelVersion:string,
  horizon:1|3|12,expectedStart:number,expectedEnd:number,asOf:number,
  maxSettlementLagSeconds=120,
):CohortCoverage{
  if(!identity||!idOk(identity.instrument)||!idOk(identity.provider)||
     !idOk(identity.venue)||!idOk(identity.sourceId)||
     !['bid','ask','mid'].includes(identity.priceSide)||
     !Number.isSafeInteger(identity.seconds)||identity.seconds<60||identity.seconds>86400||
     identity.seconds%60!==0||!idOk(modelVersion)||![1,3,12].includes(horizon)||
     !epoch(expectedStart)||!epoch(expectedEnd)||!epoch(asOf)||
     !Number.isSafeInteger(maxSettlementLagSeconds)||maxSettlementLagSeconds<0||
     maxSettlementLagSeconds>3600||!Array.isArray(records)||records.length>50000)
    throw Error('Invalid cohort coverage configuration');
  const stride=identity.seconds*horizon;
  if(!Number.isSafeInteger(stride)||expectedEnd<expectedStart||
     expectedStart%stride!==0||expectedEnd%stride!==0||
     (expectedEnd-expectedStart)%stride!==0||
     expectedStart+identity.seconds>asOf||
     !Number.isSafeInteger(expectedEnd+(horizon+1)*identity.seconds))
    throw Error('Invalid aligned or future cohort bounds');
  const expectedSlots=(expectedEnd-expectedStart)/stride+1;
  if(!Number.isSafeInteger(expectedSlots)||expectedSlots<1||expectedSlots>5000)
    throw Error('Cohort exceeds bounded audit capacity');
  const selected=new Map<number,ForecastRecord>();
  const source=key(identity);
  for(const r of records){
    if(!r||key(r)!==source)throw Error('Mixed or malformed source identity');
    if(r.modelVersion!==modelVersion||r.horizon!==horizon)continue;
    const baseClose=r.baseStart+identity.seconds;
    const nextClose=baseClose+identity.seconds;
    const targetStart=r.baseStart+horizon*identity.seconds;
    const targetClose=targetStart+identity.seconds;
    if(!idOk(r.id)||!epoch(r.baseStart)||r.baseStart<expectedStart||
       r.baseStart>expectedEnd||r.baseStart%stride!==0||
       !epoch(baseClose)||!epoch(nextClose)||!epoch(targetClose)||
       r.targetStart!==targetStart||!epoch(r.issuedAt)||
       r.issuedAt<baseClose||r.issuedAt>=nextClose||r.issuedAt>asOf||
       !Number.isFinite(r.baseClose)||r.baseClose<=0||
       !Number.isFinite(r.probability)||r.probability<=0||r.probability>=1||
       !['PENDING','SETTLED','VOID_GAP'].includes(r.status)||
       (r.status==='PENDING'&&(r.resolvedAt!==null||r.outcomeUp!==null||r.reason!==null))||
       (r.status==='SETTLED'&&(!epoch(r.resolvedAt!)||r.resolvedAt!<targetClose||
          r.resolvedAt!<r.issuedAt||r.resolvedAt!>asOf||
          typeof r.outcomeUp!=='boolean'||r.reason!==null))||
       (r.status==='VOID_GAP'&&(!epoch(r.resolvedAt!)||r.resolvedAt!<r.issuedAt||
          r.resolvedAt!>asOf||r.outcomeUp!==null||!idOk(r.reason!))))
      throw Error('Malformed, retroactive or future-dated cohort record');
    if(selected.has(r.baseStart))throw Error('Duplicate model/horizon cohort slot');
    selected.set(r.baseStart,r);
  }
  let maturedSlots=0,timelySettled=0,lateSettled=0,voidGap=0;
  let overduePending=0,immaturePending=0,missingMatured=0,missingImmature=0;
  for(let slot=expectedStart;slot<=expectedEnd;slot+=stride){
    const targetClose=slot+(horizon+1)*identity.seconds;
    const matured=targetClose<=asOf;
    if(matured)maturedSlots++;
    const r=selected.get(slot);
    if(!r){if(matured)missingMatured++;else missingImmature++;continue;}
    if(r.status==='VOID_GAP'){voidGap++;continue;}
    if(r.status==='PENDING'){if(matured)overduePending++;else immaturePending++;continue;}
    if(r.resolvedAt!-targetClose<=maxSettlementLagSeconds)timelySettled++;
    else lateSettled++;
  }
  const matureTimelyCoverage=maturedSlots?timelySettled/maturedSlots:null;
  const reasons:string[]=[];
  if(missingMatured||missingImmature)reasons.push('Declared issuance slots are absent; missing records cannot be assumed to be failed forecasts.');
  if(voidGap)reasons.push('Gap-voided outcomes reduce scoreable cohort coverage.');
  if(overduePending)reasons.push('Matured target candles have unresolved forecast records.');
  if(lateSettled)reasons.push('Settlements exceed the declared receipt-lag tolerance.');
  if(immaturePending)reasons.push('Some target candles have not yet closed.');
  const complete=maturedSlots===expectedSlots&&timelySettled===expectedSlots;
  const status:CohortCoverage['status']=complete?'COMPLETE_DESCRIPTIVE':
    maturedSlots===0&&missingMatured===0&&missingImmature===0&&voidGap===0&&
    lateSettled===0?'NOT_YET_MATURE':'INCOMPLETE';
  return {mode:'UNVERIFIED_LOCAL_RESEARCH',live:false,authenticated:false,
    persisted:false,alertsEnabled:false,execution:'NONE',status,modelVersion,horizon,
    expectedStart,expectedEnd,asOf,expectedSlots,maturedSlots,timelySettled,
    lateSettled,voidGap,overduePending,immaturePending,missingMatured,
    missingImmature,matureTimelyCoverage,reasons};
}
