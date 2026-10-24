/**
 * Descriptive reliability diagnostics for an OFFLINE, source-isolated forward
 * forecast ledger. No data authentication, notification delivery or trading.
 */
import type {FeedIdentity,ForecastRecord} from './forward-forecast-ledger.ts';

export type ReliabilityBin={
  lowerProbability:number;upperProbability:number;count:number;
  meanForecast:number|null;observedUpRate:number|null;
  wilson95Lower:number|null;wilson95Upper:number|null;
  brier:number|null;
};
export type ForwardReliability={
  mode:'UNVERIFIED_LOCAL_RESEARCH';live:false;
  status:'INSUFFICIENT'|'REPORT';reason:string|null;
  modelVersion:string;horizon:1|3|12;required:number;selected:number;
  trailingPending:number;latestTargetClose:number|null;
  brier:number|null;logLoss:number|null;referenceBrier:number|null;
  brierSkill:number|null;expectedCalibrationError:number|null;
  bins:ReliabilityBin[];
};
const epoch=(n:number)=>Number.isSafeInteger(n)&&n>=0;
const key=(x:FeedIdentity)=>JSON.stringify([x.instrument,x.provider,x.venue,x.sourceId,x.priceSide,x.seconds]);
const binIndex=(p:number)=>Math.min(4,Math.floor(p*5));
function wilson95(up:number,n:number):[number,number]{
  const z=1.959963984540054, p=up/n, z2=z*z, d=1+z2/n;
  const centre=(p+z2/(2*n))/d;
  const half=z*Math.sqrt((p*(1-p)+z2/(4*n))/n)/d;
  return [Math.max(0,centre-half),Math.min(1,centre+half)];
}
function emptyBins():ReliabilityBin[]{
  return Array.from({length:5},(_,i)=>({lowerProbability:i/5,upperProbability:(i+1)/5,
    count:0,meanForecast:null,observedUpRate:null,wilson95Lower:null,wilson95Upper:null,brier:null}));
}
/**
 * Require a fixed UTC phase of non-overlapping outcomes. Pending forecasts at
 * the latest edge are ignored, never counted as wrong. Voided/missing outcomes
 * inside the last N observations prevent scoring; no interpolation or backfill.
 * The caller-supplied asOf is NOT an authenticated receipt clock.
 */
