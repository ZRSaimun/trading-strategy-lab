/**
 * Observed-only multi-timeframe CRT research screening.
 * Rules are HYPOTHESES, not proven win-rate improvements or an order system.
 * One exact dataset/price-side across all inputs. No live order route.
 */
import type {Bar} from './research.ts';

export const CRT_SCREEN_VERSION='crt-4h-sweep-15m-displacement-research-v1';
export type Gate='PASS'|'FAIL'|'INSUFFICIENT_DATA';
export type Direction='BULLISH'|'BEARISH';
export type Source={
 datasetId:string;archiveSha256:string;instrument:string;provider:string;
 priceSide:'bid';volumeType:'exchange'|'tick'|'none'|'unverified';
 volumeVerified:boolean;
};
export type Zone={
 // Dataset IDs alone can be reused across imports: pin the exact archive
 // revision and BID price side before a prior zone can pass this gate.
 datasetId:string;archiveSha256:string;priceSide:'bid';
 direction:'DEMAND'|'SUPPLY';low:number;high:number;
 observedAt:number;referenceBarTime:number;
};
export type Context={
 fourHour:readonly Bar[];fifteenMinute:readonly Bar[];
 daily?:readonly Bar[];source:Source;
 zones?:readonly Zone[];
 sweepMaxFraction?:number;
 displacementMultiple?:number;
 volumeMultiple?:number;
};
export type ScreenedCandidate={
 direction:Direction;sweepCloseAt:number;referenceAt:number;
 referenceHigh:number;referenceLow:number;sweepDepthFraction:number;
 confirmationCloseAt:number|null;confirmationPrice:number|null;
 gates:{
  sweepDepth:Gate;structureShift:Gate;displacement:Gate;
  volume:Gate;dailyTrend:Gate;matchingZone:Gate;newsCalendar:Gate;
 };
 notes:string[];
 eligibleForLiveTrading:false;
};
export type ScreenResult={
 engine:typeof CRT_SCREEN_VERSION;source:Source;analyzedSweepPairs:number;
 candidates:ScreenedCandidate[];
 warning:string;
};

function validBar(b:Bar,seconds:number,previous:Bar|undefined){
 return Number.isSafeInteger(b.time)&&b.time>=0&&b.time%seconds===0&&
  b.observed_minutes===seconds/60&&
  [b.open,b.high,b.low,b.close].every(x=>Number.isFinite(x)&&x>0)&&
  b.low<=Math.min(b.open,b.close)&&b.high>=Math.max(b.open,b.close)&&
  b.low<=b.high&&
  (b.volume===null||(Number.isFinite(b.volume)&&b.volume>=0))&&
  (!previous||b.time>previous.time);
}
function validateBars(bars:readonly Bar[],seconds:number){
 if(!Array.isArray(bars)||bars.length>20000)throw Error('Invalid or oversized research candle window');
 for(let i=0;i<bars.length;i++){
  if(!validBar(bars[i],seconds,bars[i-1]))
   throw Error('Invalid, incomplete, misaligned or unordered historical candles');
 }
}
/**
 * Historical M1 -> timeframe aggregation can legitimately return a partial
 * first or last bucket when an imported source begins/ends mid-interval.
 * Exclude ONLY those two boundary buckets. Never silently discard internal
 * incomplete buckets, since that would hide missing market observations.
 * All retained bars are revalidated by the research engine.
 */
export function completeAggregateWindow(
 bars:readonly Bar[],seconds:900|14400,
):{bars:Bar[];excludedBoundaryBars:number}{
 if(!Array.isArray(bars)||bars.length>20000)
  throw Error('Invalid or oversized aggregate research window');
 const minutes=seconds/60;
 for(let i=0;i<bars.length;i++){
  const b=bars[i];
  if(!Number.isSafeInteger(b.time)||b.time<0||b.time%seconds!==0||
   !Number.isSafeInteger(b.observed_minutes)||b.observed_minutes<1||
   b.observed_minutes>minutes||
   ![b.open,b.high,b.low,b.close].every(n=>Number.isFinite(n)&&n>0)||
   b.low>Math.min(b.open,b.close)||b.high<Math.max(b.open,b.close)||
   (b.volume!==null&&(!Number.isFinite(b.volume)||b.volume<0))||
   (i>0&&b.time<=bars[i-1].time))
   throw Error('Invalid aggregate candle quality or time order');
 }
 const first=bars.length&&bars[0].observed_minutes!==minutes?1:0;
 const end=bars.length>first&&bars[bars.length-1].observed_minutes!==minutes?
  bars.length-1:bars.length;
 for(let i=first;i<end;i++){
  if(bars[i].observed_minutes!==minutes)
   throw Error('Incomplete internal aggregate candle; research window is not safe');
 }
 return {bars:bars.slice(first,end),excludedBoundaryBars:first+bars.length-end};
}

