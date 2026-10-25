/**
 * Predeclared, week-paired volatility interaction diagnostic for research only.
 * Contrasts are fixed; no ranking, threshold search, p-values or trading orders.
 */
import type {RiskPathReport} from './sweep-confluence-risk-path.ts';
import type {VolatilityRegimeReport,VolatilityRegime} from './causal-volatility-regime.ts';
import {auditConfluenceVolatilityInteraction} from './sweep-volatility-interaction-audit.ts';

export type FrozenVolatilityContrast={
  first:VolatilityRegime;second:VolatilityRegime;
  sharedUtcWeeks:number;firstSharedTrades:number;secondSharedTrades:number;
  status:'WITHHELD'|'DESCRIPTIVE_ONLY';
  pairedWeekMeanDifferenceR:number|null;
  bonferroniBootstrapIntervalR:[number,number]|null;
  withheldReason:'UNLABELLED_PATHS'|'TOO_FEW_SHARED_WEEKS'|'TOO_FEW_SHARED_TRADES'|null;
};
export type FrozenVolatilityContrastAudit={
  engine:'sweep-volatility-paired-week-audit-v1';datasetId:string;instrument:string;
  roundTripCostBps:5;comparisonCount:3;familywiseAlpha:0.05;
  bootstrapSamples:3000;unlabelledPaths:number;
  contrasts:FrozenVolatilityContrast[];eligibleForLiveTrading:false;
  warning:string;
};
const WEEK=604800,MONDAY=345600,SAMPLES=3000;
const PAIRS:readonly (readonly [VolatilityRegime,VolatilityRegime])[]=[
  ['LOW','NORMAL'],['HIGH','NORMAL'],['HIGH','LOW']
];
function mean(values:readonly number[]):number{
  let m=0;
  for(let i=0;i<values.length;i++){
    m+=(values[i]-m)/(i+1);
    if(!Number.isFinite(m))throw Error('Nonfinite week mean');
  }
  return m;
}
function percentile(sorted:readonly number[],p:number):number{
  const x=p*(sorted.length-1),lo=Math.floor(x),hi=Math.ceil(x);
  return sorted[lo]+(sorted[hi]-sorted[lo])*(x-lo);
}
function interval(weeklyDifferences:readonly number[],pairIndex:number):[number,number]{
  // Deterministic week-cluster resampling; paired within each UTC week.
  let seed=(20261024+Math.imul(pairIndex+1,0x9e3779b9))>>>0;
  const draws:number[]=[];
  for(let b=0;b<SAMPLES;b++){
    let total=0;
    for(let k=0;k<weeklyDifferences.length;k++){
      seed^=seed<<13;seed^=seed>>>17;seed^=seed<<5;
      total+=weeklyDifferences[(seed>>>0)%weeklyDifferences.length];
    }
    const v=total/weeklyDifferences.length;
    if(!Number.isFinite(v))throw Error('Nonfinite bootstrap replicate');
    draws.push(v);
  }
  draws.sort((a,b)=>a-b);
  // 3 fixed comparisons: 98.333...% marginal percentile intervals.
  const tail=0.05/(2*PAIRS.length);
  return [percentile(draws,tail),percentile(draws,1-tail)];
}
export function auditFrozenVolatilityPairedWeeks(
  report:RiskPathReport,volatility:VolatilityRegimeReport
):FrozenVolatilityContrastAudit{
  // Reuse the full independent risk-path and volatility metadata checks.
  const verified=auditConfluenceVolatilityInteraction(report,volatility);
  const costIndex=report.config.roundTripCostsBps.indexOf(5);
  if(costIndex<0)throw Error('Frozen 5 bps illustrative scenario is required');
  const labels=new Map(volatility.labels.map(l=>[l.eligibleFrom,l.regime] as const));
  const weekly=new Map<number,Record<VolatilityRegime,number[]>>();
  for(const trade of report.trades){
    const regime=labels.get(trade.entryAt);
    if(!regime)continue; // Unlabelled count is retained; no zero imputation.
    const week=Math.floor((trade.entryAt-MONDAY)/WEEK);
    let bucket=weekly.get(week);
    if(!bucket){bucket={LOW:[],NORMAL:[],HIGH:[]};weekly.set(week,bucket)}
    bucket[regime].push(trade.netR[costIndex]);
  }
  const contrasts:FrozenVolatilityContrast[]=PAIRS.map(([first,second],pairIndex):FrozenVolatilityContrast=>{
    const differences:number[]=[];
    let firstSharedTrades=0,secondSharedTrades=0;
    for(const bucket of weekly.values()){
      if(!bucket[first].length||!bucket[second].length)continue;
      firstSharedTrades+=bucket[first].length;
      secondSharedTrades+=bucket[second].length;
      differences.push(mean(bucket[first])-mean(bucket[second]));
    }
    const withheldReason:FrozenVolatilityContrast['withheldReason']=verified.unlabelled>0?'UNLABELLED_PATHS':
      differences.length<12?'TOO_FEW_SHARED_WEEKS':
      firstSharedTrades<30||secondSharedTrades<30?'TOO_FEW_SHARED_TRADES':null;
    return {first,second,sharedUtcWeeks:differences.length,
      firstSharedTrades,secondSharedTrades,
      status:withheldReason?'WITHHELD':'DESCRIPTIVE_ONLY',
      pairedWeekMeanDifferenceR:withheldReason?null:mean(differences),
      bonferroniBootstrapIntervalR:withheldReason?null:interval(differences,pairIndex),
      withheldReason};
  });
  return {engine:'sweep-volatility-paired-week-audit-v1',
    datasetId:report.datasetId,instrument:report.instrument,
    roundTripCostBps:5,comparisonCount:3,familywiseAlpha:0.05,
    bootstrapSamples:SAMPLES,unlabelledPaths:verified.unlabelled,
    contrasts,eligibleForLiveTrading:false,
    warning:'Three predeclared paired-UTC-week regime differences in hypothetical net R at illustrative 5 bps. Equal weight per shared week; no unmatched-week extrapolation. Deterministic week-bootstrap percentile intervals use Bonferroni 3-way adjustment but are descriptive only, not calibrated inference on inspected archives. Self-asserted archive identity/freeze, BID/OHLC fills, costs and regimes are not independently authenticated. No live quote, order, verified profitable edge or trading authorization.'};
}
