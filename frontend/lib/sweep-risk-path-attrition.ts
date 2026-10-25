/**
 * Read-only source-isolated accounting of frozen confluence risk-path selection.
 * Missing/gapped/warmup-excluded paths have UNKNOWN outcomes, not zero returns.
 */
import type {RiskPathReport} from './sweep-confluence-risk-path.ts';
import {auditConfluenceSourceInfluence} from './sweep-risk-path-source-influence.ts';

export type AttritionCounts={
 inputSignals:number;closed:number;pending:number;gapExcluded:number;
 warmupExcluded:number;overlapExcluded:number;priceExcluded:number;
};
export type AttritionSource=AttritionCounts&{
 datasetId:string;eligibleShare:number|null;unresolvedShare:number|null;
};
export type AttritionAudit={
 engine:'sweep-confluence-risk-path-attrition-v1';instrument:string;
 sourceReports:number;activeSources:number;counts:AttritionCounts;
 eligibleShare:number|null;excludedShare:number|null;
 unresolvedShare:number|null;equalSourceEligibleShare:number|null;
 sourceEligibleShareRange:{min:number;max:number}|null;
 sources:AttritionSource[];
 warning:string;
};
const FIELDS=['inputSignals','closed','pending','gapExcluded','warmupExcluded',
 'overlapExcluded','priceExcluded'] as const;
const share=(n:number,d:number):number|null=>d>0?n/d:null;
export function auditConfluenceRiskPathAttrition(reports:readonly RiskPathReport[]):AttritionAudit{
 // Independently checks all frozen source report accounting, price/return math,
 // configuration consistency, archive IDs and cross-source selected-trade overlap.
 const validated=auditConfluenceSourceInfluence(reports);
 const sources:AttritionSource[]=[...reports].sort((a,b)=>a.datasetId.localeCompare(b.datasetId,'en'))
  .map(report=>{
   const counts=Object.fromEntries(FIELDS.map(k=>[k,report[k]])) as AttritionCounts;
   return {...counts,datasetId:report.datasetId,
    eligibleShare:share(report.closed,report.inputSignals),
    // Only pending and data-gap outcomes are unresolved; other exclusions
    // were ineligible by the frozen protocol, not measured losing trades.
    unresolvedShare:share(report.pending+report.gapExcluded,report.inputSignals)};
  });
 const counts=Object.fromEntries(FIELDS.map(k=>[k,sources.reduce((sum,s)=>sum+s[k],0)])) as AttritionCounts;
 if(FIELDS.some(k=>!Number.isSafeInteger(counts[k])))throw Error('Unsafe pooled signal count');
 if(counts.closed!==validated.trades||counts.inputSignals!==
   counts.closed+counts.pending+counts.gapExcluded+counts.warmupExcluded+
   counts.overlapExcluded+counts.priceExcluded)
  throw Error('Pooled accounting mismatch');
 const eligibleShares=sources.flatMap(s=>s.eligibleShare===null?[]:[s.eligibleShare]);
 const equal=eligibleShares.length?eligibleShares.reduce((s,x)=>s+x,0)/eligibleShares.length:null;
 return {engine:'sweep-confluence-risk-path-attrition-v1',instrument:validated.instrument,
  sourceReports:reports.length,activeSources:validated.activeSources,counts,
  eligibleShare:share(counts.closed,counts.inputSignals),
  excludedShare:share(counts.inputSignals-counts.closed,counts.inputSignals),
  unresolvedShare:share(counts.pending+counts.gapExcluded,counts.inputSignals),
  equalSourceEligibleShare:equal,
  sourceEligibleShareRange:eligibleShares.length?
   {min:Math.min(...eligibleShares),max:Math.max(...eligibleShares)}:null,
  sources,
  warning:'Descriptive retrospective signal attrition, not strategy performance. Missing, pending, warmup, overlap, gap and price-excluded paths have unknown or ineligible outcomes, never imputed zero or a loss. Eligible shares can be selection-biased; equal-source shares differ from pooled shares. Archive IDs and nonoverlapping selected trades do not prove independent candle coverage or source authenticity. No broker quotes, live orders or trading-edge claim.'};
}
