/**
 * Offline, source-isolated two-window calibration deterioration audit.
 * Thresholds are descriptive review triggers, not significance tests or
 * permission to deliver alerts, trade, or infer forward profitability.
 */
import {evaluateForwardReliability} from './forward-reliability.ts';
import type {FeedIdentity,ForecastRecord} from './forward-forecast-ledger.ts';

export type ForecastCalibrationDrift={
  mode:'UNVERIFIED_LOCAL_RESEARCH';live:false;authenticated:false;
  persisted:false;alertsEnabled:false;execution:'NONE';
  status:'INSUFFICIENT'|'REPORT';
  review:'NONE'|'CALIBRATION_AND_LOSS_REVIEW'|'LOSS_REVIEW'|'NO_THRESHOLD_CROSSING';
  reason:string|null;modelVersion:string;horizon:1|3|12;
  requiredPerWindow:number;earlierCount:number;recentCount:number;
  earlierBrier:number|null;recentBrier:number|null;deltaBrier:number|null;
  earlierECE:number|null;recentECE:number|null;deltaECE:number|null;
  earlierLogLoss:number|null;recentLogLoss:number|null;
  earlierLastTargetClose:number|null;recentLastTargetClose:number|null;
  // Fixed, descriptive thresholds; no estimated type-I error or independence claim.
  brierDeteriorationThreshold:0.02;eceDeteriorationThreshold:0.05;
};
const epoch=(x:number)=>Number.isSafeInteger(x)&&x>=0;
const identityKey=(x:FeedIdentity)=>JSON.stringify([x.instrument,x.provider,x.venue,x.sourceId,x.priceSide,x.seconds]);
/**
 * Two caller-declared chronological, equal-length, contiguous cohorts.
 * Caller must prove the cohorts were prospectively registered independently.
 * Unlike scoring a convenient trailing sample, a missing slot cannot be
 * omitted without causing an insufficient or invalid report.
 */
export function auditForecastCalibrationDrift(
  earlier:readonly ForecastRecord[],recent:readonly ForecastRecord[],
  identity:FeedIdentity,modelVersion:string,horizon:1|3|12,asOf:number,
  perWindow=50,maxSettlementLagSeconds=120,
):ForecastCalibrationDrift{
  if(!Array.isArray(earlier)||!Array.isArray(recent)||
     !Number.isSafeInteger(perWindow)||perWindow<50||perWindow>250||
     !epoch(asOf)||!Number.isSafeInteger(maxSettlementLagSeconds)||
     maxSettlementLagSeconds<0||maxSettlementLagSeconds>3600||
     !identity||!Number.isSafeInteger(identity.seconds)||
     identity.seconds<60||identity.seconds%60!==0||
     ![1,3,12].includes(horizon)||typeof modelVersion!=='string'||
     !modelVersion.trim()||modelVersion.length>80||
     earlier.length>perWindow||recent.length>perWindow)
    throw Error('Invalid bounded calibration-drift configuration');
  const key=identityKey(identity),stride=identity.seconds*horizon;
  const all=[...earlier,...recent];
  const ids=new Set<string>();
  for(const r of all){
    if(!r||identityKey(r)!==key||r.modelVersion!==modelVersion||r.horizon!==horizon||
       !epoch(r.baseStart)||r.baseStart%stride!==0||
       typeof r.id!=='string'||!r.id.trim()||r.id.length>160||ids.has(r.id))
      throw Error('Mixed, duplicate, unaligned or malformed drift cohort identity');
    ids.add(r.id);
  }
  for(let i=1;i<all.length;i++){
    // Covers internal and cross-cohort gaps and prevents silent reordering.
    if(all[i].baseStart-all[i-1].baseStart!==stride)
      throw Error('Discontinuous or nonchronological drift cohort');
  }
  const base={mode:'UNVERIFIED_LOCAL_RESEARCH' as const,live:false as const,
    authenticated:false as const,persisted:false as const,alertsEnabled:false as const,
    execution:'NONE' as const,modelVersion,horizon,requiredPerWindow:perWindow,
    earlierCount:earlier.length,recentCount:recent.length,
    brierDeteriorationThreshold:0.02 as const,eceDeteriorationThreshold:0.05 as const};
  const insufficient=(reason:string):ForecastCalibrationDrift=>({...base,
    status:'INSUFFICIENT',review:'NONE',reason,
    earlierBrier:null,recentBrier:null,deltaBrier:null,
    earlierECE:null,recentECE:null,deltaECE:null,
    earlierLogLoss:null,recentLogLoss:null,
    earlierLastTargetClose:null,recentLastTargetClose:null});
  if(earlier.length!==perWindow||recent.length!==perWindow)
    return insufficient('Missing declared forecast slots in one or both chronological cohorts');
  const a=evaluateForwardReliability(earlier,identity,modelVersion,horizon,asOf,perWindow);
  const b=evaluateForwardReliability(recent,identity,modelVersion,horizon,asOf,perWindow);
  for(const r of all){
    if(r.status==='SETTLED'&&(r.reason!==null||
       !epoch(r.resolvedAt!)||r.resolvedAt!-(r.targetStart+identity.seconds)>maxSettlementLagSeconds))
      return insufficient('Missing or late trusted settlement in declared drift cohort');
  }
  if(a.status!=='REPORT'||b.status!=='REPORT'||
     a.brier===null||b.brier===null||a.expectedCalibrationError===null||
     b.expectedCalibrationError===null||a.logLoss===null||b.logLoss===null||
     a.latestTargetClose===null||b.latestTargetClose===null)
    return insufficient(`Earlier: ${a.reason??'complete'}; recent: ${b.reason??'complete'}`);
  const deltaBrier=b.brier-a.brier,deltaECE=b.expectedCalibrationError-a.expectedCalibrationError;
  const worse=deltaBrier>=0.02-1e-12;
  const review:ForecastCalibrationDrift['review']=worse&&deltaECE>=0.05-1e-12?
    'CALIBRATION_AND_LOSS_REVIEW':worse&&b.brier>0.25?'LOSS_REVIEW':'NO_THRESHOLD_CROSSING';
  return {...base,status:'REPORT',review,reason:null,
    earlierBrier:a.brier,recentBrier:b.brier,deltaBrier,
    earlierECE:a.expectedCalibrationError,recentECE:b.expectedCalibrationError,deltaECE,
    earlierLogLoss:a.logLoss,recentLogLoss:b.logLoss,
    earlierLastTargetClose:a.latestTargetClose,recentLastTargetClose:b.latestTargetClose};
}
