/**
 * Offline, predeclared paired forecast evaluation. Comparing the same settled
 * target avoids silently rewarding a model whose losing observations vanished.
 * This is NOT an authenticated, prospective, or inferential test of an edge.
 */
import type {FeedIdentity, ForecastRecord} from './forward-forecast-ledger.ts';

export type PairedModelAudit = {
  mode:'UNVERIFIED_LOCAL_RESEARCH'; live:false; authenticated:false;
  persisted:false; alertsEnabled:false; execution:'NONE';
  status:'REPORT'|'INSUFFICIENT'; reason:string|null;
  modelA:string; modelB:string; horizon:1|3|12;
  expectedSlots:number; pairedSlots:number; firstBaseStart:number; lastBaseStart:number;
  brierA:number|null; brierB:number|null; deltaBrierAminusB:number|null;
  logLossA:number|null; logLossB:number|null; deltaLogLossAminusB:number|null;
  aLowerLoss:number|null; bLowerLoss:number|null; tiedLoss:number|null;
  // The min/max of mean paired Brier differences in five chronological blocks.
  // They are descriptive stability checks, not a confidence interval or p-value.
  blockDeltaBrierRange:[number,number]|null;
};
const epoch=(n:number)=>Number.isSafeInteger(n)&&n>=0;
const token=(s:unknown)=>typeof s==='string'&&s.length>0&&s.length<=160&&s.trim()===s;
const sourceKey=(x:FeedIdentity)=>JSON.stringify([x.instrument,x.provider,x.venue,x.sourceId,x.priceSide,x.seconds]);
const logLoss=(p:number,y:number)=>y?-Math.log(p):-Math.log1p(-p);
const brier=(p:number,y:number)=>(p-y)**2;

/**
 * The caller MUST freeze [firstBaseStart,lastBaseStart] before observing target
 * outcomes and supply source-authenticated records later. Here both claims are
 * self-attested. No missing, void, late, or immature slot can be omitted.
 */
