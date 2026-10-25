/**
 * Descriptive leave-one-UTC-week-out influence audit of frozen confluence paths.
 * Source report is independently validated before any statistics are computed.
 * Not a new holdout, broker execution study, or significance test.
 */
import type {RiskPathReport} from './sweep-confluence-risk-path.ts';
import {summarizeRiskPathCostRegimes} from './sweep-risk-path-regime-stress.ts';

export type WeekInfluenceScenario={
 roundTripCostBps:number;meanNetR:number|null;meanNetBps:number|null;
 worstLeaveOneWeekMeanR:number|null;bestLeaveOneWeekMeanR:number|null;
 largestAbsoluteShiftR:number|null;mostInfluentialWeekStartUtc:number|null;
 signFlipCount:number|null;
};
export type WeekInfluenceAudit={
 engine:'sweep-confluence-week-influence-v1';datasetId:string;instrument:string;
 trades:number;eventWeeks:number;largestWeekTradeShare:number|null;
 status:'INSUFFICIENT_EVIDENCE'|'DESCRIPTIVE_ONLY';
 scenarios:WeekInfluenceScenario[];warning:string;
};
const WEEK=604800,MONDAY=345600;
function sign(x:number):number{return Math.abs(x)<=1e-10?0:Math.sign(x)}
export function auditConfluenceWeekInfluence(report:RiskPathReport):WeekInfluenceAudit{
 // Fails closed on chronology, source identity, costs, prices, R arithmetic and means.
 const validated=summarizeRiskPathCostRegimes(report);
 const costs=report.config.roundTripCostsBps;
 const weeks=new Map<number,{n:number;r:number[];bps:number[]}>();
 const totalR=costs.map(()=>0),totalBps=costs.map(()=>0);
 for(const trade of report.trades){
  const key=Math.floor((trade.entryAt-MONDAY)/WEEK);
  const g=weeks.get(key)||{n:0,r:costs.map(()=>0),bps:costs.map(()=>0)};
  g.n++;
  for(let j=0;j<costs.length;j++){
   g.r[j]+=trade.netR[j];g.bps[j]+=trade.netBps[j];
   totalR[j]+=trade.netR[j];totalBps[j]+=trade.netBps[j];
   if(![g.r[j],g.bps[j],totalR[j],totalBps[j]].every(Number.isFinite))
    throw Error('Nonfinite weekly aggregate');
  }
  weeks.set(key,g);
 }
 const n=report.trades.length,eligible=n>=30&&weeks.size>=12;
 const largestWeekTradeShare=n?Math.max(...[...weeks.values()].map(g=>g.n))/n:null;
 const scenarios:WeekInfluenceScenario[]=costs.map((cost,j)=>{
  const baseR=validated.scenarios[j].meanNetR;
  const baseBps=validated.scenarios[j].meanNetBps;
  let worst=Infinity,best=-Infinity,largest=-Infinity,most:number|null=null,flips=0;
  if(eligible&&baseR!==null){
   for(const [week,g] of [...weeks].sort((a,b)=>a[0]-b[0])){
    const remaining=n-g.n;
    if(remaining<=0)throw Error('Empty leave-one-week-out sample');
    const r=(totalR[j]-g.r[j])/remaining;
    const bps=(totalBps[j]-g.bps[j])/remaining;
    if(!Number.isFinite(r)||!Number.isFinite(bps))
     throw Error('Nonfinite leave-one-week-out mean');
    worst=Math.min(worst,r);best=Math.max(best,r);
    const shift=Math.abs(r-baseR);
    if(shift>largest){largest=shift;most=week*WEEK+MONDAY}
    if(sign(r)!==0&&sign(baseR)!==0&&sign(r)!==sign(baseR))flips++;
   }
  }
  return {roundTripCostBps:cost,meanNetR:baseR,meanNetBps:baseBps,
   worstLeaveOneWeekMeanR:eligible?worst:null,
   bestLeaveOneWeekMeanR:eligible?best:null,
   largestAbsoluteShiftR:eligible?largest:null,
   mostInfluentialWeekStartUtc:eligible?most:null,
   signFlipCount:eligible?flips:null};
 });
 return {engine:'sweep-confluence-week-influence-v1',datasetId:report.datasetId,
  instrument:report.instrument,trades:n,eventWeeks:weeks.size,
  largestWeekTradeShare,status:eligible?'DESCRIPTIVE_ONLY':'INSUFFICIENT_EVIDENCE',
  scenarios,
  warning:'Retrospective leave-one-UTC-week-out sensitivity only, not an independent holdout, hypothesis test, broker fill, confidence interval or proof of an edge. Weeks may be dependent and already inspected. The 30-trade/12-week minimum is a disclosure gate, not evidence of statistical power. BID/OHLC costs are illustrative; no orders.'};
}
