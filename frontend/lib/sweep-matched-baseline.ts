/**
 * Predeclared, UTC-hour-matched historical control for causal v3 sweeps.
 * Every control's complete outcome must have matured BEFORE its paired sweep
 * observation. This is a retrospective descriptive comparison, not a trade.
 */
import {validStructureSegments} from './structure-quality.ts';
import {studySweepOutcomes,type SweepOutcome,type SweepStudyConfig} from './sweep-outcome-study.ts';
import type {Bar,Detection} from './research.ts';

export type MatchedSweepPair={sweep:SweepOutcome;control:SweepOutcome;differenceBps:number};
export type MatchedSweepComparison={
 datasetId:string;instrument:string;frame:string;horizonBars:number;costBps:number;seed:string;
 matched:number;unmatched:number;pending:number;gapExcluded:number;priceExcluded:number;
 pairs:MatchedSweepPair[];
 meanSweepNetBps:number|null;meanControlNetBps:number|null;meanDifferenceBps:number|null;
 warning:string;
};
const FRAME_SECONDS:Record<string,number>={'1m':60,'3m':180,'5m':300,'15m':900,'30m':1800,'1H':3600,'2H':7200,'4H':14400,'1D':86400,'1W':604800,'1M':0};
function closeAt(b:Bar,frame:string):number{
 if(frame==='1M'){
  const d=new Date(b.time*1000);
  return Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,1)/1000;
 }
 return b.time+FRAME_SECONDS[frame];
}
function hash32(s:string):number{
 let h=2166136261;
 for(let i=0;i<s.length;i++)h=Math.imul(h^s.charCodeAt(i),16777619);
 return h>>>0;
}
function eligibleBefore(indices:readonly number[],bars:readonly Bar[],frame:string,horizon:number,observedAt:number):number{
 let lo=0,hi=indices.length;
 while(lo<hi){const mid=(lo+hi)>>>1;
  if(closeAt(bars[indices[mid]+horizon],frame)<=observedAt)lo=mid+1;
  else hi=mid;
 }
 return lo;
}
const mean=(numbers:readonly number[])=>numbers.length?numbers.reduce((s,n)=>s+n,0)/numbers.length:null;

/**
 * Match each completed sweep to one unique historical non-sweep observation
 * at the same UTC close-hour. A seeded deterministic choice is made from
 * controls whose entire fixed-horizon label matured by the sweep's close.
 * This excludes future outcomes from both signal and control selection.
 * No price-dependent selection, optimization or performance filter is used.
 */
export function compareSweepsToPastHourControls(
 bars:readonly Bar[],observations:readonly Detection[],cfg:SweepStudyConfig,seed='fixed-baseline-v1'
):MatchedSweepComparison{
 if(!seed.trim()||seed.length>128)throw Error('Predeclared baseline seed required (1–128 characters)');
 const study=studySweepOutcomes(bars,observations,cfg);
 const segments=validStructureSegments(bars,cfg.frame);
 const sweepCloses=new Set(observations.filter(e=>e.kind==='SELL-SIDE SWEEP'||e.kind==='BUY-SIDE SWEEP').map(e=>e.observed_at));
 const pools:number[][]=Array.from({length:24},()=>[]);
 for(let i=0;i+cfg.horizonBars<bars.length;i++){
  if(segments[i]<0||segments[i+cfg.horizonBars]!==segments[i])continue;
  const observedAt=closeAt(bars[i],cfg.frame);
  if(sweepCloses.has(observedAt))continue;
  const entry=bars[i+1].open,exit=bars[i+cfg.horizonBars].close;
  if(!Number.isFinite(entry)||!Number.isFinite(exit)||entry<=0||exit<=0||!Number.isFinite((exit/entry-1)*10000))continue;
  pools[new Date(observedAt*1000).getUTCHours()].push(i);
 }
 const used=new Set<number>(),pairs:MatchedSweepPair[]=[];
 let unmatched=0;
 for(const sweep of [...study.completed].sort((a,b)=>a.observedAt-b.observedAt)){
  const hour=new Date(sweep.observedAt*1000).getUTCHours();
  const pool=pools[hour];
  const available=eligibleBefore(pool,bars,cfg.frame,cfg.horizonBars,sweep.observedAt);
  if(!available){unmatched++;continue}
  const first=hash32([cfg.datasetId,cfg.instrument,cfg.frame,seed,sweep.observedAt,sweep.kind].join('|'))%available;
  let chosen=-1;
  for(let step=0;step<available;step++){
   const index=pool[(first+step)%available];
   if(!used.has(index)){chosen=index;break}
  }
  if(chosen<0){unmatched++;continue}
  used.add(chosen);
  const entry=bars[chosen+1].open,exit=bars[chosen+cfg.horizonBars].close;
  const sign=sweep.direction==='bullish'?1:-1;
  const grossBps=sign*(exit/entry-1)*10000;
  const control:SweepOutcome={observedAt:closeAt(bars[chosen],cfg.frame),kind:sweep.kind,direction:sweep.direction,
   entryAt:bars[chosen+1].time,exitAt:closeAt(bars[chosen+cfg.horizonBars],cfg.frame),
   entry,exit,grossBps,netBps:grossBps-cfg.costBps};
  pairs.push({sweep,control,differenceBps:sweep.netBps-control.netBps});
 }
 return {datasetId:cfg.datasetId,instrument:cfg.instrument,frame:cfg.frame,horizonBars:cfg.horizonBars,costBps:cfg.costBps,seed,
  matched:pairs.length,unmatched,pending:study.pending,gapExcluded:study.gapExcluded,priceExcluded:study.priceExcluded,pairs,
  meanSweepNetBps:mean(pairs.map(p=>p.sweep.netBps)),meanControlNetBps:mean(pairs.map(p=>p.control.netBps)),
  meanDifferenceBps:mean(pairs.map(p=>p.differenceBps)),
  warning:'Retrospective descriptive control, NOT a trading backtest or causal effect. Matched controls are from prior matured history at the same UTC close-hour; some sweeps have no match. Outcomes can overlap and are dependent. Timezone, session mix, regimes, costs, spreads and multiple testing remain unverified. No evidence of executable profit.'};
}
