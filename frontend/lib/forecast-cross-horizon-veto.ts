/**
 * OFFLINE cross-horizon veto for an already assessed two-model forecast.
 * This is deliberately more conservative than within-horizon agreement:
 * 1-, 3- and 12-candle research directions must ALL agree to avoid abstention.
 * Different horizons need not have monotone probabilities or equal accuracy.
 * No market feed, alert transport, quote, or broker is authenticated here.
 */
import type {ForecastAgreement,AgreementHorizon,AgreementStatus} from './forecast-agreement-gate.ts';

export type HorizonVetoReason =
  'RESEARCH_CONSENSUS_ONLY'|'STALE'|'MODEL_CONFLICT'|
  'INSUFFICIENT'|'UNCERTAIN'|'CROSS_HORIZON_CONFLICT';
export type HorizonVeto = {
  mode:'UNVERIFIED_LOCAL_RESEARCH';live:false;authenticated:false;
  persisted:false;alertsEnabled:false;execution:'NONE';ordersSubmitted:0;
  status:'RESEARCH_CONSENSUS_ONLY'|'ABSTAIN';
  reason:HorizonVetoReason;direction:'UP'|'DOWN'|null;
  assessedAt:number;asOf:number;maxAgeSeconds:number;
  horizons:readonly [1,3,12];
  // Research directions, NOT actionable buy/sell signals.
  researchDirections:(('UP'|'DOWN'|null))[];
};
const epoch=(v:number)=>Number.isSafeInteger(v)&&v>=0;
const token=(v:unknown)=>typeof v==='string'&&v.length>0&&v.length<=160&&v.trim()===v;
const probability=(v:unknown)=>typeof v==='number'&&Number.isFinite(v)&&v>=0&&v<=1;
const allowed:readonly AgreementStatus[]=[
  'ABSTAIN_INSUFFICIENT','ABSTAIN_CONFLICT','ABSTAIN_UNCERTAIN',
  'CONSENSUS_UP_RESEARCH_ONLY','CONSENSUS_DOWN_RESEARCH_ONLY',
];
function checkHorizon(r:AgreementHorizon,expected:1|3|12):void{
  if(!r||r.horizon!==expected||!allowed.includes(r.status)||
     !Number.isSafeInteger(r.frequencySamples)||r.frequencySamples<0||
     !Number.isFinite(r.ewmaEffectiveSamples)||r.ewmaEffectiveSamples<0||
     r.ewmaEffectiveSamples>r.frequencySamples+1e-8)
    throw Error('Invalid or reordered horizon evidence');
  const a=r.frequencyProbability,b=r.ewmaProbability;
  if(a===null||b===null){
    if(a!==null||b!==null)throw Error('Partially missing model probabilities');
    if(r.status!=='ABSTAIN_INSUFFICIENT'||r.direction!==null||
       r.absoluteDisagreement!==null||r.probabilityRange!==null)
      throw Error('Malformed insufficient horizon evidence');
    return;
  }
  if(!probability(a)||!probability(b)||!probability(r.absoluteDisagreement)||
     !Array.isArray(r.probabilityRange)||r.probabilityRange.length!==2||
     !probability(r.probabilityRange[0])||!probability(r.probabilityRange[1])||
     Math.abs(r.absoluteDisagreement!-Math.abs(a-b))>1e-9||
     Math.abs(r.probabilityRange[0]-Math.min(a,b))>1e-9||
     Math.abs(r.probabilityRange[1]-Math.max(a,b))>1e-9)
    throw Error('Inconsistent probability provenance');
  if(r.status==='ABSTAIN_INSUFFICIENT')throw Error('Insufficient status with complete probabilities');
  if(r.status==='CONSENSUS_UP_RESEARCH_ONLY'){
    if(r.direction!=='UP'||a<=0.5||b<=0.5)throw Error('Invalid UP consensus');
  }else if(r.status==='CONSENSUS_DOWN_RESEARCH_ONLY'){
    if(r.direction!=='DOWN'||a>=0.5||b>=0.5)throw Error('Invalid DOWN consensus');
  }else if(r.direction!==null)throw Error('Abstention cannot carry a direction');
}
/**
 * All three horizon decisions are mandatory, even when a caller prefers a
 * short holding period. Cross-horizon disagreement is a conservative veto,
 * NOT a mathematical inconsistency and NOT evidence that either is wrong.
 * Caller-supplied timestamps cannot prove the observations were prospective.
 */
export function vetoOfflineCrossHorizon(
  agreement:ForecastAgreement,asOf:number,
  maxAgeSeconds=120,
):HorizonVeto{
  if(!epoch(asOf)||!Number.isSafeInteger(maxAgeSeconds)||
     maxAgeSeconds<0||maxAgeSeconds>3600||!agreement||
     agreement.mode!=='UNVERIFIED_LOCAL_RESEARCH'||agreement.live!==false||
     agreement.authenticated!==false||agreement.persisted!==false||
     agreement.alertsEnabled!==false||agreement.execution!=='NONE'||
     agreement.ordersSubmitted!==0||!agreement.identity||
     !token(agreement.identity.instrument)||!token(agreement.identity.provider)||
     !token(agreement.identity.venue)||!token(agreement.identity.sourceId)||
     !['bid','ask','mid'].includes(agreement.identity.priceSide)||
     !Number.isSafeInteger(agreement.identity.seconds)||
     agreement.identity.seconds<60||agreement.identity.seconds>86400||
     agreement.identity.seconds%60!==0||
     !epoch(agreement.issuedAsOf)||!epoch(agreement.assessedAt)||
     agreement.issuedAsOf>agreement.assessedAt||agreement.assessedAt>asOf||
     !Array.isArray(agreement.horizons)||agreement.horizons.length!==3)
    throw Error('Untrusted, future or malformed offline agreement');
  const expected=[1,3,12] as const;
  agreement.horizons.forEach((r,i)=>checkHorizon(r,expected[i]));
  const researchDirections=agreement.horizons.map(r=>r.direction);
  let reason:HorizonVetoReason;
  if(asOf-agreement.assessedAt>maxAgeSeconds)reason='STALE';
  else if(agreement.horizons.some(r=>r.status==='ABSTAIN_CONFLICT'))reason='MODEL_CONFLICT';
  else if(agreement.horizons.some(r=>r.status==='ABSTAIN_INSUFFICIENT'))reason='INSUFFICIENT';
  else if(agreement.horizons.some(r=>r.status==='ABSTAIN_UNCERTAIN'))reason='UNCERTAIN';
  else if(new Set(researchDirections).size!==1)reason='CROSS_HORIZON_CONFLICT';
  else reason='RESEARCH_CONSENSUS_ONLY';
  const status=reason==='RESEARCH_CONSENSUS_ONLY'?'RESEARCH_CONSENSUS_ONLY':'ABSTAIN';
  const direction=status==='RESEARCH_CONSENSUS_ONLY'?researchDirections[0]:null;
  return {mode:'UNVERIFIED_LOCAL_RESEARCH',live:false,authenticated:false,
    persisted:false,alertsEnabled:false,execution:'NONE',ordersSubmitted:0,
    status,reason,direction,assessedAt:agreement.assessedAt,asOf,
    maxAgeSeconds,horizons:expected,researchDirections};
}
