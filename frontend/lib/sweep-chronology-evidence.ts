/** Offline completed-path chronology audit; NEVER certifies an untouched holdout. */
import type {RiskPathReport} from './sweep-confluence-risk-path.ts';
import {summarizeRiskPathCostRegimes} from './sweep-risk-path-regime-stress.ts';
const W=604800,MON=345600;
export type ChronologyPlan={datasetId:string;instrument:string;developmentStart:number;validationStart:number;holdoutStart:number;holdoutEnd:number};
export type ChronologySlice={phase:'DEVELOPMENT'|'VALIDATION'|'HOLDOUT';completedEntries:number;purged:number;embargoed:number;eligible:number;weeks:number;status:'WITHHELD'|'DESCRIPTIVE_ONLY';tradeMeanR:number|null;equalWeekMeanR:number|null};
export type ChronologyAudit={engine:'sweep-chronology-evidence-v1';datasetId:string;instrument:string;roundTripCostBps:5;purgeSeconds:604800;embargoSeconds:604800;inputCompleted:number;outside:number;accounted:number;slices:ChronologySlice[];sourceProvenanceVerified:false;untouchedHoldoutVerified:false;eligibleForLiveTrading:false;warning:string};
function mean(xs:readonly number[]):number{let m=0;xs.forEach((x,i)=>{m+=(x-m)/(i+1);if(!Number.isFinite(m))throw Error('Nonfinite mean')});return m}
export function auditFrozenChronology(report:RiskPathReport,plan:ChronologyPlan):ChronologyAudit{
 summarizeRiskPathCostRegimes(report); // Independent price, chronology, accounting and cost audit.
 if(!plan||plan.datasetId!==report.datasetId||plan.instrument!==report.instrument)throw Error('Source identity mismatch');
 const b=[plan.developmentStart,plan.validationStart,plan.holdoutStart,plan.holdoutEnd];
 if(b.some(t=>!Number.isSafeInteger(t)||t<0||t>4102444800||(t-MON)%W!==0))throw Error('Monday UTC boundaries required');
 if(b.some((t,i)=>i>0&&t-b[i-1]<14*W))throw Error('Each phase requires at least 14 full weeks');
 const j=report.config.roundTripCostsBps.indexOf(5);
 if(j<0)throw Error('Frozen 5 bps cost required');
 const names:readonly ChronologySlice['phase'][]=['DEVELOPMENT','VALIDATION','HOLDOUT'];
 const bins=names.map((phase,i)=>({phase,start:b[i],end:b[i+1],completedEntries:0,purged:0,embargoed:0,values:[] as number[],weeks:new Map<number,number[]>()}));
 let outside=0;
 for(const t of report.trades){
  const i=t.entryAt<b[0]||t.entryAt>=b[3]?-1:t.entryAt<b[1]?0:t.entryAt<b[2]?1:2;
  if(i<0){outside++;continue}
  const z=bins[i];z.completedEntries++;
  if(t.entryAt<z.start+W){z.purged++;continue}
  // The outcome at the embargo boundary is NOT available to the phase.
  if(t.exitAt>=z.end-W){z.embargoed++;continue}
  const v=t.netR[j];z.values.push(v);
  const w=Math.floor((t.entryAt-MON)/W),a=z.weeks.get(w)||[];
  a.push(v);z.weeks.set(w,a);
 }
 const slices:ChronologySlice[]=bins.map(z=>{
  const eligible=z.values.length,weeks=z.weeks.size,enough=eligible>=30&&weeks>=12;
  return {phase:z.phase,completedEntries:z.completedEntries,purged:z.purged,embargoed:z.embargoed,eligible,weeks,status:enough?'DESCRIPTIVE_ONLY':'WITHHELD',tradeMeanR:enough?mean(z.values):null,equalWeekMeanR:enough?mean([...z.weeks.values()].map(mean)):null};
 });
 const accounted=outside+slices.reduce((n,z)=>n+z.purged+z.embargoed+z.eligible,0);
 if(accounted!==report.closed)throw Error('Attrition accounting mismatch');
 return {engine:'sweep-chronology-evidence-v1',datasetId:report.datasetId,instrument:report.instrument,roundTripCostBps:5,purgeSeconds:W,embargoSeconds:W,inputCompleted:report.closed,outside,accounted,slices,sourceProvenanceVerified:false,untouchedHoldoutVerified:false,eligibleForLiveTrading:false,warning:'Descriptive only: retrospective completed BID/OHLC paths, not all signal outcomes. Fixed one-week purge and embargo cannot prove complete feature lookback or an untouched holdout. Caller-provided boundaries and dataset IDs are not independent provenance. Costs are illustrative, not authenticated executable quotes or financing. Withheld observations are unknown, not zero returns. No statistical edge or trading authorization.'};
}
