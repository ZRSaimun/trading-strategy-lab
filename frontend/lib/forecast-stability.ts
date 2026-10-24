/**
 * Descriptive score stability over two consecutive, non-overlapping evaluation
 * windows. NOT a significance test or an alert-delivery service.
 * Overlapping forecast horizons produce correlated outcomes.
 */
import type {ForecastSample} from './forecast-audit.ts';

export type ScoreWindow={count:number;firstEvaluatedAt:number;lastEvaluatedAt:number;brier:number;logLoss:number;baselineBrier:0.25;upRate:number};
export type StabilityReview={
 status:'INSUFFICIENT'|'REVIEW'|'NO_FLAG';horizon:number;window:number;
 earlier:ScoreWindow|null;recent:ScoreWindow|null;
 deltaBrier:number|null;recentBrierSkill:number|null;reasons:string[];
};
const avg=(values:number[])=>values.reduce((a,b)=>a+b,0)/values.length;
const epoch=(v:number)=>Number.isSafeInteger(v)&&v>=0;
function metrics(items:readonly ForecastSample[]):ScoreWindow{
 return {count:items.length,firstEvaluatedAt:items[0].evaluatedAt,
  lastEvaluatedAt:items[items.length-1].evaluatedAt,
  brier:avg(items.map(s=>(s.probability-Number(s.up))**2)),
  logLoss:avg(items.map(s=>s.up?-Math.log(s.probability):-Math.log1p(-s.probability))),
  baselineBrier:0.25,upRate:avg(items.map(s=>Number(s.up)))};
}
/**
 * Compare the latest N matured outcomes with the immediately preceding N.
 * Flags are predeclared descriptive heuristics, not statistical proof.
 * Do not infer broker P&L or issue orders from this score.
 */
export function reviewForecastStability(samples:readonly ForecastSample[],horizon:1|3|12,seconds:number,window=100):StabilityReview{
 if(![1,3,12].includes(horizon)||!Number.isSafeInteger(seconds)||seconds<60||seconds%60!==0||
    !Number.isSafeInteger(window)||window<20||window>1000||samples.length>20000)
  throw Error('Invalid stability review horizon, timeframe, window or sample count');
 let priorIssue=-1,priorEvaluation=-1;
 for(const s of samples){
  if(!epoch(s.observedAt)||!epoch(s.evaluatedAt)||s.observedAt<=priorIssue||s.evaluatedAt<=priorEvaluation||
     s.observedAt%seconds!==0||s.evaluatedAt%seconds!==0||
     s.evaluatedAt-s.observedAt!==horizon*seconds||
     !Number.isFinite(s.probability)||s.probability<=0||s.probability>=1||typeof s.up!=='boolean')
   throw Error('Malformed, mixed-horizon, duplicate or unordered forecast evaluation');
  priorIssue=s.observedAt;priorEvaluation=s.evaluatedAt;
 }
 if(samples.length<window*2)return {status:'INSUFFICIENT',horizon,window,earlier:null,recent:null,
  deltaBrier:null,recentBrierSkill:null,reasons:['Need '+window*2+' matured outcomes for two fixed comparison windows; have '+samples.length+'.']};
 // A fixed-count comparison must not silently bridge missing/partial bars,
 // weekend closures, or disconnected provider intervals. Historical calibration
 // produces one evaluation per completed bar within a contiguous segment.
 // The last two windows must therefore cover 2*window consecutive issue times.
 // An older gap outside the comparison is irrelevant.
 const selected=samples.slice(-2*window);
 for(let i=1;i<selected.length;i++){
  if(selected[i].observedAt-selected[i-1].observedAt!==seconds ||
     selected[i].evaluatedAt-selected[i-1].evaluatedAt!==seconds){
   return {status:'INSUFFICIENT',horizon,window,earlier:null,recent:null,
    deltaBrier:null,recentBrierSkill:null,
    reasons:['The latest '+(2*window)+' evaluations cross a missing or non-contiguous candle interval; do not compare score windows across gaps. Collect '+(2*window)+' consecutive matured evaluations.']};
  }
 }
 const earlier=metrics(selected.slice(0,window)),recent=metrics(selected.slice(window));
 const deltaBrier=recent.brier-earlier.brier;
 const recentBrierSkill=1-recent.brier/0.25;
 const reasons:string[]=[];
 if(deltaBrier>=0.02)reasons.push('Recent Brier loss is at least 0.02 worse than the preceding window.');
 if(recent.brier>0.25)reasons.push('Recent Brier loss is worse than the fixed 50% reference.');
 return {status:reasons.length?'REVIEW':'NO_FLAG',horizon,window,earlier,recent,
  deltaBrier,recentBrierSkill,reasons};
}
