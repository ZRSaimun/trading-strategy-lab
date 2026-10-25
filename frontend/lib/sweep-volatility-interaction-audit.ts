/**
 * Frozen descriptive join of completed-candle volatility labels to hypothetical
 * confluence risk paths. No regime selection, calibration or broker execution.
 */
import type {RiskPathReport,RiskPathTrade} from './sweep-confluence-risk-path.ts';
import type {VolatilityRegimeReport,VolatilityRegime} from './causal-volatility-regime.ts';
import {summarizeRiskPathCostRegimes} from './sweep-risk-path-regime-stress.ts';

export type InteractionCostSlice={roundTripCostBps:number;meanNetBps:number|null;meanNetR:number|null};
export type InteractionGroup={regime:VolatilityRegime|'UNLABELLED';trades:number;eventWeeks:number;status:'INSUFFICIENT_EVIDENCE'|'DESCRIPTIVE_ONLY';scenarios:InteractionCostSlice[]};
export type VolatilityInteractionAudit={
 engine:'sweep-volatility-interaction-audit-v1';datasetId:string;instrument:string;
 trades:number;matched:number;unlabelled:number;groups:InteractionGroup[];
 status:'INSUFFICIENT_EVIDENCE'|'DESCRIPTIVE_ONLY';warning:string;
};
const H=3600,WEEK=604800,MONDAY=345600;
const regimes:readonly VolatilityRegime[]=['LOW','NORMAL','HIGH'];
function average(xs:readonly number[]):number|null{
 if(!xs.length)return null;
 let m=0;
 for(let i=0;i<xs.length;i++){
  m+=(xs[i]-m)/(i+1);
  if(!Number.isFinite(m))throw Error('Nonfinite scenario mean');
 }
 return m;
}
function bucket(name:InteractionGroup['regime'],trades:readonly RiskPathTrade[],costs:readonly number[]):InteractionGroup{
 const weeks=new Set(trades.map(t=>Math.floor((t.entryAt-MONDAY)/WEEK))).size;
 return {regime:name,trades:trades.length,eventWeeks:weeks,
  status:trades.length>=30&&weeks>=12?'DESCRIPTIVE_ONLY':'INSUFFICIENT_EVIDENCE',
  scenarios:costs.map((roundTripCostBps,j)=>({roundTripCostBps,
   meanNetBps:average(trades.map(t=>t.netBps[j])),
   meanNetR:average(trades.map(t=>t.netR[j]))}))};
}
export function auditConfluenceVolatilityInteraction(
 report:RiskPathReport,volatility:VolatilityRegimeReport
):VolatilityInteractionAudit{
 // Independently validate source, price, chronology and frozen cost arithmetic.
 summarizeRiskPathCostRegimes(report);
 if(volatility?.engine!=='causal-1h-natr-terciles-v1'||volatility.frame!=='1H'||
    volatility.atrPeriod!==14||volatility.baselineBars!==24||
    volatility.datasetId!==report.datasetId||volatility.instrument!==report.instrument)
  throw Error('Mismatched frozen source or volatility protocol');
 if(!Array.isArray(volatility.labels)||volatility.labels.length>1_000_000||
    !Number.isSafeInteger(volatility.inputCandles)||volatility.inputCandles<0||
    !Number.isSafeInteger(volatility.labelled)||volatility.labelled!==volatility.labels.length||
    !Number.isSafeInteger(volatility.unlabelled)||volatility.unlabelled<0||
    volatility.inputCandles!==volatility.labelled+volatility.unlabelled)
  throw Error('Invalid volatility label accounting');
 const counts:Record<VolatilityRegime,number>={LOW:0,NORMAL:0,HIGH:0};
 const byEntry=new Map<number,VolatilityRegime>();
 let previous=-Infinity;
 for(const l of volatility.labels){
  if(!Number.isSafeInteger(l.candleOpenAt)||l.candleOpenAt<0||
     l.candleOpenAt<=previous||l.candleOpenAt%H!==0||
     l.observedAt!==l.candleOpenAt+H||l.eligibleFrom!==l.observedAt||
     !Number.isFinite(l.normalizedAtrBps)||l.normalizedAtrBps<=0||
     !Number.isFinite(l.trailingPercentile)||l.trailingPercentile<0||l.trailingPercentile>1||
     !regimes.includes(l.regime))throw Error('Invalid or noncausal volatility label');
  const expected=l.trailingPercentile<1/3?'LOW':l.trailingPercentile>2/3?'HIGH':'NORMAL';
  if(l.regime!==expected)throw Error('Volatility regime does not match frozen rank');
  counts[l.regime]++;
  byEntry.set(l.eligibleFrom,l.regime);
  previous=l.candleOpenAt;
 }
 if(!volatility.counts||regimes.some(k=>!Number.isSafeInteger(volatility.counts[k])||
   volatility.counts[k]!==counts[k]))throw Error('Volatility regime counts mismatch');
 const grouped:Record<InteractionGroup['regime'],RiskPathTrade[]>={LOW:[],NORMAL:[],HIGH:[],UNLABELLED:[]};
 for(const trade of report.trades){
  // A confirmation-candle label is known at this next-bar entry, not before.
  const regime=byEntry.get(trade.entryAt)||'UNLABELLED';
  grouped[regime].push(trade);
 }
 const names:readonly InteractionGroup['regime'][]=['LOW','NORMAL','HIGH','UNLABELLED'];
 const groups:InteractionGroup[]=names.map(k=>bucket(k,grouped[k],report.config.roundTripCostsBps));
 const matched=report.trades.length-grouped.UNLABELLED.length;
 return {engine:'sweep-volatility-interaction-audit-v1',datasetId:report.datasetId,
  instrument:report.instrument,trades:report.trades.length,matched,
  unlabelled:grouped.UNLABELLED.length,groups,
  status:groups.slice(0,3).every(g=>g.status==='DESCRIPTIVE_ONLY')&&matched===report.trades.length?
   'DESCRIPTIVE_ONLY':'INSUFFICIENT_EVIDENCE',
  warning:'Frozen descriptive 1H ATR-rank x confluence risk-path join at next-open entry only. UNLABELLED paths are not dropped or assigned zero P&L. Groups are not optimized, independent, statistically significant, or untouched holdouts. Dataset IDs and label receipts are not cryptographic source verification. BID/OHLC fills and flat costs are hypothetical; no actual CFD spread, financing, slippage, quote or order. No profitable edge established.'};
}
