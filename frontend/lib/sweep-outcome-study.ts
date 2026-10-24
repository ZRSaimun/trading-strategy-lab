/**
 * Fixed-horizon, research-only follow-through for causal v3 sweep observations.
 * A result is NOT a trade: no broker quote, financing, leverage, stop or fill model.
 */
import {validStructureSegments} from './structure-quality.ts';
import type {Bar,Detection} from './research.ts';

export type SweepStudyConfig={
 datasetId:string;instrument:string;frame:string;horizonBars:number;costBps:number;
};
export type SweepOutcome={
 observedAt:number;kind:'SELL-SIDE SWEEP'|'BUY-SIDE SWEEP';
 direction:'bullish'|'bearish';entryAt:number;exitAt:number;
 entry:number;exit:number;grossBps:number;netBps:number;
};
export type SweepStudy={
 datasetId:string;instrument:string;frame:string;horizonBars:number;costBps:number;
 completed:SweepOutcome[];pending:number;gapExcluded:number;priceExcluded:number;
 meanNetBps:number|null;positiveFraction:number|null;
 warning:string;
};
const FRAME_SECONDS:Record<string,number>={'1m':60,'3m':180,'5m':300,'15m':900,'30m':1800,'1H':3600,'2H':7200,'4H':14400,'1D':86400,'1W':604800,'1M':0};
function closeTime(bar:Bar,frame:string){
 if(frame==='1M'){
  const d=new Date(bar.time*1000);
  return Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,1)/1000;
 }
 return bar.time+FRAME_SECONDS[frame];
}
export function studySweepOutcomes(bars:readonly Bar[],observations:readonly Detection[],cfg:SweepStudyConfig):SweepStudy{
 if(!cfg.datasetId.trim()||!cfg.instrument.trim())throw Error('Exact dataset and instrument identity required');
 if(!Number.isSafeInteger(cfg.horizonBars)||cfg.horizonBars<1||cfg.horizonBars>100)throw Error('Horizon must be 1–100 completed bars');
 if(!Number.isFinite(cfg.costBps)||cfg.costBps<0||cfg.costBps>10000)throw Error('Round-trip cost must be 0–10000 basis points');
 // Refuse ambiguous event-to-bar mapping. Gaps are allowed, duplicates/reversal are not.
 for(let i=1;i<bars.length;i++)if(bars[i].time<=bars[i-1].time)throw Error('Candles must have strictly increasing timestamps');
 const segments=validStructureSegments(bars,cfg.frame);
 const byClose=new Map<number,number>();
 bars.forEach((b,i)=>{if(segments[i]>=0)byClose.set(closeTime(b,cfg.frame),i)});
 const completed:SweepOutcome[]=[];
 let pending=0,gapExcluded=0,priceExcluded=0;
 const seen=new Set<number>();
 for(const event of observations){
  if(event.kind!=='SELL-SIDE SWEEP'&&event.kind!=='BUY-SIDE SWEEP')continue;
  if(event.rule_version!=='structure-research-v3')throw Error('Only causal v3 observations can be evaluated');
  if(!Number.isSafeInteger(event.observed_at)||!Array.isArray(event.reference_times)||
     event.reference_times.some(t=>!Number.isSafeInteger(t)||t>=event.observed_at))throw Error('Invalid or future-referencing sweep observation');
  const i=byClose.get(event.observed_at);
  if(i===undefined)throw Error('Sweep observation is not on a valid completed candle');
  if(seen.has(event.observed_at))throw Error('Conflicting or duplicate sweep observations at one close');
  seen.add(event.observed_at);
  const end=i+cfg.horizonBars;
  if(end>=bars.length){pending++;continue}
  if(segments[end]!==segments[i]){gapExcluded++;continue}
  const entry=bars[i+1].open,exit=bars[end].close;
  if(!Number.isFinite(entry)||!Number.isFinite(exit)||entry<=0||exit<=0){priceExcluded++;continue}
  const sign=event.kind==='SELL-SIDE SWEEP'?1:-1;
  const grossBps=sign*(exit/entry-1)*10000;
  if(!Number.isFinite(grossBps)||!Number.isFinite(grossBps-cfg.costBps)){priceExcluded++;continue}
  completed.push({observedAt:event.observed_at,kind:event.kind,direction:sign===1?'bullish':'bearish',
    entryAt:bars[i+1].time,exitAt:closeTime(bars[end],cfg.frame),entry,exit,grossBps,netBps:grossBps-cfg.costBps});
 }
 const meanNetBps=completed.length?completed.reduce((sum,e)=>sum+e.netBps,0)/completed.length:null;
 const positiveFraction=completed.length?completed.filter(e=>e.netBps>0).length/completed.length:null;
 return {datasetId:cfg.datasetId,instrument:cfg.instrument,frame:cfg.frame,horizonBars:cfg.horizonBars,costBps:cfg.costBps,
   completed,pending,gapExcluded,priceExcluded,meanNetBps,positiveFraction,
   warning:'Descriptive historical follow-through only, not a backtest or broker fills. Costs are assumptions. Overlapping outcomes are dependent; no claim of predictive edge.'};
}
