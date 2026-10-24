/**
 * Predeclared, causal and deliberately restrictive sweep -> same-close MSS/FVG
 * confluence study. Research observations only: no broker quotes or orders.
 *
 * A structure break is a proxy for MSS, NOT proof of a market-structure shift.
 * We intentionally require directional break and FVG at the SAME completed
 * confirmation close. The earliest qualifying close is used, never selected
 * by its subsequent return. Signal enters at NEXT candle open for a fixed
 * horizon; these directional outcomes are not executable trading P&L.
 */
import {validStructureSegments} from './structure-quality.ts';
import type {Bar,Detection} from './research.ts';

const SECONDS:Record<string,number>={
 '1m':60,'3m':180,'5m':300,'15m':900,'30m':1800,'1H':3600,
 '2H':7200,'4H':14400,'1D':86400,'1W':604800,'1M':0,
};
const SWEEP=['SELL-SIDE SWEEP','BUY-SIDE SWEEP'] as const;
const RELATED=new Set<string>([...SWEEP,'BULLISH STRUCTURE BREAK','BEARISH STRUCTURE BREAK','BULLISH FVG','BEARISH FVG']);
export type ConfluenceConfig={
 datasetId:string;instrument:string;frame:string;maxConfirmationBars:number;
 horizonBars:number;costScenariosBps:readonly number[];
};
export type ConfluenceSignal={
 sweepAt:number;confirmationAt:number;direction:'bullish'|'bearish';
 entryAt:number;exitAt:number;entry:number;exit:number;
 grossBps:number;netBps:readonly number[];
};
export type ConfluenceStudy={
 engine:'sweep-mss-fvg-same-close-v1';datasetId:string;instrument:string;frame:string;
 maxConfirmationBars:number;horizonBars:number;costScenariosBps:readonly number[];
 sweepCount:number;confirmed:number;completed:number;unconfirmed:number;
 confirmationReused:number;pending:number;gapExcluded:number;priceExcluded:number;
 signals:ConfluenceSignal[];meanNetBps:(number|null)[];
 warning:string;
};
function closeAt(bar:Bar,frame:string):number{
 if(frame==='1M'){
  const d=new Date(bar.time*1000);
  return Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,1)/1000;
 }
 return bar.time+SECONDS[frame];
}
function mean(values:readonly number[]):number|null{
 if(!values.length)return null;
 let m=0;
 for(let i=0;i<values.length;i++){
  m+=(values[i]-m)/(i+1);
  if(!Number.isFinite(m))throw Error('Nonfinite outcome mean');
 }
 return m;
}
export function studySweepConfluence(
 bars:readonly Bar[],observations:readonly Detection[],cfg:ConfluenceConfig
):ConfluenceStudy{
 if(!cfg.datasetId?.trim()||!cfg.instrument?.trim())throw Error('Exact source identity required');
 if(!Object.prototype.hasOwnProperty.call(SECONDS,cfg.frame))throw Error('Unsupported timeframe');
 if(!Number.isSafeInteger(cfg.maxConfirmationBars)||cfg.maxConfirmationBars<1||cfg.maxConfirmationBars>12)
  throw Error('Confirmation window must be 1–12 bars');
 if(!Number.isSafeInteger(cfg.horizonBars)||cfg.horizonBars<1||cfg.horizonBars>100)
  throw Error('Horizon must be 1–100 bars');
 if(!Array.isArray(cfg.costScenariosBps)||cfg.costScenariosBps.length<1||cfg.costScenariosBps.length>10||
    cfg.costScenariosBps.some((c,i)=>!Number.isFinite(c)||c<0||c>10000||i>0&&c<=cfg.costScenariosBps[i-1]))
  throw Error('Cost scenarios must be sorted, unique and within 0–10000 bps');
 if(bars.length>1_000_000||observations.length>1_000_000)throw Error('Research input exceeds bounded limit');
 for(let i=1;i<bars.length;i++)if(bars[i].time<=bars[i-1].time)
  throw Error('Candles must be strictly increasing');
 const segments=validStructureSegments(bars,cfg.frame);
 const byClose=new Map<number,number>(),byOpen=new Map<number,number>();
 bars.forEach((b,i)=>{
  if(segments[i]>=0){byClose.set(closeAt(b,cfg.frame),i);byOpen.set(b.time,i)}
 });
 const events=new Map<number,Set<string>>();
 const sweeps:{index:number;at:number;kind:string}[]=[];
 for(const e of observations){
  if(!RELATED.has(e.kind))continue;
  if(e.rule_version!=='structure-research-v3'||!Number.isSafeInteger(e.observed_at)||
    !Array.isArray(e.reference_times)||!e.reference_times.length)
   throw Error('Only valid causal v3 structural events are accepted');
  const i=byClose.get(e.observed_at);
  if(i===undefined||e.reference_times.some(t=>{
    const j=byOpen.get(t);
    return !Number.isSafeInteger(t)||t>=e.observed_at||j===undefined||
      j>i||segments[j]!==segments[i];
  }))throw Error('Structural event references invalid, incomplete or future candles');
  const set=events.get(e.observed_at)||new Set<string>();
  if(set.has(e.kind))throw Error('Duplicate structural event at one close');
  set.add(e.kind);events.set(e.observed_at,set);
  if(e.kind===SWEEP[0]||e.kind===SWEEP[1])sweeps.push({index:i,at:e.observed_at,kind:e.kind});
 }
 sweeps.sort((a,b)=>a.at-b.at||a.kind.localeCompare(b.kind));
 const usedConfirmation=new Set<number>();
 const signals:ConfluenceSignal[]=[];
 let confirmed=0,unconfirmed=0,confirmationReused=0,pending=0,gapExcluded=0,priceExcluded=0;
 for(const sweep of sweeps){
  const bullish=sweep.kind===SWEEP[0];
  const breakKind=bullish?'BULLISH STRUCTURE BREAK':'BEARISH STRUCTURE BREAK';
  const fvgKind=bullish?'BULLISH FVG':'BEARISH FVG';
  let j=-1;
  for(let k=sweep.index+1;k<=sweep.index+cfg.maxConfirmationBars&&k<bars.length;k++){
   if(segments[k]!==segments[sweep.index])break;
   const set=events.get(closeAt(bars[k],cfg.frame));
   if(set?.has(breakKind)&&set.has(fvgKind)){j=k;break}
  }
  if(j<0){unconfirmed++;continue}
  if(usedConfirmation.has(j)){confirmationReused++;continue}
  usedConfirmation.add(j);confirmed++;
  const end=j+cfg.horizonBars;
  if(end>=bars.length){pending++;continue}
  if(segments[end]!==segments[j]){gapExcluded++;continue}
  const entry=bars[j+1].open,exit=bars[end].close;
  if(!Number.isFinite(entry)||!Number.isFinite(exit)||entry<=0||exit<=0){priceExcluded++;continue}
  const grossBps=(bullish?1:-1)*(exit/entry-1)*10000;
  if(!Number.isFinite(grossBps)||cfg.costScenariosBps.some(cost=>!Number.isFinite(grossBps-cost))){priceExcluded++;continue}
  signals.push({sweepAt:sweep.at,confirmationAt:closeAt(bars[j],cfg.frame),
   direction:bullish?'bullish':'bearish',entryAt:bars[j+1].time,
   exitAt:closeAt(bars[end],cfg.frame),entry,exit,grossBps,
   netBps:cfg.costScenariosBps.map(cost=>grossBps-cost)});
 }
 return {engine:'sweep-mss-fvg-same-close-v1',datasetId:cfg.datasetId,instrument:cfg.instrument,
  frame:cfg.frame,maxConfirmationBars:cfg.maxConfirmationBars,horizonBars:cfg.horizonBars,
  costScenariosBps:[...cfg.costScenariosBps],sweepCount:sweeps.length,confirmed,
  completed:signals.length,unconfirmed,confirmationReused,pending,gapExcluded,priceExcluded,
  signals,meanNetBps:cfg.costScenariosBps.map((_,i)=>mean(signals.map(s=>s.netBps[i]))),
  warning:'Exploratory completed-candle sweep + same-close directional structure break (MSS proxy) + FVG. Not a validated MSS, CRT strategy, broker fill, stop/target model or independent holdout. Hypothetical fixed-horizon bid-price directional returns subtract assumed costs; spread, financing and execution are unverified. No predictive or profitability claim.'};
}
