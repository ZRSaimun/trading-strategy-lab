/**
 * Frozen, offline UTC-week sign-symmetry stress for completed confluence paths.
 * This is a descriptive negative-control reference, NOT a significance test.
 */
import type {RiskPathReport} from './sweep-confluence-risk-path.ts';
import {summarizeRiskPathCostRegimes} from './sweep-risk-path-regime-stress.ts';

export type WeekSignSymmetryAudit={
 engine:'sweep-week-sign-symmetry-stress-v1';datasetId:string;instrument:string;
 roundTripCostBps:5;trades:number;utcWeeks:number;
 status:'WITHHELD'|'DESCRIPTIVE_ONLY';withheldReason:'TOO_FEW_TRADES'|'TOO_FEW_WEEKS'|null;
 observedEqualWeekMeanNetR:number|null;
 maxWeekAbsoluteContributionShare:number|null;
 nullAbsoluteTailFraction:number|null;null95ReferenceR:[number,number]|null;
 draws:number;enumeration:'NONE'|'EXACT'|'SEEDED_MONTE_CARLO';
 eligibleForLiveTrading:false;warning:string;
};
const WEEK=604800,MONDAY=345600,SEED=20261024,MONTE_CARLO_DRAWS=8192;
function mean(xs:readonly number[]):number{
 let m=0;
 for(let i=0;i<xs.length;i++){m+=(xs[i]-m)/(i+1);if(!Number.isFinite(m))throw Error('Nonfinite week return')}
 return m;
}
function percentile(sorted:readonly number[],q:number):number{
 const p=(sorted.length-1)*q,lo=Math.floor(p),hi=Math.ceil(p);
 return sorted[lo]+(sorted[hi]-sorted[lo])*(p-lo);
}
export function auditFrozenWeekSignSymmetry(report:RiskPathReport):WeekSignSymmetryAudit{
 // Independent accounting, price, cost and chronology validation first.
 summarizeRiskPathCostRegimes(report);
 const costIndex=report.config.roundTripCostsBps.indexOf(5);
 if(costIndex<0)throw Error('Frozen illustrative 5 bps scenario required');
 const grouped=new Map<number,number[]>();
 for(const t of report.trades){
  const week=Math.floor((t.entryAt-MONDAY)/WEEK);
  const bucket=grouped.get(week)||[];
  bucket.push(t.netR[costIndex]);grouped.set(week,bucket);
 }
 const weeks=[...grouped].sort((a,b)=>a[0]-b[0]).map(([,rs])=>mean(rs));
 if(weeks.length>5200)throw Error('Excessive UTC week count');
 const reason:WeekSignSymmetryAudit['withheldReason']=report.closed<30?'TOO_FEW_TRADES':weeks.length<12?'TOO_FEW_WEEKS':null;
 const base={engine:'sweep-week-sign-symmetry-stress-v1' as const,
  datasetId:report.datasetId,instrument:report.instrument,roundTripCostBps:5 as const,
  trades:report.closed,utcWeeks:weeks.length,eligibleForLiveTrading:false as const,
  warning:'Descriptive sign-symmetry negative-control reference for preselected hypothetical BID/OHLC paths at illustrative 5 bps, NOT a calibrated p-value, confidence interval, proof of independence, prospective inference, or profitable edge. Sign flips assume independent symmetric UTC-week returns and do not correct selection, drift, multiple trials, source authenticity, CFD spreads, financing, slippage or broker execution. No live orders.'};
 if(reason)return {...base,status:'WITHHELD' as const,withheldReason:reason,
  observedEqualWeekMeanNetR:null,maxWeekAbsoluteContributionShare:null,
  nullAbsoluteTailFraction:null,null95ReferenceR:null,draws:0,enumeration:'NONE' as const};
 const observed=mean(weeks);
 const absSum=weeks.reduce((s,v)=>s+Math.abs(v),0);
 const concentration=absSum===0?0:Math.max(...weeks.map(Math.abs))/absSum;
 if(!Number.isFinite(absSum)||!Number.isFinite(concentration))throw Error('Nonfinite week concentration');
 const exact=weeks.length<=16;
 const draws=exact?2**weeks.length:MONTE_CARLO_DRAWS;
 const nullMeans:number[]=[];
 let state=SEED>>>0;
 for(let b=0;b<draws;b++){
  let sum=0;
  for(let i=0;i<weeks.length;i++){
   let flip:boolean;
   if(exact)flip=(Math.floor(b/(2**i))%2)===1;
   else{
    state^=state<<13;state^=state>>>17;state^=state<<5;
    flip=(state>>>0)<2147483648;
   }
   sum+=(flip?-1:1)*weeks[i];
  }
  const v=sum/weeks.length;
  if(!Number.isFinite(v))throw Error('Nonfinite null draw');
  nullMeans.push(v);
 }
 const epsilon=1e-12*Math.max(1,Math.abs(observed));
 const extreme=nullMeans.filter(v=>Math.abs(v)+epsilon>=Math.abs(observed)).length;
 nullMeans.sort((a,b)=>a-b);
 return {...base,status:'DESCRIPTIVE_ONLY',withheldReason:null,
  observedEqualWeekMeanNetR:observed,maxWeekAbsoluteContributionShare:concentration,
  nullAbsoluteTailFraction:extreme/draws,
  null95ReferenceR:[percentile(nullMeans,.025),percentile(nullMeans,.975)],
  draws,enumeration:exact?'EXACT':'SEEDED_MONTE_CARLO'};
}