function median(v:number[]){
 const s=[...v].sort((a,b)=>a-b),n=s.length;
 return n%2?s[(n-1)/2]:(s[n/2-1]+s[n/2])/2;
}
function directionAndDepth(ref:Bar,manip:Bar):{direction:Direction;depth:number}|null{
 const span=ref.high-ref.low;if(span<=0)return null;
 const sweptLow=manip.low<ref.low&&manip.close>ref.low&&manip.close<ref.high;
 const sweptHigh=manip.high>ref.high&&manip.close<ref.high&&manip.close>ref.low;
 if(sweptLow===sweptHigh)return null; // reject ambiguous outside bars
 return sweptLow?{direction:'BULLISH',depth:(ref.low-manip.low)/span}:
  {direction:'BEARISH',depth:(manip.high-ref.high)/span};
}
function trend(bars:readonly Bar[]|undefined,at:number,dir:Direction):Gate{
 if(!bars)return 'INSUFFICIENT_DATA';
 // Daily bars are UTC calendar buckets. Only fully CLOSED prior daily bars
 // can be used: any current day is excluded, regardless of partial data.
 const prior=bars.filter(b=>b.time+86400<=at);
 if(prior.length<20)return 'INSUFFICIENT_DATA';
 const recent=prior.slice(-20).map(b=>b.close);
 const short=recent.slice(-5).reduce((a,b)=>a+b,0)/5;
 const long=recent.reduce((a,b)=>a+b,0)/20;
 return dir==='BULLISH'?(short>long?'PASS':'FAIL'):(short<long?'PASS':'FAIL');
}
function zoneGate(zones:readonly Zone[]|undefined,source:Source,
 dir:Direction,at:number,price:number):Gate{
 if(!zones?.length)return 'INSUFFICIENT_DATA';
 const matching=zones.filter(z=>z.datasetId===source.datasetId&&
  z.archiveSha256===source.archiveSha256&&z.priceSide===source.priceSide&&
  Number.isSafeInteger(z.observedAt)&&Number.isSafeInteger(z.referenceBarTime)&&
  z.referenceBarTime>=0&&z.referenceBarTime%14400===0&&
  z.observedAt<=at&&z.referenceBarTime+14400<=z.observedAt&&
  z.observedAt-z.referenceBarTime<30*86400&&
  z.low>0&&z.high>z.low&&z.low<=price&&price<=z.high&&
  z.direction===(dir==='BULLISH'?'DEMAND':'SUPPLY'));
 return matching.length?'PASS':'INSUFFICIENT_DATA';
}
function volumeGate(history:readonly Bar[],last:Bar,source:Source,multiple:number):Gate{
 if(!source.volumeVerified||!['exchange','tick'].includes(source.volumeType))
  return 'INSUFFICIENT_DATA';
 const values=history.map(b=>b.volume);
 if(last.volume===null||last.volume<=0||
  values.some(v=>v===null||v<=0))return 'INSUFFICIENT_DATA';
 const average=values.reduce<number>((sum,v)=>sum+(v??0),0)/values.length;
 return Number.isFinite(average)&&average>0&&last.volume>multiple*average?'PASS':'FAIL';
}

