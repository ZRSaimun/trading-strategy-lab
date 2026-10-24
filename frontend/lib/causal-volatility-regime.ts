/**
 * Frozen, causal 1H volatility-regime labels for offline hypothesis research.
 * A label becomes available at the completed candle close (next bar open).
 * No future candles, broker quotes, outcome returns, fitting or orders.
 */
import {validStructureSegments} from './structure-quality.ts';
import type {Bar} from './research.ts';

export type VolatilityRegime='LOW'|'NORMAL'|'HIGH';
export type VolatilityLabel={
 candleOpenAt:number;observedAt:number;eligibleFrom:number;
 normalizedAtrBps:number;trailingPercentile:number;regime:VolatilityRegime;
};
export type VolatilityRegimeReport={
 engine:'causal-1h-natr-terciles-v1';datasetId:string;instrument:string;
 frame:'1H';atrPeriod:14;baselineBars:24;
 inputCandles:number;labelled:number;unlabelled:number;
 labels:VolatilityLabel[];counts:Record<VolatilityRegime,number>;
 warning:string;
};
const H=3600,ATR=14,BASELINE=24;
const near=(a:number,b:number)=>Math.abs(a-b)<=1e-12*Math.max(1,Math.abs(a),Math.abs(b));

export function labelCausalHourlyVolatility(
 bars:readonly Bar[],identity:{datasetId:string;instrument:string}
):VolatilityRegimeReport{
 if(!identity?.datasetId?.trim()||!identity?.instrument?.trim())
  throw Error('Exact source and instrument identity required');
 if(!Array.isArray(bars)||bars.length>1_000_000)
  throw Error('Bounded hourly candle input required');
 for(let i=1;i<bars.length;i++)
  if(!Number.isSafeInteger(bars[i].time)||bars[i].time<=bars[i-1].time)
   throw Error('Duplicate, unordered or invalid hourly timestamp');
 const segments=validStructureSegments(bars,'1H');
 const tr=new Array<number>(bars.length).fill(NaN);
 const natr=new Array<number>(bars.length).fill(NaN);
 const labels:VolatilityLabel[]=[];
 const counts:Record<VolatilityRegime,number>={LOW:0,NORMAL:0,HIGH:0};
 let runStart=-1,previousGood=-1,rollingTr=0;
 for(let i=0;i<bars.length;i++){
  const b=bars[i];
  const valid=segments[i]>=0&&
   [b.open,b.high,b.low,b.close].every(p=>Number.isFinite(p)&&p>0);
  if(!valid){runStart=-1;previousGood=-1;rollingTr=0;continue}
  if(previousGood!==i-1||i===0||segments[i]!==segments[i-1]){
   runStart=i;rollingTr=0;
  }else{
   const prev=bars[i-1].close;
   tr[i]=Math.max(b.high-b.low,Math.abs(b.high-prev),Math.abs(b.low-prev));
   rollingTr+=tr[i];
   if(i-runStart>ATR)rollingTr-=tr[i-ATR];
   if(i-runStart>=ATR){
    natr[i]=rollingTr/ATR/b.close*10000;
    if(!Number.isFinite(natr[i])||natr[i]<=0){
     runStart=-1;previousGood=-1;rollingTr=0;continue;
    }
   }
  }
  previousGood=i;
  if(i-runStart<ATR+BASELINE)continue;
  const current=natr[i];
  let lower=0,tied=0;
  for(let k=i-BASELINE;k<i;k++){
   const value=natr[k];
   if(!Number.isFinite(value)||value<=0)throw Error('Broken ATR baseline');
   if(near(value,current))tied++;
   else if(value<current)lower++;
  }
  const percentile=(lower+tied/2)/BASELINE;
  const regime:VolatilityRegime=percentile<1/3?'LOW':percentile>2/3?'HIGH':'NORMAL';
  counts[regime]++;
  labels.push({candleOpenAt:b.time,observedAt:b.time+H,eligibleFrom:b.time+H,
   normalizedAtrBps:current,trailingPercentile:percentile,regime});
 }
 return {engine:'causal-1h-natr-terciles-v1',datasetId:identity.datasetId,
  instrument:identity.instrument,frame:'1H',atrPeriod:ATR,baselineBars:BASELINE,
  inputCandles:bars.length,labelled:labels.length,unlabelled:bars.length-labels.length,
  labels,counts,
  warning:'Frozen exploratory normalized ATR(14) rank against the 24 PRIOR completed hourly ATR values. Each label is available only at its candle close; incomplete/gapped/nonpositive-price runs reset warmup. Regimes are descriptive, not calibrated probabilities, executable quotes, statistical significance, independent holdout or a profitable signal. Do not tune thresholds on inspected archives. No orders.'};
}
