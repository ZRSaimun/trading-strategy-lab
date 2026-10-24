/** Historical-only, prequential probability audit. Never produces trade signals. */
import type {Bar} from './research.ts';

export type ForecastSample={observedAt:number;evaluatedAt:number;probability:number;up:boolean};
export type CalibrationBin={from:number;to:number;count:number;meanForecast:number|null;observedUpRate:number|null};
export type HorizonAudit={horizon:number;samples:number;brier:number|null;baselineBrier:number|null;logLoss:number|null;baselineLogLoss:number|null;brierSkill:number|null;calibrationError:number|null;bins:CalibrationBin[];evaluations:ForecastSample[];recent:ForecastSample[];firstEvaluatedAt:number|null;lastEvaluatedAt:number|null};
export type ForecastAudit={version:'rolling-beta-v1';status:'HISTORICAL AUDIT ONLY';window:number;alpha:number;segments:number;completeBars:number;excludedBars:number;horizons:HorizonAudit[]};
const HORIZONS=[1,3,12] as const;
function mean(values:number[]){return values.reduce((a,b)=>a+b,0)/values.length}
function score(p:number,y:number){return -(y*Math.log(p)+(1-y)*Math.log(1-p))}

/**
 * For a forecast issued after close(i), the training label for k is allowed
 * only when k+h <= i. The evaluated label closes at i+h, never at issue time.
 * A missing or partial bar splits the data; no future information or gap fill.
 */
export function auditRollingDirection(bars:readonly Bar[],seconds:number,window=40,alpha=1):ForecastAudit{
 if(!Number.isSafeInteger(seconds)||seconds<60||seconds%60!==0||
    !Number.isSafeInteger(window)||window<20||window>500||
    !Number.isFinite(alpha)||alpha<=0||alpha>100||bars.length>20000)
  throw Error('Invalid historical forecast settings or more than 20,000 bars');
 let prev=-Infinity,excludedBars=0,completeBars=0;
 const segments:Bar[][]=[];let current:Bar[]=[];
 const flush=()=>{if(current.length){segments.push(current);current=[]}};
 for(const b of bars){
  if(!Number.isSafeInteger(b.time)||b.time<=prev||b.time%seconds!==0||
     ![b.open,b.high,b.low,b.close].every(x=>Number.isFinite(x)&&x>0)||
     b.high<Math.max(b.open,b.close)||b.low>Math.min(b.open,b.close)||
     !Number.isSafeInteger(b.observed_minutes)||b.observed_minutes<0)
   throw Error('Invalid, misaligned, or unordered historical OHLC');
  if(prev!==-Infinity&&b.time-prev!==seconds)flush();
  prev=b.time;
  if(b.observed_minutes!==seconds/60){excludedBars++;flush();continue}
  completeBars++;current.push(b);
 }
 flush();
 const horizons:HorizonAudit[]=HORIZONS.map(h=>{
  const samples:ForecastSample[]=[];
  for(const s of segments){
   if(s.length<window+2*h)continue;
   // Precompute labels, but every forecast reads only labels matured by issue time.
   const prefix=[0];
   for(let k=0;k<s.length-h;k++)prefix.push(prefix.at(-1)!+(s[k+h].close>s[k].close?1:0));
   for(let i=window+h-1;i+h<s.length;i++){
    const first=i-h-window+1,last=i-h;
    const up=prefix[last+1]-prefix[first];
    const p=(up+alpha)/(window+2*alpha);
    samples.push({observedAt:s[i].time+seconds,evaluatedAt:s[i+h].time+seconds,
      probability:p,up:s[i+h].close>s[i].close});
   }
  }
  const bins:CalibrationBin[]=Array.from({length:5},(_,i)=>{
   const selected=samples.filter(s=>Math.min(4,Math.floor(s.probability*5))===i);
   return {from:i/5,to:(i+1)/5,count:selected.length,
     meanForecast:selected.length?mean(selected.map(s=>s.probability)):null,
     observedUpRate:selected.length?mean(selected.map(s=>Number(s.up))):null};
  });
  const brier=samples.length?mean(samples.map(s=>(s.probability-Number(s.up))**2)):null;
  const baselineBrier=samples.length?0.25:null;
  const logLoss=samples.length?mean(samples.map(s=>score(s.probability,Number(s.up)))):null;
  const calibrationError=samples.length?bins.reduce((sum,b)=>sum+(b.count/samples.length)*Math.abs((b.meanForecast??0)-(b.observedUpRate??0)),0):null;
  return {horizon:h,samples:samples.length,brier,baselineBrier,logLoss,
    baselineLogLoss:samples.length?Math.log(2):null,
    brierSkill:brier===null?null:1-brier/0.25,calibrationError,bins,evaluations:samples,recent:samples.slice(-10),
    firstEvaluatedAt:samples[0]?.evaluatedAt??null,lastEvaluatedAt:samples.at(-1)?.evaluatedAt??null};
 });
 return {version:'rolling-beta-v1',status:'HISTORICAL AUDIT ONLY',window,alpha,
   segments:segments.length,completeBars,excludedBars,horizons};
}
