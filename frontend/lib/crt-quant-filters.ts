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
 // A daily UTC bucket can be time-closed yet contain only a fraction
 // of its 1,440 expected source minutes (holiday, outage, archive edge).
 // Do not let a partial day's close distort the 5/20-day trend proxy.
 // Without a verified exchange calendar, shortened sessions are excluded
 // rather than guessed complete. Current/future daily buckets are excluded.
 const prior=bars.filter(b=>b.time+86400<=at&&b.observed_minutes===1440);
 if(prior.length<20)return 'INSUFFICIENT_DATA';
 const window=prior.slice(-20);
 // A completed candle can be from months or years before this sweep.
 // With no certified exchange calendar, use a conservative freshness
 // ceiling and a bounded 20-session span. This does NOT infer whether
 // a gap is a weekend, holiday or data outage.
 const latestClose=window[19].time+86400;
 const oldestClose=window[0].time+86400;
 if(at-latestClose>3*86400||latestClose-oldestClose>30*86400)
  return 'INSUFFICIENT_DATA';
 const recent=window.map(b=>b.close);
 const short=recent.slice(-5).reduce((a,b)=>a+b,0)/5;
 const long=recent.reduce((a,b)=>a+b,0)/20;
 return dir==='BULLISH'?(short>long?'PASS':'FAIL'):(short<long?'PASS':'FAIL');
}
function zoneGate(zones:readonly Zone[]|undefined,source:Source,
 dir:Direction,sweepStartAt:number,price:number):Gate{
 if(!zones?.length)return 'INSUFFICIENT_DATA';
 const matching=zones.filter(z=>z.datasetId===source.datasetId&&
  z.archiveSha256===source.archiveSha256&&z.priceSide===source.priceSide&&
  Number.isSafeInteger(z.observedAt)&&Number.isSafeInteger(z.referenceBarTime)&&
  z.referenceBarTime>=0&&z.referenceBarTime%14400===0&&
  // A zone first recorded during/after manipulation cannot be prior context.
  // Its reference 4H candle must also have closed before that record.
  z.observedAt<=sweepStartAt&&z.referenceBarTime+14400<=z.observedAt&&
  z.observedAt-z.referenceBarTime<30*86400&&
  Number.isFinite(z.low)&&Number.isFinite(z.high)&&
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
  // Only the next 16 completed 15m bars may confirm the closed 4H sweep.
  // If the first eligible bar or any preceding bar is missing, later shifts
  // CANNOT be cherry-picked: the earliest shift may have occurred in that gap.
  // Conversely, a fully observed 16-bar window with no shift is an observed
  // negative (FAIL), not missing evidence (INSUFFICIENT_DATA).
  const firstPost=fifteenMinute.findIndex(b=>b.time>=sweepCloseAt);
  let completeNegativeWindow=false;
  if(firstPost>=20&&fifteenMinute[firstPost]?.time===sweepCloseAt){
   completeNegativeWindow=true;
   for(let offset=0;offset<16;offset++){
    const j=firstPost+offset;
    const b=fifteenMinute[j];
    if(!b||b.time!==sweepCloseAt+offset*900){
     completeNegativeWindow=false;
     break;
    }
    const history=fifteenMinute.slice(j-20,j);
    if(history.length!==20||b.time-history[0].time!==20*900){
     completeNegativeWindow=false;
     break;
    }
    const bullish=observed.direction==='BULLISH';
    const swing=history.slice(-3);
    const shift=bullish?b.close>Math.max(...swing.map(x=>x.high))&&b.close>b.open:
     b.close<Math.min(...swing.map(x=>x.low))&&b.close<b.open;
    if(!shift)continue;
    gates.structureShift='PASS';
    const span=b.high-b.low;
    // A zero-range median makes any positive signal candle appear to
    // exceed 1.5x its baseline. Such a ratio is undefined, often indicating
    // stale/placeholder quotes. Never report a displacement PASS from it.
    const priorMedianRange=median(history.map(x=>x.high-x.low));
    gates.displacement=priorMedianRange<=0?'INSUFFICIENT_DATA':
     span>=priorMedianRange*displacement&&span>0?'PASS':'FAIL';
    gates.volume=volumeGate(history,b,source,volumeMultiple);
    confirm=b;
    break; // first observed shift; no later-best selection
   }
  }
  if(confirm===null){
   if(completeNegativeWindow){
    gates.structureShift='FAIL';
    notes.push('All 16 following 15-minute bars and prior 20-bar windows were observed; no qualifying directional structure shift occurred.');
   }else{
    notes.push('Cannot determine the first 15-minute structure shift: the next 4H window or its preceding 20 contiguous bars is incomplete.');
   }
  }else if(gates.displacement==='FAIL'){
   notes.push('First qualifying shift lacks prior-20-median range displacement; later shifts are not cherry-picked.');
  }else if(gates.displacement==='INSUFFICIENT_DATA'){
   notes.push('Prior-20 15-minute median candle range is zero: a multiplicative displacement ratio cannot be verified from flat/stale quotes.');
  }
  if(gates.volume==='INSUFFICIENT_DATA')notes.push('Verified actual volume history is missing; zero-volume HistData placeholders must not pass volume gates.');
  // Evaluate pre-existing 4H context against the sweep's own completed close,
  // not a later 15m confirmation price that was unknown at sweep close.
  gates.matchingZone=zoneGate(input.zones,source,observed.direction,sweep.time,sweep.close);
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
