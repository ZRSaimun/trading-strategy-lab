/**
 * Retrospective, non-executing friction sensitivity for past-only matched sweeps.
 * Extra round-trip bps are fixed illustrative costs, not executable broker quotes.
 * No strategy selection, optimisation, holdout certification, or order submission.
 */
import type {MatchedSweepComparison,MatchedSweepPair} from './sweep-matched-baseline.ts';

const WEEK_SECONDS=604800;
const MONDAY_EPOCH_SECONDS=345600;
const MAX_PAIRS=100000;
export const PAIRED_FRICTION_SCENARIOS=[
 {id:'unchanged',sweepExtraBps:0,controlExtraBps:0},
 {id:'symmetric_plus_5',sweepExtraBps:5,controlExtraBps:5},
 {id:'sweep_plus_2',sweepExtraBps:2,controlExtraBps:0},
 {id:'sweep_plus_5',sweepExtraBps:5,controlExtraBps:0},
 {id:'sweep_plus_10',sweepExtraBps:10,controlExtraBps:0},
] as const;
export type PairedFrictionRow={
 id:typeof PAIRED_FRICTION_SCENARIOS[number]['id'];
 sweepTotalCostBps:number;controlTotalCostBps:number;
 eventMeanSweepNetBps:number|null;eventMeanControlNetBps:number|null;
 eventMeanDifferenceBps:number|null;equalWeekMeanDifferenceBps:number|null;
 positiveWeekFraction:number|null;
};
export type PairedFrictionAudit={
 datasetId:string;instrument:string;frame:string;horizonBars:number;seed:string;
 matched:number;activeUtcWeeks:number;baselineCostBps:number;
 status:'INSUFFICIENT_EVIDENCE'|'DESCRIPTIVE_ONLY';
 rows:PairedFrictionRow[];
 /** Null unless the observed baseline event-weighted difference is strictly positive. */
 eventWeightedBreakEvenExtraSweepBps:number|null;
 warning:string;
};
const safeTime=(n:number)=>Number.isSafeInteger(n)&&n>=0&&n<=8640000000000;
const close=(a:number,b:number)=>Math.abs(a-b)<=1e-8*Math.max(1,Math.abs(a),Math.abs(b));
const avg=(s:number,n:number)=>n?s/n:null;
function validateOutcome(pair:MatchedSweepPair,baselineCostBps:number){
 const {sweep:s,control:c,differenceBps:d}=pair;
 if(![s.observedAt,s.entryAt,s.exitAt,c.observedAt,c.entryAt,c.exitAt].every(safeTime)||
    !(c.observedAt<=c.entryAt&&c.entryAt<c.exitAt&&c.exitAt<=s.observedAt&&
      s.observedAt<=s.entryAt&&s.entryAt<s.exitAt))
  throw Error('Invalid or future-dependent matched outcome chronology');
 if(s.kind!==c.kind||s.direction!==c.direction||
    !['SELL-SIDE SWEEP','BUY-SIDE SWEEP'].includes(s.kind)||
    s.direction!==(s.kind==='SELL-SIDE SWEEP'?'bullish':'bearish'))
  throw Error('Invalid paired direction or sweep type');
 for(const x of [s,c]){
  if(![x.entry,x.exit,x.grossBps,x.netBps].every(Number.isFinite)||x.entry<=0||x.exit<=0)
   throw Error('Invalid price or return');
  const expected=(x.direction==='bullish'?1:-1)*(x.exit/x.entry-1)*10000;
  if(!Number.isFinite(expected)||!close(x.grossBps,expected)||!close(x.netBps,x.grossBps-baselineCostBps))
   throw Error('Inconsistent source price or round-trip cost arithmetic');
 }
 if(!Number.isFinite(d)||!close(d,s.netBps-c.netBps))
  throw Error('Inconsistent paired difference');
}
/** The fixed stress grid deliberately changes costs, never matched membership. */
export function auditMatchedSweepFriction(comparison:MatchedSweepComparison):PairedFrictionAudit{
 if(!comparison.datasetId?.trim()||!comparison.instrument?.trim()||!comparison.frame?.trim()||
    !comparison.seed?.trim())throw Error('Exact source identity and locked matching seed required');
 if(!Number.isSafeInteger(comparison.horizonBars)||comparison.horizonBars<1||
    !Number.isFinite(comparison.costBps)||comparison.costBps<0||comparison.costBps>10000)
  throw Error('Invalid horizon or baseline round-trip cost');
 if(!Array.isArray(comparison.pairs)||!Number.isSafeInteger(comparison.matched)||
    comparison.matched!==comparison.pairs.length||comparison.matched>MAX_PAIRS)
  throw Error('Invalid paired sample size');
 const pairs=[...comparison.pairs].sort((a,b)=>a.sweep.observedAt-b.sweep.observedAt);
 const sweepTimes=new Set<number>(),controlTimes=new Set<number>();
 const weekly=new Map<number,{sweep:number;control:number;count:number}>();
 let sweepSum=0,controlSum=0,diffSum=0;
 for(const pair of pairs){
  validateOutcome(pair,comparison.costBps);
  const {sweep:s,control:c,differenceBps:d}=pair;
  if(sweepTimes.has(s.observedAt)||controlTimes.has(c.observedAt))
   throw Error('Duplicate matched sweep or control');
  sweepTimes.add(s.observedAt);controlTimes.add(c.observedAt);
  sweepSum+=s.netBps;controlSum+=c.netBps;diffSum+=d;
  const week=Math.floor((s.observedAt-MONDAY_EPOCH_SECONDS)/WEEK_SECONDS);
  const w=weekly.get(week)??{sweep:0,control:0,count:0};
  w.sweep+=s.netBps;w.control+=c.netBps;w.count++;
  weekly.set(week,w);
  if(![sweepSum,controlSum,diffSum,w.sweep,w.control].every(Number.isFinite))
   throw Error('Overflowed historical return aggregation');
 }
 for(const [observedAt] of weekly){if(!Number.isSafeInteger(observedAt))throw Error('Invalid UTC week');}
 for(const [value,computed] of [
  [comparison.meanSweepNetBps,avg(sweepSum,pairs.length)],
  [comparison.meanControlNetBps,avg(controlSum,pairs.length)],
  [comparison.meanDifferenceBps,avg(diffSum,pairs.length)],
 ] as const){if(value!==null&&(!Number.isFinite(value)||computed===null||!close(value,computed))||
                  value===null&&computed!==null)throw Error('Inconsistent source aggregate');}
 const n=pairs.length,weeks=weekly.size;
 const groups=[...weekly.entries()].sort((a,b)=>a[0]-b[0]).map(([,w])=>w);
 const rows=PAIRED_FRICTION_SCENARIOS.map(sc=>{
  const sweepTotalCostBps=comparison.costBps+sc.sweepExtraBps;
  const controlTotalCostBps=comparison.costBps+sc.controlExtraBps;
  const differenceExtra=sc.sweepExtraBps-sc.controlExtraBps;
  const eventMeanSweepNetBps=n?sweepSum/n-sc.sweepExtraBps:null;
  const eventMeanControlNetBps=n?controlSum/n-sc.controlExtraBps:null;
  const eventMeanDifferenceBps=n?diffSum/n-differenceExtra:null;
  let equalWeekMeanDifferenceBps:number|null=null,positiveWeekFraction:number|null=null;
  if(weeks){
   let weekSum=0,positive=0;
   for(const w of groups){
    const diff=(w.sweep-w.control)/w.count-differenceExtra;
    weekSum+=diff;
    if(diff>0)positive++;
   }
   equalWeekMeanDifferenceBps=weekSum/weeks;
   positiveWeekFraction=positive/weeks;
  }
  if([sweepTotalCostBps,controlTotalCostBps,eventMeanSweepNetBps,eventMeanControlNetBps,
      eventMeanDifferenceBps,equalWeekMeanDifferenceBps,positiveWeekFraction]
      .some(x=>x!==null&&!Number.isFinite(x)))throw Error('Nonfinite stress result');
  return {id:sc.id,sweepTotalCostBps,controlTotalCostBps,eventMeanSweepNetBps,
    eventMeanControlNetBps,eventMeanDifferenceBps,equalWeekMeanDifferenceBps,positiveWeekFraction};
 });
 return {datasetId:comparison.datasetId,instrument:comparison.instrument,frame:comparison.frame,
  horizonBars:comparison.horizonBars,seed:comparison.seed,matched:n,activeUtcWeeks:weeks,
  baselineCostBps:comparison.costBps,status:n>=30&&weeks>=12?'DESCRIPTIVE_ONLY':'INSUFFICIENT_EVIDENCE',
  rows,eventWeightedBreakEvenExtraSweepBps:n>=30&&weeks>=12&&diffSum/n>0?diffSum/n:null,
  warning:'Offline, retrospective, fixed additive round-trip bps sensitivity only. Identical added costs cancel in matched differences; asymmetric costs may not. Does not reprice fills, stops, position size, financing, slippage tails or quote latency. Equal-week and event means are descriptive, not calibrated inference. Unverified data provenance/timebase, matched selection, overlapping outcomes and repeated research prevent claims of edge or executable profit.'};
}
