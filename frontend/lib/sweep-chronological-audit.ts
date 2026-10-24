/**
 * Strictly retrospective, source-isolated chronological audit of pre-matched
 * sweep/control pairs. Does not establish an untouched holdout or trading edge.
 */
import type {MatchedSweepComparison,MatchedSweepPair} from './sweep-matched-baseline.ts';

export type ChronologicalBoundaries={
 developmentStartUtc:number;
 developmentEndUtc:number;
 validationEndUtc:number;
 holdoutEndUtc:number;
 embargoSeconds:number;
};
export type ChronologicalWindow={
 name:'development'|'validation'|'holdout';startUtc:number;endUtc:number;
 matched:number;weeks:number;
 meanSweepNetBps:number|null;meanControlNetBps:number|null;meanDifferenceBps:number|null;
 status:'INSUFFICIENT_EVIDENCE'|'EXPLORATORY_ONLY';
};
export type ChronologicalAudit={
 datasetId:string;instrument:string;frame:string;horizonBars:number;costBps:number;seed:string;
 boundaries:ChronologicalBoundaries;windows:ChronologicalWindow[];
 outsideRange:number;crossWindowControlExcluded:number;boundaryPurged:number;
 warning:string;
};
const WEEK=604800,MONDAY=345600;
function safeTime(value:number){return Number.isSafeInteger(value)&&value>=0&&value<=8640000000000;}
function mean(sum:number,count:number){return count?sum/count:null;}
function verifyPair(p:MatchedSweepPair){
 const {sweep:s,control:c,differenceBps:d}=p;
 if(![s.observedAt,s.entryAt,s.exitAt,c.observedAt,c.entryAt,c.exitAt].every(safeTime)||
    !(s.observedAt<=s.entryAt&&s.entryAt<s.exitAt&&c.observedAt<=c.entryAt&&c.entryAt<c.exitAt&&
      c.exitAt<=s.observedAt&&c.observedAt<s.observedAt))
  throw Error('Invalid or future-referencing matched pair chronology');
 if(s.kind!==c.kind||s.direction!==c.direction||
    !['SELL-SIDE SWEEP','BUY-SIDE SWEEP'].includes(s.kind)||
    !['bullish','bearish'].includes(s.direction))throw Error('Mismatched sweep/control direction');
 if(![s.netBps,c.netBps,d].every(Number.isFinite)||
    Math.abs((s.netBps-c.netBps)-d)>1e-8*Math.max(1,Math.abs(d)))
  throw Error('Nonfinite or inconsistent paired return');
}
/**
 * Explicit half-open [start,end) chronological windows. Requires the CONTROL
 * as well as the sweep to belong to the window, so a validation/holdout report
 * cannot reuse a development-period outcome as its benchmark. Boundary-crossing
 * labels and optional embargo neighborhoods are purged, not reassigned.
 *
 * This is a post-hoc audit of an already constructed comparison; its holdout
 * is not genuinely untouched if any research choices used that period.
 */
export function auditMatchedSweepsChronologically(
 comparison:MatchedSweepComparison,b:ChronologicalBoundaries
):ChronologicalAudit{
 if(!comparison.datasetId?.trim()||!comparison.instrument?.trim()||!comparison.frame?.trim()||!comparison.seed?.trim())
  throw Error('Exact source, instrument, frame and matching seed required');
 if(!Number.isSafeInteger(comparison.horizonBars)||comparison.horizonBars<1||
    !Number.isFinite(comparison.costBps)||comparison.costBps<0)
  throw Error('Invalid research horizon or cost');
 const times=[b.developmentStartUtc,b.developmentEndUtc,b.validationEndUtc,b.holdoutEndUtc];
 if(!times.every(safeTime)||!(times[0]<times[1]&&times[1]<times[2]&&times[2]<times[3])||
    !Number.isSafeInteger(b.embargoSeconds)||b.embargoSeconds<0||
    b.embargoSeconds*2>=Math.min(times[1]-times[0],times[2]-times[1],times[3]-times[2]))
  throw Error('Invalid predeclared chronological boundaries or embargo');
 if(!Array.isArray(comparison.pairs)||comparison.pairs.length!==comparison.matched||comparison.pairs.length>100000)
  throw Error('Invalid matched pair count');
 const names=['development','validation','holdout'] as const;
 const internal=names.map((name,i)=>({name,startUtc:times[i],endUtc:times[i+1],
  matched:0,sumSweep:0,sumControl:0,sumDifference:0,weeks:new Set<number>()}));
 let outsideRange=0,crossWindowControlExcluded=0,boundaryPurged=0;
 const sweeps=new Set<number>(),controls=new Set<number>();
 for(const p of comparison.pairs){
  verifyPair(p);
  const s=p.sweep,c=p.control;
  if(sweeps.has(s.observedAt)||controls.has(c.observedAt))throw Error('Duplicate matched sweep or control');
  sweeps.add(s.observedAt);controls.add(c.observedAt);
  const w=internal.find(w=>s.observedAt>=w.startUtc&&s.observedAt<w.endUtc);
  if(!w){outsideRange++;continue;}
  if(c.observedAt<w.startUtc||c.exitAt<w.startUtc){crossWindowControlExcluded++;continue;}
  const left=w.startUtc+b.embargoSeconds,right=w.endUtc-b.embargoSeconds;
  if(s.observedAt<left||s.entryAt<left||s.exitAt>=right||c.observedAt<left||c.entryAt<left){
   boundaryPurged++;continue;
  }
  w.matched++;w.sumSweep+=s.netBps;w.sumControl+=c.netBps;w.sumDifference+=p.differenceBps;
  if(![w.sumSweep,w.sumControl,w.sumDifference].every(Number.isFinite))throw Error('Overflowed window return sum');
  w.weeks.add(Math.floor((s.observedAt-MONDAY)/WEEK));
 }
 const windows:ChronologicalWindow[]=internal.map(w=>({
  name:w.name,startUtc:w.startUtc,endUtc:w.endUtc,matched:w.matched,weeks:w.weeks.size,
  meanSweepNetBps:mean(w.sumSweep,w.matched),meanControlNetBps:mean(w.sumControl,w.matched),
  meanDifferenceBps:mean(w.sumDifference,w.matched),
  status:w.matched>=30&&w.weeks.size>=12?'EXPLORATORY_ONLY':'INSUFFICIENT_EVIDENCE'
 }));
 return {datasetId:comparison.datasetId,instrument:comparison.instrument,frame:comparison.frame,
  horizonBars:comparison.horizonBars,costBps:comparison.costBps,seed:comparison.seed,boundaries:{...b},
  windows,outsideRange,crossWindowControlExcluded,boundaryPurged,
  warning:'Retrospective chronological diagnostic, NOT a genuinely untouched holdout, broker fill or trading strategy. Both sweep and prior matured control must lie within each window. Exclusions and overlapping event weeks can bias estimates. No significance, multiple-test correction, verified source UTC offset, bid/ask execution costs or profit claim.'};
}
