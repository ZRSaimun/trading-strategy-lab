/**
 * Disconnected prequential (predict-then-observe) forecast scorecard.
 * Every reference probability uses only already-SETTLED outcomes available
 * when that forecast was issued. Never authenticates caller timestamps/data.
 */
import type {FeedIdentity, ForecastRecord} from './forward-forecast-ledger.ts';

export type PrequentialScorecard={
 mode:'UNVERIFIED_LOCAL_RESEARCH';live:false;execution:'NONE';persisted:false;
 status:'INSUFFICIENT'|'REPORT';reason:string|null;
 modelVersion:string;horizon:1|3|12;required:number;trainingWindow:number;
 scored:number;latestTargetClose:number|null;
 modelBrier:number|null;adaptiveReferenceBrier:number|null;
 modelLogLoss:number|null;adaptiveReferenceLogLoss:number|null;
 brierSkillVsAdaptive:number|null;meanExcessBrier:number|null;
 worstSingleExcessBrier:number|null;maxConsecutiveUnderperformance:number|null;
};
const epoch=(x:number)=>Number.isSafeInteger(x)&&x>=0;
const key=(x:FeedIdentity)=>JSON.stringify([x.instrument,x.provider,x.venue,x.sourceId,x.priceSide,x.seconds]);
const loss=(p:number,y:number)=>(p-y)**2;
const logLoss=(p:number,y:number)=>y?-Math.log(p):-Math.log1p(-p);
/**
 * The last `evaluationWindow` disjoint, UTC-phase-aligned forecasts are scored
 * against a Jeffreys-smoothed directional frequency from the preceding
 * `trainingWindow` disjoint observations, all resolved before issuance.
 * A gap, void, pending target past close, or late training resolution blocks
 * the whole scorecard; it never silently selects only successful predictions.
 */
