/**
 * Disconnected prequential calibration challenge, NOT an alert/trade signal.
 * The e-process tests a conditional Bernoulli calibration null using a
 * predictable Laplace-smoothed alternative. The anytime threshold assumes
 * the declared model, source, cohort, and test family were fixed in advance.
 */
export type EProcessFeed={instrument:string;provider:string;venue:string;sourceId:string;priceSide:'bid'|'ask'|'mid';seconds:number};
export type EProcessRecord={
  id:string;modelVersion:string;horizon:1|3|12;probability:number;
  instrument:string;provider:string;venue:string;sourceId:string;priceSide:'bid'|'ask'|'mid';seconds:number;
  baseStart:number;baseClose:number;issuedAt:number;targetStart:number;
  status:'PENDING'|'SETTLED'|'VOID_GAP';resolvedAt:number|null;
  outcomeUp:boolean|null;reason:string|null;
};
export type CalibrationEProcess={
  mode:'UNVERIFIED_LOCAL_RESEARCH';live:false;authenticated:false;
  persisted:false;alertsEnabled:false;execution:'NONE';
  status:'INSUFFICIENT'|'REPORT';decision:'NONE'|'REVIEW_ONLY'|'NO_THRESHOLD';
  reason:string|null;modelVersion:string;horizon:1|3|12;
  observations:number;minimumObservations:number;familySize:number;
  alphaPerFamily:number;thresholdLogE:number;
  finalLogE:number|null;peakLogE:number|null;
  eValue:number|null;eValueCensored:boolean;
  firstBaseStart:number|null;lastTargetClose:number|null;
};
const epoch=(x:number)=>Number.isSafeInteger(x)&&x>=0;
const feedKey=(x:EProcessFeed)=>JSON.stringify([x.instrument,x.provider,x.venue,x.sourceId,x.priceSide,x.seconds]);
/**
 * The caller declares the entire contiguous non-overlapping cohort. Never
 * filter outcomes or choose a convenient suffix after inspecting results.
 * An e-process threshold is only interpretable under the conditional
 * calibration null and a genuinely prospective predeclared test family.
 */
export function auditForecastCalibrationEProcess(
  records:readonly EProcessRecord[],identity:EProcessFeed,modelVersion:string,
  horizon:1|3|12,asOf:number,
  options:{alpha?:number;familySize?:number;minimumObservations?:number;maxSettlementLagSeconds?:number}={},
):CalibrationEProcess{
  const {alpha=.05,familySize=3,minimumObservations=30,maxSettlementLagSeconds=120}=options;
  if(!Array.isArray(records)||records.length>500||!identity||
    ![identity.instrument,identity.provider,identity.venue,identity.sourceId].every(s=>typeof s==='string'&&s.trim().length>0)||
    !['bid','ask','mid'].includes(identity.priceSide)||
    !Number.isSafeInteger(identity.seconds)||identity.seconds<60||identity.seconds%60!==0||
    typeof modelVersion!=='string'||!modelVersion.trim()||modelVersion.length>80||
    ![1,3,12].includes(horizon)||!epoch(asOf)||
    !Number.isFinite(alpha)||alpha<=0||alpha>.1||
    !Number.isSafeInteger(familySize)||familySize<1||familySize>100||
    !Number.isSafeInteger(minimumObservations)||minimumObservations<30||minimumObservations>500||
    !Number.isSafeInteger(maxSettlementLagSeconds)||maxSettlementLagSeconds<0||maxSettlementLagSeconds>3600)
    throw Error('Invalid bounded e-process configuration');
  const thresholdLogE=Math.log(familySize/alpha);
  const base={mode:'UNVERIFIED_LOCAL_RESEARCH' as const,live:false as const,
    authenticated:false as const,persisted:false as const,alertsEnabled:false as const,
    execution:'NONE' as const,modelVersion,horizon,minimumObservations,
    familySize,alphaPerFamily:alpha/familySize,thresholdLogE};
  const insufficient=(reason:string):CalibrationEProcess=>({...base,
    status:'INSUFFICIENT',decision:'NONE',reason,observations:records.length,
    finalLogE:null,peakLogE:null,eValue:null,eValueCensored:false,
    firstBaseStart:null,lastTargetClose:null});
  if(records.length<minimumObservations)return insufficient('Declared cohort has too few observations');
  const key=feedKey(identity),stride=horizon*identity.seconds;
  const ids=new Set<string>();
  let successes=0,logE=0,peakLogE=0,previous:EProcessRecord|null=null;
  for(const r of records){
    if(!r||feedKey(r)!==key||r.modelVersion!==modelVersion||r.horizon!==horizon||
      typeof r.id!=='string'||!/^[A-Za-z0-9_-]{1,80}$/.test(r.id)||ids.has(r.id)||
      !epoch(r.baseStart)||r.baseStart%stride!==0||
      !Number.isFinite(r.baseClose)||r.baseClose<=0||
      !Number.isFinite(r.probability)||r.probability<=0||r.probability>=1||
      !epoch(r.issuedAt)||!epoch(r.resolvedAt!)||
      !epoch(r.targetStart)||!Number.isSafeInteger(r.baseStart+stride+identity.seconds)||
      r.targetStart!==r.baseStart+stride||
      r.issuedAt<r.baseStart+identity.seconds||
      r.issuedAt>=r.baseStart+2*identity.seconds||r.issuedAt>asOf||
      r.status!=='SETTLED'||typeof r.outcomeUp!=='boolean'||r.reason!==null||
      r.resolvedAt!<r.targetStart+identity.seconds||
      r.resolvedAt!>r.targetStart+identity.seconds+maxSettlementLagSeconds||
      r.resolvedAt!>asOf||
      (previous!==null&&(r.baseStart-previous.baseStart!==stride||previous.resolvedAt!>r.issuedAt)))
      throw Error('Invalid, missing, late, mixed, noncausal or noncontiguous e-process observation');
    ids.add(r.id);
    // q_t depends ONLY on outcomes settled before the current issue time.
    const q=Math.max(.01,Math.min(.99,(successes+1)/(ids.size+1)));
    const p=r.probability;
    logE+=r.outcomeUp?Math.log(q/p):Math.log((1-q)/(1-p));
    peakLogE=Math.max(peakLogE,logE);
    successes+=Number(r.outcomeUp);
    previous=r;
  }
  const eValueCensored=logE>Math.log(Number.MAX_VALUE);
  return {...base,status:'REPORT',decision:peakLogE>=thresholdLogE?'REVIEW_ONLY':'NO_THRESHOLD',
    reason:null,observations:records.length,finalLogE:logE,peakLogE,
    eValue:eValueCensored?null:Math.exp(logE),eValueCensored,
    firstBaseStart:records[0].baseStart,lastTargetClose:previous!.targetStart+identity.seconds};
}
