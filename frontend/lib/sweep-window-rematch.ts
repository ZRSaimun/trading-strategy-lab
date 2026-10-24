/**
 * Retrospective within-window control matching for the v3 sweep study.
 * Unlike auditing a globally matched sample after the fact, this creates
 * independent historical control pools INSIDE each predeclared time window.
 * Neither this diagnostic nor its "holdout" is untouched forward evidence.
 */
import {compareSweepsToPastHourControls,type MatchedSweepPair} from './sweep-matched-baseline.ts';
import type {SweepStudyConfig} from './sweep-outcome-study.ts';
import type {Bar,Detection} from './research.ts';
import type {ChronologicalBoundaries} from './sweep-chronological-audit.ts';

const FRAMES:Record<string,number>={
 '1m':60,'3m':180,'5m':300,'15m':900,'30m':1800,'1H':3600,
 '2H':7200,'4H':14400,'1D':86400,'1W':604800,'1M':0,
};
const WEEK=604800,MONDAY=345600;
const names=['development','validation','holdout'] as const;
const validTime=(v:number)=>Number.isSafeInteger(v)&&v>=0&&v<=8640000000000;
function closeAt(bar:Bar,frame:string):number{
 if(frame==='1M'){
  const d=new Date(bar.time*1000);
  return Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,1)/1000;
 }
 return bar.time+FRAMES[frame];
}
function mean(numbers:readonly number[]):number|null{
 if(!numbers.length)return null;
 // Incremental mean avoids overflowing an otherwise finite average.
 let value=0;
 for(let i=0;i<numbers.length;i++){
  value+= (numbers[i]-value)/(i+1);
  if(!Number.isFinite(value))throw Error('Nonfinite matched-window mean');
 }
 return value;
}
export type RematchedWindow={
 name:typeof names[number];startUtc:number;endUtc:number;
 sweepObservations:number;matched:number;unmatched:number;pending:number;
 gapExcluded:number;priceExcluded:number;weeks:number;
 meanSweepNetBps:number|null;meanControlNetBps:number|null;meanDifferenceBps:number|null;
 status:'INSUFFICIENT_EVIDENCE'|'EXPLORATORY_ONLY';
 pairs:MatchedSweepPair[];
};
export type WindowRematchReport={
 datasetId:string;instrument:string;frame:string;horizonBars:number;costBps:number;seed:string;
 boundaries:ChronologicalBoundaries;windows:RematchedWindow[];
 warning:string;
};

/**
 * Each window is cut BEFORE matching. Controls must be non-sweep bars in the
 * SAME window and their outcome must mature before the paired sweep closes.
 * Outcome candles cannot cross a boundary/embargo because they are excluded
 * from the corresponding input slice. No historical outcomes select the seed.
 */
export function rematchSweepsWithinWindows(
 bars:readonly Bar[],observations:readonly Detection[],cfg:SweepStudyConfig,
 boundaries:ChronologicalBoundaries,seed='locked-window-controls-v1'
):WindowRematchReport{
 if(!Object.prototype.hasOwnProperty.call(FRAMES,cfg.frame))throw Error('Unsupported timeframe');
 if(!seed.trim()||seed.length>128)throw Error('Predeclared matching seed required');
 const b=boundaries;
 const times=[b.developmentStartUtc,b.developmentEndUtc,b.validationEndUtc,b.holdoutEndUtc];
 if(!times.every(validTime)||!(times[0]<times[1]&&times[1]<times[2]&&times[2]<times[3])||
    !Number.isSafeInteger(b.embargoSeconds)||b.embargoSeconds<0||
    b.embargoSeconds*2>=Math.min(times[1]-times[0],times[2]-times[1],times[3]-times[2]))
  throw Error('Invalid predeclared chronological boundaries or embargo');
 for(let i=0;i<bars.length;i++){
  if(!validTime(bars[i].time)||i>0&&bars[i].time<=bars[i-1].time)
   throw Error('Input candles must have strictly increasing valid UTC timestamps');
 }
 const windows=names.map((name,i):RematchedWindow=>{
  const startUtc=times[i]+b.embargoSeconds,endUtc=times[i+1]-b.embargoSeconds;
  const sample=bars.filter(bar=>{const closed=closeAt(bar,cfg.frame);return closed>=startUtc&&closed<endUtc});
  const sweeps=observations.filter(e=>(e.kind==='SELL-SIDE SWEEP'||e.kind==='BUY-SIDE SWEEP')&&
   e.observed_at>=startUtc&&e.observed_at<endUtc);
  // All in-window sweeps are passed so none can be mistaken for a control.
  const matched=compareSweepsToPastHourControls(sample,sweeps,cfg,seed);
  const weeks=new Set(matched.pairs.map(p=>Math.floor((p.sweep.observedAt-MONDAY)/WEEK)));
  for(const p of matched.pairs){
   if(p.control.observedAt<startUtc||p.control.exitAt>p.sweep.observedAt||
      p.sweep.observedAt<startUtc||p.sweep.exitAt>=endUtc)
    throw Error('Matched label crossed a predeclared window');
  }
  return {name,startUtc,endUtc,sweepObservations:sweeps.length,matched:matched.matched,
   unmatched:matched.unmatched,pending:matched.pending,gapExcluded:matched.gapExcluded,
   priceExcluded:matched.priceExcluded,weeks:weeks.size,
   meanSweepNetBps:mean(matched.pairs.map(p=>p.sweep.netBps)),
   meanControlNetBps:mean(matched.pairs.map(p=>p.control.netBps)),
   meanDifferenceBps:mean(matched.pairs.map(p=>p.differenceBps)),
   status:matched.matched>=30&&weeks.size>=12?'EXPLORATORY_ONLY':'INSUFFICIENT_EVIDENCE',
   pairs:matched.pairs};
 });
 return {datasetId:cfg.datasetId,instrument:cfg.instrument,frame:cfg.frame,
  horizonBars:cfg.horizonBars,costBps:cfg.costBps,seed,boundaries:{...boundaries},windows,
  warning:'Retrospective within-window control matching, NOT a genuinely untouched holdout or a trading strategy. Controls are selected only from prior matured, same-UTC-hour non-sweep observations inside each predeclared window. Sparse samples, calendar closures, source timezone, unknown broker spread/slippage/financing, dependent outcomes and repeated hypothesis search limit inference. No live orders or profit claim.'};
}