export function evaluatePrequentialForecastBenchmark(
 records:readonly ForecastRecord[],identity:FeedIdentity,modelVersion:string,
 horizon:1|3|12,asOf:number,trainingWindow=20,evaluationWindow=20,
):PrequentialScorecard{
 if(!identity||!identity.instrument?.trim()||!identity.provider?.trim()||
    !identity.venue?.trim()||!identity.sourceId?.trim()||
    !['bid','ask','mid'].includes(identity.priceSide)||!epoch(identity.seconds)||
    identity.seconds<60||identity.seconds%60!==0||!modelVersion?.trim()||
    modelVersion.length>80||![1,3,12].includes(horizon)||!epoch(asOf)||
    !Number.isSafeInteger(trainingWindow)||trainingWindow<20||trainingWindow>500||
    !Number.isSafeInteger(evaluationWindow)||evaluationWindow<20||evaluationWindow>500||
    !Array.isArray(records)||records.length>50000)
  throw Error('Invalid prequential benchmark configuration');
 const base={mode:'UNVERIFIED_LOCAL_RESEARCH' as const,live:false as const,
  execution:'NONE' as const,persisted:false as const,modelVersion,horizon,
  required:evaluationWindow,trainingWindow};
 const insufficient=(reason:string,scored=0):PrequentialScorecard=>({
  ...base,status:'INSUFFICIENT',reason,scored,latestTargetClose:null,
  modelBrier:null,adaptiveReferenceBrier:null,modelLogLoss:null,
  adaptiveReferenceLogLoss:null,brierSkillVsAdaptive:null,
  meanExcessBrier:null,worstSingleExcessBrier:null,
  maxConsecutiveUnderperformance:null,
 });
 const source=key(identity),seen=new Set<number>(),aligned:ForecastRecord[]=[];
 for(const r of records){
  if(key(r)!==source)throw Error('Mixed source identity');
  if(r.modelVersion!==modelVersion||r.horizon!==horizon)continue;
  const close=r.baseStart+identity.seconds;
  const nextClose=r.baseStart+2*identity.seconds;
  const target=r.baseStart+horizon*identity.seconds;
  const targetClose=target+identity.seconds;
  if(!epoch(r.baseStart)||r.baseStart%identity.seconds!==0||
     !epoch(close)||!epoch(nextClose)||!epoch(target)||!epoch(targetClose)||
     r.targetStart!==target||!epoch(r.issuedAt)||r.issuedAt<close||
     r.issuedAt>=nextClose||r.issuedAt>asOf||
     !Number.isFinite(r.baseClose)||r.baseClose<=0||
     !Number.isFinite(r.probability)||r.probability<=0||r.probability>=1||
     !['PENDING','SETTLED','VOID_GAP'].includes(r.status)||
     (r.status==='PENDING'&&(r.resolvedAt!==null||r.outcomeUp!==null))||
     (r.status==='VOID_GAP'&&(!epoch(r.resolvedAt!)||r.resolvedAt!<r.issuedAt||
       r.resolvedAt!>asOf||r.outcomeUp!==null))||
     (r.status==='SETTLED'&&(!epoch(r.resolvedAt!)||r.resolvedAt!<targetClose||
       r.resolvedAt!<r.issuedAt||r.resolvedAt!>asOf||typeof r.outcomeUp!=='boolean')))
   throw Error('Malformed or future-dated forecast record');
  if(seen.has(r.baseStart))throw Error('Duplicate model/horizon base candle');
  seen.add(r.baseStart);
  if((r.baseStart/identity.seconds)%horizon===0)aligned.push(r);
 }
 aligned.sort((a,b)=>a.baseStart-b.baseStart);
 if(aligned.some(r=>r.status==='PENDING'&&r.targetStart+identity.seconds<=asOf))
  return insufficient('Overdue unresolved outcome');
 let end=aligned.length;
 while(end>0&&aligned[end-1].status==='PENDING')end--;
 const need=trainingWindow+evaluationWindow;
 if(end<need)return insufficient('Insufficient consecutive prospectively settled observations');
 const selected=aligned.slice(end-need,end);
 for(let i=0;i<selected.length;i++){
  if(selected[i].status!=='SETTLED')return insufficient('Pending or voided outcome in training/evaluation window');
  if(i&&selected[i].baseStart-selected[i-1].baseStart!==horizon*identity.seconds)
   return insufficient('Missing aligned forecast interval');
 }
 let modelBrier=0,referenceBrier=0,modelLog=0,referenceLog=0;
 let worstExcess=-Infinity,losingStreak=0,maxLosingStreak=0;
 for(let i=trainingWindow;i<selected.length;i++){
  const candidate=selected[i];
  const training=selected.slice(i-trainingWindow,i);
  // A settled outcome is NOT usable until its recorded resolution is known.
  if(training.some(r=>r.resolvedAt!>candidate.issuedAt||
     r.targetStart+identity.seconds>candidate.issuedAt))
   return insufficient('Reference training outcome was not known at forecast issuance');
  const up=training.reduce((sum,r)=>sum+Number(r.outcomeUp),0);
  const reference=(up+0.5)/(trainingWindow+1);
  const y=Number(candidate.outcomeUp);
  const m=loss(candidate.probability,y),b=loss(reference,y);
  const excess=m-b;
  modelBrier+=m;referenceBrier+=b;
  modelLog+=logLoss(candidate.probability,y);
  referenceLog+=logLoss(reference,y);
  worstExcess=Math.max(worstExcess,excess);
  if(excess>0){losingStreak++;maxLosingStreak=Math.max(maxLosingStreak,losingStreak);}
  else losingStreak=0;
 }
 const n=evaluationWindow;
 const mb=modelBrier/n,rb=referenceBrier/n;
 const metrics=[mb,rb,modelLog/n,referenceLog/n,worstExcess];
 if(metrics.some(x=>!Number.isFinite(x))||rb<=0)
  throw Error('Nonfinite prequential diagnostic');
 return {...base,status:'REPORT',reason:null,scored:n,
  latestTargetClose:selected.at(-1)!.targetStart+identity.seconds,
  modelBrier:mb,adaptiveReferenceBrier:rb,
  modelLogLoss:modelLog/n,adaptiveReferenceLogLoss:referenceLog/n,
  brierSkillVsAdaptive:1-mb/rb,meanExcessBrier:mb-rb,
  worstSingleExcessBrier:worstExcess,
  maxConsecutiveUnderperformance:maxLosingStreak};
}