export function evaluateForwardReliability(
  records:readonly ForecastRecord[], identity:FeedIdentity, modelVersion:string,
  horizon:1|3|12, asOf:number, sampleSize=100,
):ForwardReliability{
  if(!identity.instrument.trim()||!identity.provider.trim()||!identity.venue.trim()||!identity.sourceId.trim()||
     !['bid','ask','mid'].includes(identity.priceSide)||!epoch(identity.seconds)||
     identity.seconds<60||identity.seconds%60!==0||!modelVersion.trim()||modelVersion.length>80||
     ![1,3,12].includes(horizon)||!epoch(asOf)||!Number.isSafeInteger(sampleSize)||
     sampleSize<50||sampleSize>500||records.length>50000)
    throw Error('Invalid reliability configuration');
  const exact=key(identity),aligned:ForecastRecord[]=[],seen=new Set<number>();
  for(const r of records){
    if(key(r)!==exact)throw Error('Mixed forecast feed identity');
    if(r.modelVersion!==modelVersion||r.horizon!==horizon)continue;
    const close=r.baseStart+identity.seconds;
    const firstNextClose=r.baseStart+2*identity.seconds;
    const target=r.baseStart+horizon*identity.seconds;
    const targetClose=target+identity.seconds;
    if(!epoch(r.baseStart)||r.baseStart%identity.seconds!==0||!epoch(close)||
       !epoch(firstNextClose)||!epoch(target)||!epoch(targetClose)||
       r.targetStart!==target||!epoch(r.issuedAt)||r.issuedAt<close||
       r.issuedAt>=firstNextClose||r.issuedAt>asOf||
       !Number.isFinite(r.baseClose)||r.baseClose<=0||
       !Number.isFinite(r.probability)||r.probability<=0||r.probability>=1||
       !['PENDING','SETTLED','VOID_GAP'].includes(r.status)||
       (r.status==='PENDING'&&(r.resolvedAt!==null||r.outcomeUp!==null))||
       (r.status==='VOID_GAP'&&(!epoch(r.resolvedAt!)||r.resolvedAt!<r.issuedAt||r.resolvedAt!>asOf||r.outcomeUp!==null))||
       (r.status==='SETTLED'&&(!epoch(r.resolvedAt!)||r.resolvedAt!<targetClose||r.resolvedAt!<r.issuedAt||
          r.resolvedAt!>asOf||typeof r.outcomeUp!=='boolean')))
      throw Error('Malformed or future-dated forward forecast');
    if(seen.has(r.baseStart))throw Error('Duplicate model/horizon base candle');
    seen.add(r.baseStart);
    if((r.baseStart/identity.seconds)%horizon===0)aligned.push(r);
  }
  aligned.sort((a,b)=>a.baseStart-b.baseStart);
  if(aligned.some(r=>r.status==='PENDING'&&r.targetStart+identity.seconds<=asOf)){
    return {mode:'UNVERIFIED_LOCAL_RESEARCH',live:false,status:'INSUFFICIENT',
      reason:'Unresolved forecast past its target candle close',modelVersion,horizon,
      required:sampleSize,selected:0,trailingPending:0,latestTargetClose:null,
      brier:null,logLoss:null,referenceBrier:null,brierSkill:null,
      expectedCalibrationError:null,bins:emptyBins()};
  }
  let end=aligned.length;
  while(end>0&&aligned[end-1].status==='PENDING')end--;
  const trailingPending=aligned.length-end;
  const selected=aligned.slice(Math.max(0,end-sampleSize),end);
  const base={mode:'UNVERIFIED_LOCAL_RESEARCH' as const,live:false as const,
    modelVersion,horizon,required:sampleSize,trailingPending};
  const insufficient=(reason:string):ForwardReliability=>({
    ...base,status:'INSUFFICIENT',reason,selected:selected.length,latestTargetClose:null,
    brier:null,logLoss:null,referenceBrier:null,brierSkill:null,
    expectedCalibrationError:null,bins:emptyBins(),
  });
  if(selected.length<sampleSize)return insufficient('Insufficient UTC-phase-aligned settled forward observations');
  for(let i=0;i<selected.length;i++){
    if(selected[i].status!=='SETTLED')return insufficient('Gap-voided or pending outcome within evaluation window');
    if(i&&selected[i].baseStart-selected[i-1].baseStart!==horizon*identity.seconds)
      return insufficient('Discontinuous non-overlapping outcome window');
  }
  const bins=emptyBins();
  const counts=Array(5).fill(0) as number[];
  const pSums=Array(5).fill(0) as number[];
  const upSums=Array(5).fill(0) as number[];
  const brierSums=Array(5).fill(0) as number[];
  let brierTotal=0,logTotal=0;
  for(const r of selected){
    const i=binIndex(r.probability),up=Number(r.outcomeUp);
    const loss=(r.probability-up)**2;
    counts[i]++;pSums[i]+=r.probability;upSums[i]+=up;brierSums[i]+=loss;
    brierTotal+=loss;
    logTotal-=up?Math.log(r.probability):Math.log1p(-r.probability);
  }
  let ece=0;
  for(let i=0;i<5;i++){
    const n=counts[i];if(!n)continue;
    const p=pSums[i]/n, observed=upSums[i]/n;
    // Wilson intervals are only descriptive; serial dependence is not removed
    // merely by choosing non-overlapping forecast horizons.
    const interval=n>=10?wilson95(upSums[i],n):[null,null];
    bins[i]={...bins[i],count:n,meanForecast:p,observedUpRate:observed,
      wilson95Lower:interval[0],wilson95Upper:interval[1],brier:brierSums[i]/n};
    ece+=n/sampleSize*Math.abs(p-observed);
  }
  const brier=brierTotal/sampleSize;
  return {...base,status:'REPORT',reason:null,selected:sampleSize,
    latestTargetClose:selected[selected.length-1].targetStart+identity.seconds,
    brier,logLoss:logTotal/sampleSize,referenceBrier:.25,
    brierSkill:1-brier/.25,expectedCalibrationError:ece,bins};
}
