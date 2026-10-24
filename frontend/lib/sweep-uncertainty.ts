/**
 * Deterministic, week-clustered descriptive uncertainty for matched sweep pairs.
 * No p-value, broker execution or claim of a trading edge is produced.
 */
import type {MatchedSweepComparison} from './sweep-matched-baseline.ts';

export type SweepUncertainty={
 datasetId:string;instrument:string;frame:string;seed:string;
 matched:number;weeks:number;meanDifferenceBps:number|null;
 lower95Bps:number|null;upper95Bps:number|null;
 status:'INSUFFICIENT_EVIDENCE'|'DESCRIPTIVE_ONLY';
 warning:string;
};
const WEEK=604800;
const MONDAY=345600;
const REPLICATES=2000;
function hash32(value:string){
 let h=2166136261;
 for(let i=0;i<value.length;i++)h=Math.imul(h^value.charCodeAt(i),16777619);
 return (h>>>0)||0x9e3779b9;
}
function quantile(sorted:readonly number[],q:number){
 const x=(sorted.length-1)*q,lo=Math.floor(x),hi=Math.ceil(x);
 return sorted[lo]+(sorted[hi]-sorted[lo])*(x-lo);
}
/**
 * Resample whole UTC Monday-starting calendar-week clusters, preserving
 * within-week event overlap. This does not account for dependence between
 * weeks or the bias from searching many strategies/seeds.
 */
export function estimateSweepDifferenceUncertainty(
 comparison:MatchedSweepComparison,seed='locked-week-bootstrap-v1'
):SweepUncertainty{
 if(!comparison.datasetId?.trim()||!comparison.instrument?.trim()||!comparison.frame?.trim())
  throw Error('Exact dataset, instrument and frame identity required');
 if(!seed.trim()||seed.length>128)throw Error('Predeclared bootstrap seed required');
 if(!Array.isArray(comparison.pairs)||comparison.pairs.length!==comparison.matched||comparison.pairs.length>100000)
  throw Error('Invalid matched pair count');
 const seen=new Set<number>();
 const clusters=new Map<number,{sum:number;count:number}>();
 let total=0;
 for(const p of comparison.pairs){
  const s=p.sweep,c=p.control;
  if(!Number.isSafeInteger(s.observedAt)||s.observedAt<0||
     !Number.isSafeInteger(c.observedAt)||c.observedAt<0||
     !Number.isSafeInteger(c.exitAt)||!Number.isSafeInteger(s.exitAt)||
     c.observedAt>=s.observedAt||c.exitAt> s.observedAt||c.exitAt<=c.observedAt||
     s.exitAt<=s.observedAt||seen.has(s.observedAt)||s.kind!==c.kind||s.direction!==c.direction)
   throw Error('Invalid or duplicate causal matched pair chronology');
  if(!Number.isFinite(s.netBps)||!Number.isFinite(c.netBps)||!Number.isFinite(p.differenceBps)||
     Math.abs((s.netBps-c.netBps)-p.differenceBps)>1e-8*Math.max(1,Math.abs(p.differenceBps)))
   throw Error('Nonfinite or inconsistent matched return');
  seen.add(s.observedAt);
  total+=p.differenceBps;
  if(!Number.isFinite(total))throw Error('Overflowed paired return sum');
  const week=Math.floor((s.observedAt-MONDAY)/WEEK);
  const group=clusters.get(week)||{sum:0,count:0};
  group.sum+=p.differenceBps;group.count++;
  if(!Number.isFinite(group.sum))throw Error('Overflowed weekly return sum');
  clusters.set(week,group);
 }
 const matched=comparison.pairs.length,weeks=clusters.size;
 const meanDifferenceBps=matched?total/matched:null;
 if(meanDifferenceBps!==null&&!Number.isFinite(meanDifferenceBps))throw Error('Overflowed mean');
 const common={datasetId:comparison.datasetId,instrument:comparison.instrument,frame:comparison.frame,
  seed,matched,weeks,meanDifferenceBps};
 const warning='Research-only paired difference. UTC-week cluster bootstrap assumes independent weeks, does not fix timezone, bid/ask costs, market regimes, selection bias, multiple testing or missing forward validation. Not executable profit.';
 if(matched<30||weeks<12)return {...common,lower95Bps:null,upper95Bps:null,status:'INSUFFICIENT_EVIDENCE',warning};
 const groups=[...clusters.entries()].sort((a,b)=>a[0]-b[0]).map(([,v])=>v);
 let state=hash32([comparison.datasetId,comparison.instrument,comparison.frame,comparison.seed,seed].join('|'));
 const draw=()=>{state^=state<<13;state^=state>>>17;state^=state<<5;return (state>>>0)/4294967296};
 const estimates:number[]=[];
 for(let rep=0;rep<REPLICATES;rep++){
  let sum=0,count=0;
  for(let k=0;k<weeks;k++){
   const g=groups[Math.floor(draw()*weeks)];sum+=g.sum;count+=g.count;
  }
  if(count===0||!Number.isFinite(sum/count))throw Error('Invalid bootstrap replicate');
  estimates.push(sum/count);
 }
 estimates.sort((a,b)=>a-b);
 return {...common,lower95Bps:quantile(estimates,.025),upper95Bps:quantile(estimates,.975),
  status:'DESCRIPTIVE_ONLY',warning};
}
