/**
 * Offline, descriptive circular moving-block sensitivity for completed OHLC
 * confluence paths. Four contiguous UTC calendar weeks per sampled block.
 * No data access, parameter search, order routes, or calibrated inference.
 */
import type {RiskPathReport} from './sweep-confluence-risk-path.ts';
import {summarizeRiskPathCostRegimes} from './sweep-risk-path-regime-stress.ts';

const WEEK=604800,MONDAY=345600,BLOCK=4,DRAWS=3000,MAX_WEEKS=2600;
export type FourWeekCostScenario={
 roundTripCostBps:number;meanNetR:number|null;meanNetBps:number|null;
 blockLower95NetR:number|null;blockUpper95NetR:number|null;
 blockLower95NetBps:number|null;blockUpper95NetBps:number|null;
};
export type FourWeekBlockAudit={
 engine:'sweep-four-week-block-uncertainty-v1';datasetId:string;instrument:string;
 seed:string;blockWeeks:4;replicates:3000;trades:number;
 activeWeeks:number;calendarWeeks:number;activeWeekFraction:number|null;
 largestFourWeekTradeShare:number|null;
 status:'INSUFFICIENT_EVIDENCE'|'DESCRIPTIVE_ONLY'|'WITHHELD_EMPTY_RESAMPLE';
 scenarios:FourWeekCostScenario[];sourceProvenanceVerified:false;
 untouchedHoldoutVerified:false;eligibleForLiveTrading:false;warning:string;
};
function percentile(xs:readonly number[],p:number):number{
 const at=(xs.length-1)*p,lo=Math.floor(at),hi=Math.ceil(at);
 return xs[lo]+(xs[hi]-xs[lo])*(at-lo);
}
function hash(s:string):number{
 let h=2166136261;
 for(let i=0;i<s.length;i++)h=Math.imul(h^s.charCodeAt(i),16777619);
 return h>>>0||0x9e3779b9;
}
export function auditFourWeekBlockUncertainty(
 report:RiskPathReport,seed='locked-four-week-block-v1'
):FourWeekBlockAudit{
 // Independent validation of source identity, chronological non-overlap,
 // exact scenario arithmetic, trade geometry and report-level means.
 const validated=summarizeRiskPathCostRegimes(report);
 if(typeof seed!=='string'||!seed.trim()||seed.length>128)
  throw Error('A bounded nonempty frozen seed is required');
 const costs=report.config.roundTripCostsBps;
 const buckets=new Map<number,{n:number;r:number[];bps:number[]}>();
 for(const t of report.trades){
  const w=Math.floor((t.entryAt-MONDAY)/WEEK);
  const g=buckets.get(w)||{n:0,r:costs.map(()=>0),bps:costs.map(()=>0)};
  g.n++;
  for(let j=0;j<costs.length;j++){
   g.r[j]+=t.netR[j];g.bps[j]+=t.netBps[j];
   if(!Number.isFinite(g.r[j])||!Number.isFinite(g.bps[j]))
    throw Error('Nonfinite weekly total');
  }
  buckets.set(w,g);
 }
 const keys=[...buckets.keys()].sort((a,b)=>a-b);
 const span=keys.length?keys[keys.length-1]-keys[0]+1:0;
 if(span>MAX_WEEKS)throw Error('Excessive calendar-week span');
 const weeks=Array.from({length:span},(_,i)=>
  buckets.get(keys[0]+i)||{n:0,r:costs.map(()=>0),bps:costs.map(()=>0)});
 const count=report.trades.length,active=keys.length;
 let largest=0;
 for(let i=0;i<span;i++){
  let n=0;
  for(let j=0;j<BLOCK;j++)n+=weeks[(i+j)%span].n;
  largest=Math.max(largest,n);
 }
 const enough=count>=30&&active>=12&&span>=16;
 const scenarios:FourWeekCostScenario[]=costs.map((cost,j)=>({
  roundTripCostBps:cost,meanNetR:validated.scenarios[j].meanNetR,
  meanNetBps:validated.scenarios[j].meanNetBps,
  blockLower95NetR:null,blockUpper95NetR:null,
  blockLower95NetBps:null,blockUpper95NetBps:null
 }));
 let status:FourWeekBlockAudit['status']=enough?'DESCRIPTIVE_ONLY':'INSUFFICIENT_EVIDENCE';
 if(enough){
  let state=hash([report.datasetId,report.instrument,report.engine,
   report.config.atrPeriod,report.config.stopAtrMultiple,
   report.config.rewardRisk,report.config.maxHoldBars,costs.join(','),seed].join('|'));
  const next=()=>{state^=state<<13;state^=state>>>17;state^=state<<5;return (state>>>0)/4294967296};
  const samplesR=costs.map(()=>[] as number[]),samplesBps=costs.map(()=>[] as number[]);
  for(let draw=0;draw<DRAWS;draw++){
   const sumR=costs.map(()=>0),sumBps=costs.map(()=>0);
   let sampled=0;
   // Sampling *calendar* weeks, including zero-trade weeks, prevents a
   // sparse source from silently being converted into active-week-only data.
   for(let offset=0;offset<span;offset+=BLOCK){
    const start=Math.floor(next()*span);
    for(let j=0;j<Math.min(BLOCK,span-offset);j++){
     const g=weeks[(start+j)%span];sampled+=g.n;
     for(let k=0;k<costs.length;k++){
      sumR[k]+=g.r[k];sumBps[k]+=g.bps[k];
     }
    }
   }
   // Do not condition on a positive-trade resample by discarding it.
   // Withhold the entire interval instead of changing the sampling law.
   if(sampled===0){status='WITHHELD_EMPTY_RESAMPLE';break}
   for(let k=0;k<costs.length;k++){
    const r=sumR[k]/sampled,b=sumBps[k]/sampled;
    if(!Number.isFinite(r)||!Number.isFinite(b))throw Error('Nonfinite resample');
    samplesR[k].push(r);samplesBps[k].push(b);
   }
  }
  if(status==='DESCRIPTIVE_ONLY')for(let j=0;j<costs.length;j++){
   samplesR[j].sort((a,b)=>a-b);samplesBps[j].sort((a,b)=>a-b);
   scenarios[j].blockLower95NetR=percentile(samplesR[j],.025);
   scenarios[j].blockUpper95NetR=percentile(samplesR[j],.975);
   scenarios[j].blockLower95NetBps=percentile(samplesBps[j],.025);
   scenarios[j].blockUpper95NetBps=percentile(samplesBps[j],.975);
  }
 }
 return {engine:'sweep-four-week-block-uncertainty-v1',datasetId:report.datasetId,
  instrument:report.instrument,seed,blockWeeks:BLOCK,replicates:DRAWS,trades:count,
  activeWeeks:active,calendarWeeks:span,activeWeekFraction:span?active/span:null,
  largestFourWeekTradeShare:count?largest/count:null,status,scenarios,
  sourceProvenanceVerified:false,untouchedHoldoutVerified:false,
  eligibleForLiveTrading:false,
  warning:'Descriptive four-UTC-calendar-week circular moving-block bootstrap only. Calendar gaps remain in the sampling frame. Four-week dependence is an arbitrary frozen sensitivity assumption, not a calibrated confidence interval, valid p-value, out-of-sample validation, or profitable edge. Circular wrapping may join unrelated market regimes. BID/OHLC and flat costs are not authenticated executable bid/ask, slippage, financing or broker fills. No orders.'};
}
