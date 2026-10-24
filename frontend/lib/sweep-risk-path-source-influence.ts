/**
 * Offline leave-one-archive-out sensitivity for frozen, source-isolated OHLC
 * confluence risk paths. No signal fitting, broker access, or trading orders.
 */
import type {RiskPathReport,RiskPathTrade} from './sweep-confluence-risk-path.ts';
import {summarizeRiskPathCostRegimes} from './sweep-risk-path-regime-stress.ts';

export type SourceInfluenceScenario={
 roundTripCostBps:number;pooledMeanNetBps:number|null;pooledMeanNetR:number|null;
 equalSourceMeanNetR:number|null;worstLeaveOneSourceMeanR:number|null;
 bestLeaveOneSourceMeanR:number|null;largestAbsoluteShiftR:number|null;
 mostInfluentialDatasetId:string|null;signFlipCount:number|null;
};
export type SourceInfluenceAudit={
 engine:'sweep-confluence-source-influence-v1';instrument:string;
 reports:number;activeSources:number;trades:number;eventWeeks:number;
 largestSourceTradeShare:number|null;
 status:'INSUFFICIENT_EVIDENCE'|'DESCRIPTIVE_ONLY';
 scenarios:SourceInfluenceScenario[];warning:string;
};
const WEEK=604800,MONDAY=345600;
const close=(a:number,b:number)=>Math.abs(a-b)<=1e-10*Math.max(1,Math.abs(a),Math.abs(b));
function sign(x:number){return Math.abs(x)<=1e-10?0:Math.sign(x)}
export function auditConfluenceSourceInfluence(reports:readonly RiskPathReport[]):SourceInfluenceAudit{
 if(!Array.isArray(reports)||reports.length<1||reports.length>100)
  throw Error('Require 1–100 frozen source reports');
 const sorted=[...reports].sort((a,b)=>String(a.datasetId).localeCompare(String(b.datasetId),'en'));
 const ids=new Set<string>();
 const baseline=sorted[0];
 const costs=baseline.config?.roundTripCostsBps;
 const sources:{id:string;n:number;r:number[];bps:number[]}[]=[];
 const allTrades:RiskPathTrade[]=[];
 let total=0;
 for(const report of sorted){
  // Independently validates source, chronology, stop/target, costs and means.
  summarizeRiskPathCostRegimes(report);
  if(ids.has(report.datasetId))throw Error('Duplicate dataset identity');
  ids.add(report.datasetId);
  if(report.instrument!==baseline.instrument||
     report.config.atrPeriod!==baseline.config.atrPeriod||
     report.config.stopAtrMultiple!==baseline.config.stopAtrMultiple||
     report.config.rewardRisk!==baseline.config.rewardRisk||
     report.config.maxHoldBars!==baseline.config.maxHoldBars||
     report.config.roundTripCostsBps.length!==costs.length||
     report.config.roundTripCostsBps.some((v,j)=>v!==costs[j]))
   throw Error('Mixed instrument or frozen strategy configuration');
  total+=report.trades.length;
  if(total>100000)throw Error('Bounded total trade count exceeded');
  const r=costs.map((_,j)=>report.trades.reduce((sum,t)=>sum+t.netR[j],0));
  const bps=costs.map((_,j)=>report.trades.reduce((sum,t)=>sum+t.netBps[j],0));
  if([...r,...bps].some(v=>!Number.isFinite(v)))throw Error('Nonfinite source aggregate');
  sources.push({id:report.datasetId,n:report.trades.length,r,bps});
  allTrades.push(...report.trades);
 }
 // A trade cannot be counted twice under different archive identifiers.
 allTrades.sort((a,b)=>a.entryAt-b.entryAt||a.exitAt-b.exitAt);
 for(let i=1;i<allTrades.length;i++)if(allTrades[i].entryAt<allTrades[i-1].exitAt)
  throw Error('Cross-source overlapping trade intervals');
 const weeks=new Set(allTrades.map(t=>Math.floor((t.entryAt-MONDAY)/WEEK)));
 const active=sources.filter(s=>s.n>0),eligible=total>=30&&weeks.size>=12&&active.length>=5;
 const largestSourceTradeShare=total?Math.max(...sources.map(s=>s.n))/total:null;
 const scenarios:SourceInfluenceScenario[]=costs.map((cost,j)=>{
  const sumR=sources.reduce((sum,s)=>sum+s.r[j],0);
  const sumBps=sources.reduce((sum,s)=>sum+s.bps[j],0);
  if(!Number.isFinite(sumR)||!Number.isFinite(sumBps))throw Error('Nonfinite pooled aggregate');
  const meanR=total?sumR/total:null,meanBps=total?sumBps/total:null;
  const equal=active.length?active.reduce((sum,s)=>sum+s.r[j]/s.n,0)/active.length:null;
  if([meanR,meanBps,equal].some(x=>x!==null&&!Number.isFinite(x)))throw Error('Nonfinite source mean');
  let worst=Infinity,best=-Infinity,shift=-Infinity,most:string|null=null,flips=0;
  if(eligible&&meanR!==null){
   for(const s of active){
    const remain=total-s.n;
    if(remain<=0)throw Error('Empty leave-one-source sample');
    const v=(sumR-s.r[j])/remain;
    if(!Number.isFinite(v))throw Error('Nonfinite leave-one-source mean');
    worst=Math.min(worst,v);best=Math.max(best,v);
    const delta=Math.abs(v-meanR);
    if(delta>shift&&(shift===-Infinity||!close(delta,shift))){shift=delta;most=s.id}
    if(sign(v)!==0&&sign(meanR)!==0&&sign(v)!==sign(meanR))flips++;
   }
  }
  return {roundTripCostBps:cost,pooledMeanNetBps:meanBps,pooledMeanNetR:meanR,
   equalSourceMeanNetR:equal,
   worstLeaveOneSourceMeanR:eligible?worst:null,
   bestLeaveOneSourceMeanR:eligible?best:null,
   largestAbsoluteShiftR:eligible?shift:null,
   mostInfluentialDatasetId:eligible?most:null,signFlipCount:eligible?flips:null};
 });
 return {engine:'sweep-confluence-source-influence-v1',instrument:baseline.instrument,
  reports:reports.length,activeSources:active.length,trades:total,eventWeeks:weeks.size,
  largestSourceTradeShare,status:eligible?'DESCRIPTIVE_ONLY':'INSUFFICIENT_EVIDENCE',
  scenarios,
  warning:'Retrospective source-level leave-one-out sensitivity, not an untouched holdout, independent source-authenticity proof, broker fill, significance test or trading edge. Dataset IDs alone cannot prove independent underlying archives; overlapping archive coverage without overlapping selected trades may remain. Equal-source means do not replace trade-weighted returns. BID/OHLC friction is hypothetical. No orders.'};
}