export function auditPairedForwardModels(
  records:readonly ForecastRecord[], identity:FeedIdentity,
  modelA:string,modelB:string,horizon:1|3|12,
  firstBaseStart:number,lastBaseStart:number,asOf:number,
  minPairs=30,maxSettlementLagSeconds=120,
):PairedModelAudit{
  if(!identity||![identity.instrument,identity.provider,identity.venue,identity.sourceId].every(token)||
     !['bid','ask','mid'].includes(identity.priceSide)||
     !Number.isSafeInteger(identity.seconds)||identity.seconds<60||identity.seconds>86400||identity.seconds%60!==0||
     !token(modelA)||!token(modelB)||modelA===modelB||![1,3,12].includes(horizon)||
     !epoch(firstBaseStart)||!epoch(lastBaseStart)||!epoch(asOf)||
     !Number.isSafeInteger(minPairs)||minPairs<5||minPairs>5000||
     !Number.isSafeInteger(maxSettlementLagSeconds)||maxSettlementLagSeconds<0||maxSettlementLagSeconds>3600||
     !Array.isArray(records)||records.length>50000)
    throw Error('Invalid paired comparison configuration');
  const stride=identity.seconds*horizon;
  const targetCloseLast=lastBaseStart+(horizon+1)*identity.seconds;
  if(!Number.isSafeInteger(stride)||!Number.isSafeInteger(targetCloseLast)||
     lastBaseStart<firstBaseStart||firstBaseStart%stride!==0||lastBaseStart%stride!==0||
     (lastBaseStart-firstBaseStart)%stride!==0||
     firstBaseStart+identity.seconds>asOf)
    throw Error('Invalid predeclared cohort window');
  const expectedSlots=(lastBaseStart-firstBaseStart)/stride+1;
  if(!Number.isSafeInteger(expectedSlots)||expectedSlots>5000)
    throw Error('Cohort exceeds bounded comparison capacity');
  const base={mode:'UNVERIFIED_LOCAL_RESEARCH' as const,live:false as const,
    authenticated:false as const,persisted:false as const,alertsEnabled:false as const,
    execution:'NONE' as const,modelA,modelB,horizon,expectedSlots,
    firstBaseStart,lastBaseStart};
  const insufficient=(reason:string,pairedSlots:number):PairedModelAudit=>({
    ...base,status:'INSUFFICIENT',reason,pairedSlots,
    brierA:null,brierB:null,deltaBrierAminusB:null,
    logLossA:null,logLossB:null,deltaLogLossAminusB:null,
    aLowerLoss:null,bLowerLoss:null,tiedLoss:null,blockDeltaBrierRange:null,
  });
  const a=new Map<number,ForecastRecord>(),b=new Map<number,ForecastRecord>();
  const ids=new Set<string>();
  const exact=sourceKey(identity);
  for(const r of records){
    if(!r||sourceKey(r)!==exact)throw Error('Mixed or malformed source identity');
    if(r.horizon!==horizon||(r.modelVersion!==modelA&&r.modelVersion!==modelB))continue;
    const baseClose=r.baseStart+identity.seconds;
    const nextClose=baseClose+identity.seconds;
    const targetStart=r.baseStart+horizon*identity.seconds;
    const targetClose=targetStart+identity.seconds;
    if(!token(r.id)||!epoch(r.baseStart)||r.baseStart<firstBaseStart||r.baseStart>lastBaseStart||
       r.baseStart%stride!==0||!epoch(baseClose)||!epoch(nextClose)||!epoch(targetClose)||
       r.targetStart!==targetStart||!epoch(r.issuedAt)||r.issuedAt<baseClose||
       r.issuedAt>=nextClose||r.issuedAt>asOf||
       !Number.isFinite(r.baseClose)||r.baseClose<=0||
       !Number.isFinite(r.probability)||r.probability<=0||r.probability>=1||
       !['PENDING','SETTLED','VOID_GAP'].includes(r.status)||
       (r.status==='PENDING'&&(r.resolvedAt!==null||r.outcomeUp!==null||r.reason!==null))||
       (r.status==='SETTLED'&&(!epoch(r.resolvedAt!)||r.resolvedAt!<targetClose||
          r.resolvedAt!<r.issuedAt||r.resolvedAt!>asOf||
          typeof r.outcomeUp!=='boolean'||r.reason!==null))||
       (r.status==='VOID_GAP'&&(!epoch(r.resolvedAt!)||r.resolvedAt!<r.issuedAt||
          r.resolvedAt!>asOf||r.outcomeUp!==null||!token(r.reason))))
      throw Error('Malformed, retroactive or future-dated paired forecast');
    const map=r.modelVersion===modelA?a:b;
    if(ids.has(r.id)||map.has(r.baseStart))throw Error('Duplicate forecast id or model cohort slot');
    ids.add(r.id);map.set(r.baseStart,r);
  }
  if(targetCloseLast>asOf)return insufficient('The predeclared cohort has immature targets',0);
  if(expectedSlots<minPairs)return insufficient('Insufficient predeclared paired sample size',0);
  const pairs:{pa:number;pb:number;y:number}[]=[];
  for(let slot=firstBaseStart;slot<=lastBaseStart;slot+=stride){
    const left=a.get(slot),right=b.get(slot);
    if(!left||!right)return insufficient('Missing forecast issuance in predeclared paired cohort',pairs.length);
    if(left.status!=='SETTLED'||right.status!=='SETTLED')
      return insufficient('Pending or gap-voided outcome in paired cohort',pairs.length);
    const targetClose=slot+(horizon+1)*identity.seconds;
    if(left.resolvedAt!-targetClose>maxSettlementLagSeconds||
       right.resolvedAt!-targetClose>maxSettlementLagSeconds)
      return insufficient('Late settlement in predeclared paired cohort',pairs.length);
    if(left.baseClose!==right.baseClose||left.outcomeUp!==right.outcomeUp)
      throw Error('Conflicting paired target price or outcome');
    pairs.push({pa:left.probability,pb:right.probability,y:Number(left.outcomeUp)});
  }
  let sumA=0,sumB=0,logA=0,logB=0,aLower=0,bLower=0,tied=0;
  const blockDeltas:number[]=[];
  const blocks=5;
  for(let block=0;block<blocks;block++){
    const from=Math.floor(block*pairs.length/blocks),to=Math.floor((block+1)*pairs.length/blocks);
    let blockSum=0;
    for(let i=from;i<to;i++){
      const {pa,pb,y}=pairs[i],la=brier(pa,y),lb=brier(pb,y);
      sumA+=la;sumB+=lb;logA+=logLoss(pa,y);logB+=logLoss(pb,y);
      blockSum+=la-lb;
      if(Math.abs(la-lb)<1e-12)tied++;
      else if(la<lb)aLower++;
      else bLower++;
    }
    blockDeltas.push(blockSum/(to-from));
  }
  return {...base,status:'REPORT',reason:null,pairedSlots:pairs.length,
    brierA:sumA/pairs.length,brierB:sumB/pairs.length,
    deltaBrierAminusB:(sumA-sumB)/pairs.length,
    logLossA:logA/pairs.length,logLossB:logB/pairs.length,
    deltaLogLossAminusB:(logA-logB)/pairs.length,
    aLowerLoss:aLower,bLowerLoss:bLower,tiedLoss:tied,
    blockDeltaBrierRange:[Math.min(...blockDeltas),Math.max(...blockDeltas)]};
}