export function screenCrtHypotheses(input:Context):ScreenResult{
 const {fourHour,fifteenMinute,daily,source}=input;
 const sweepMax=input.sweepMaxFraction??0.4,
  displacement=input.displacementMultiple??1.5,volumeMultiple=input.volumeMultiple??1.5;
 if(!source||!/^[a-f0-9]{64}$/.test(source.datasetId)||
  !/^[a-f0-9]{64}$/.test(source.archiveSha256)||
  !source.provider?.trim()||!source.instrument?.trim()||source.priceSide!=='bid'||
  !['exchange','tick','none','unverified'].includes(source.volumeType)||
  typeof source.volumeVerified!=='boolean'||
  !Number.isFinite(sweepMax)||sweepMax<=0||sweepMax>1||
  !Number.isFinite(displacement)||displacement<1||displacement>10||
  !Number.isFinite(volumeMultiple)||volumeMultiple<1||volumeMultiple>10)
  throw Error('Invalid source, volume provenance or experimental thresholds');
 validateBars(fourHour,14400);validateBars(fifteenMinute,900);
 if(daily){
  // Daily UTC buckets are allowed to include session closure gaps and
  // incomplete calendar-day aggregates. Never treat them as complete 1440m.
  if(!Array.isArray(daily)||daily.length>20000)throw Error('Invalid daily research input');
  for(let i=0;i<daily.length;i++){
   const b=daily[i];
   if(!Number.isSafeInteger(b.time)||b.time%86400!==0||
    ![b.open,b.high,b.low,b.close].every(x=>Number.isFinite(x)&&x>0)||
    b.low>Math.min(b.open,b.close)||b.high<Math.max(b.open,b.close)||
    b.observed_minutes<1||b.observed_minutes>1440||
    (i>0&&b.time<=daily[i-1].time))
    throw Error('Invalid daily research input');
  }
 }
 const result:ScreenedCandidate[]=[];
 for(let i=1;i<fourHour.length;i++){
  const ref=fourHour[i-1],sweep=fourHour[i];
  // The preceding reference and manipulation must be adjacent closed 4H bars.
  if(sweep.time-ref.time!==14400)continue;
  const observed=directionAndDepth(ref,sweep);if(!observed)continue;
  const sweepCloseAt=sweep.time+14400;
  const depthPass=observed.depth<=sweepMax;
  const gates:ScreenedCandidate['gates']={
   sweepDepth:depthPass?'PASS':'FAIL',structureShift:'INSUFFICIENT_DATA',
   displacement:'INSUFFICIENT_DATA',volume:'INSUFFICIENT_DATA',
   dailyTrend:trend(daily,sweepCloseAt,observed.direction),
   matchingZone:'INSUFFICIENT_DATA',newsCalendar:'INSUFFICIENT_DATA',
  };
  let confirm:Bar|null=null;
  const notes:string[]=[];
  if(!depthPass)notes.push('Outside wick exceeds frozen 40% reference-range hypothesis (or configured research threshold).');
  // A 15m signal is eligible only AFTER 4H Candle 2 completed.
  // This research hypothesis permits the following completed 4H block.
  for(let j=20;j<fifteenMinute.length;j++){
   const b=fifteenMinute[j];
   if(b.time<sweepCloseAt)continue;
   if(b.time>=sweepCloseAt+14400)break;
   const history=fifteenMinute.slice(j-20,j);
   if(b.time-history[0].time!==20*900)continue;
   const span=b.high-b.low;
   const priorRanges=history.map(x=>x.high-x.low);
   const threshold=median(priorRanges)*displacement;
   const bullish=observed.direction==='BULLISH';
   const swing=history.slice(-3);
   const shift=bullish?b.close>Math.max(...swing.map(x=>x.high))&&b.close>b.open:
    b.close<Math.min(...swing.map(x=>x.low))&&b.close<b.open;
   if(!shift)continue;
   gates.structureShift='PASS';
   gates.displacement=span>=threshold&&span>0?'PASS':'FAIL';
   gates.volume=volumeGate(history,b,source,volumeMultiple);
   confirm=b;
   break; // earliest observed shift, never optimize by later outcome
  }
  if(confirm===null)notes.push('No eligible 15-minute closed-bar swing break within the next completed 4H block; or 20 prior contiguous bars unavailable.');
  else if(gates.displacement==='FAIL')notes.push('First qualifying shift lacks prior-20-median range displacement; later shifts are not cherry-picked.');
  if(gates.volume==='INSUFFICIENT_DATA')notes.push('Verified actual volume history is missing; zero-volume HistData placeholders must not pass volume gates.');
  gates.matchingZone=zoneGate(input.zones,source,observed.direction,sweepCloseAt,confirm?.close??sweep.close);
  if(gates.matchingZone==='INSUFFICIENT_DATA')notes.push('No source-linked, causally recorded matching 4H supply/demand reference; no automatic order-block claim.');
  notes.push('No verified timestamped economic calendar, so a 15-minute high-impact news exclusion cannot be confirmed.');
  result.push({direction:observed.direction,sweepCloseAt,referenceAt:ref.time,
    referenceHigh:ref.high,referenceLow:ref.low,
    sweepDepthFraction:observed.depth,confirmationCloseAt:confirm?confirm.time+900:null,
    confirmationPrice:confirm?.close??null,gates,notes,eligibleForLiveTrading:false});
 }
 return {engine:CRT_SCREEN_VERSION,source:{...source},
  analyzedSweepPairs:Math.max(0,fourHour.length-1),candidates:result,
  warning:'Exploratory closed-bar research only. No independently validated CRT/ICT definitions, executable bid/ask, news feed, broker costs, locked holdout or trading authorization. No positive gate combination implies profitability.'};
}
