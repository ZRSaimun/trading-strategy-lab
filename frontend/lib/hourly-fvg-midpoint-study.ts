/**
 * First-touch hourly FVG midpoint study (research only).
 *
 * The three-candle gap is known at the third bar CLOSE. Only the first
 * subsequently observed midpoint touch can qualify; failed touches are not
 * replaced with prettier future rejections. No broker order/fill is modeled.
 */
import type {Bar} from './research.ts';

export const HOURLY_FVG_VERSION='hourly-fvg-first-midpoint-touch-v6';
export type Evidence='PASS'|'FAIL'|'INSUFFICIENT_DATA';
export type Side='BULLISH'|'BEARISH';
export type FvgSource={
 datasetId:string;archiveSha256:string;instrument:string;provider:string;
 priceSide:'bid';volumeType:'exchange'|'tick'|'none'|'unverified';
 volumeVerified:boolean;
};
export type FvgConfig={
 maxTouchWaitBars?:number;markoutBars?:number;
 minimumRejectionWickFraction?:number;volumeMultiple?:number;
 hypotheticalRoundTripCostsBps?:readonly number[];
};
export type Markout={
 entryObservedAt:number;entryPrice:number;exitObservedAt:number;exitPrice:number;
 grossBps:number;netBpsByCost:readonly {costBps:number;netBps:number}[];
};
export type FvgObservation={
 direction:Side;formationClosedAt:number;gapLow:number;gapHigh:number;
 midpoint:number;firstTouchClosedAt:number|null;rejectionWickFraction:number|null;
 gates:{midpointTouch:Evidence;wickRejection:Evidence;verifiedVolume:Evidence;
  strictCandidate:Evidence;markout:Evidence};
 blindMidpointTouch:Markout|null;confirmedNextOpen:Markout|null;
 eligibleForLiveTrading:false;
};
export type FvgStudy={
 version:typeof HOURLY_FVG_VERSION;source:FvgSource;
 config:Required<FvgConfig>;observations:FvgObservation[];
 warning:string;
};
const HOUR=3600;
function validateBars(bars:readonly Bar[]){
 if(!Array.isArray(bars)||bars.length>20000)
  throw Error('Invalid or oversized hourly research window');
 for(let i=0;i<bars.length;i++){
  const b=bars[i];
  // A safe integer bar open can still overflow when converted to its
  // completed-bar close. All signal and markout timestamps use close times.
  if(!Number.isSafeInteger(b.time)||!Number.isSafeInteger(b.time+HOUR)||
   b.time<0||b.time%HOUR!==0||
   b.observed_minutes!==60||
   ![b.open,b.high,b.low,b.close].every(x=>Number.isFinite(x)&&x>0)||
   b.low>Math.min(b.open,b.close)||b.high<Math.max(b.open,b.close)||
   b.low>b.high||
   (b.volume!==null&&(!Number.isFinite(b.volume)||b.volume<0))||
   (i>0&&b.time<=bars[i-1].time))
   throw Error('Invalid, incomplete, misaligned or unordered hourly BID candles');
 }
}
// Decompose a validated positive finite float into an exact integer times
// a power of two. This preserves even subnormal observed volume values.
function positiveFloatParts(value:number):{mantissa:bigint;exponent:number}{
 const view=new DataView(new ArrayBuffer(8));
 view.setFloat64(0,value,false);
 const high=view.getUint32(0,false),low=view.getUint32(4,false);
 const biasedExponent=(high>>>20)&0x7ff;
 const fraction=(BigInt(high&0xfffff)<<32n)|BigInt(low);
 return {
  mantissa:biasedExponent===0?fraction:(1n<<52n)|fraction,
  exponent:biasedExponent===0?-1074:biasedExponent-1075,
 };
}
function verifiedVolume(bars:readonly Bar[],j:number,source:FvgSource,multiple:number):Evidence{
 if(!source.volumeVerified||!['exchange','tick'].includes(source.volumeType))
  return 'INSUFFICIENT_DATA';
 if(j<20)return 'INSUFFICIENT_DATA';
 const history=bars.slice(j-20,j),now=bars[j];
 if(history.length!==20||now.time-history[0].time!==20*HOUR||
  now.volume===null||now.volume<=0||
  history.some(b=>b.volume===null||b.volume<=0))
  return 'INSUFFICIENT_DATA';
 // Compare the exact finite IEEE-754 values, not rounded quotients.
 // For 20 prior bars, now > multiple * (sum/20) is equivalent to
 // 20*now > multiple*sum. Binary integer mantissas avoid both overflow
 // and false threshold ties introduced by floating-point division.
 const historyParts=history.map(b=>positiveFloatParts(b.volume!));
 const current=positiveFloatParts(now.volume);
 const factor=positiveFloatParts(multiple);
 const commonExponent=Math.min(current.exponent,...historyParts.map(x=>x.exponent));
 const total=historyParts.reduce((sum,x)=>
  sum+(x.mantissa<<BigInt(x.exponent-commonExponent)),0n);
 let lhs=20n*current.mantissa<<BigInt(current.exponent-commonExponent);
 let rhs=factor.mantissa*total;
 if(factor.exponent>=0)rhs<<=BigInt(factor.exponent);
 else lhs<<=BigInt(-factor.exponent);
 return lhs>rhs?'PASS':'FAIL';
}
// Evaluate the wick threshold against the exact supplied IEEE-754 prices.
// Subtracting a tiny positive low from a much larger wick/range can round
// BOTH differences to a false 50% equality. Keep the displayed fraction
// descriptive, but do not let its rounded value decide eligibility.
function wickMeetsFraction(bar:Bar,bull:boolean,minimum:number):boolean{
 const low=positiveFloatParts(bar.low),high=positiveFloatParts(bar.high);
 const anchor=positiveFloatParts(bull?Math.min(bar.open,bar.close):
  Math.max(bar.open,bar.close));
 const exponent=Math.min(low.exponent,high.exponent,anchor.exponent);
 const scaled=(part:{mantissa:bigint;exponent:number})=>
  part.mantissa<<BigInt(part.exponent-exponent);
 const wick=bull?scaled(anchor)-scaled(low):scaled(high)-scaled(anchor);
 const range=scaled(high)-scaled(low);
 // A zero-range candle has a descriptive wick fraction of zero.
 if(range===0n)return minimum===0;
 const threshold=positiveFloatParts(minimum);
 let lhs=wick,rhs=range*threshold.mantissa;
 if(threshold.exponent>=0)rhs<<=BigInt(threshold.exponent);
 else lhs<<=BigInt(-threshold.exponent);
 return lhs>=rhs;
}
function markout(entryAt:number,entry:number,exitAt:number,exit:number,
 direction:Side,costs:readonly number[]):Markout|null{
 const sign=direction==='BULLISH'?1:-1;
 const grossBps=sign*(exit-entry)/entry*10000;
 // Finite source OHLC can still overflow a bps ratio. Infinity is not a
 // measured return and must never enter a research report.
 if(!Number.isFinite(grossBps))return null;
 const netBpsByCost=costs.map(costBps=>({costBps,netBps:grossBps-costBps}));
 if(netBpsByCost.some(x=>!Number.isFinite(x.netBps)))return null;
 return {entryObservedAt:entryAt,entryPrice:entry,exitObservedAt:exitAt,
  exitPrice:exit,grossBps,netBpsByCost};
}
export function studyHourlyFvgMidpoint(
 bars:readonly Bar[],source:FvgSource,config:FvgConfig={},
):FvgStudy{
 const maxTouchWaitBars=config.maxTouchWaitBars??12;
 const markoutBars=config.markoutBars??3;
 const minimumRejectionWickFraction=config.minimumRejectionWickFraction??0.5;
 const volumeMultiple=config.volumeMultiple??1.5;
 const costs=config.hypotheticalRoundTripCostsBps??[0,5,15];
 if(!source||!/^[a-f0-9]{64}$/.test(source.datasetId)||
  !/^[a-f0-9]{64}$/.test(source.archiveSha256)||
  !source.instrument?.trim()||!source.provider?.trim()||
  source.priceSide!=='bid'||typeof source.volumeVerified!=='boolean'||
  !['exchange','tick','none','unverified'].includes(source.volumeType)||
  !Number.isSafeInteger(maxTouchWaitBars)||maxTouchWaitBars<1||maxTouchWaitBars>48||
  !Number.isSafeInteger(markoutBars)||markoutBars<1||markoutBars>48||
  !Number.isFinite(minimumRejectionWickFraction)||
  minimumRejectionWickFraction<0||minimumRejectionWickFraction>1||
  !Number.isFinite(volumeMultiple)||volumeMultiple<1||volumeMultiple>10||
  !Array.isArray(costs)||costs.length<1||costs.length>10||
  costs.some(x=>!Number.isFinite(x)||x<0||x>1000))
  throw Error('Invalid source identity, volume provenance or frozen FVG study settings');
 validateBars(bars);
 const observations:FvgObservation[]=[];
 for(let i=2;i<bars.length;i++){
  const first=bars[i-2],middle=bars[i-1],third=bars[i];
  if(middle.time-first.time!==HOUR||third.time-middle.time!==HOUR)continue;
  const bull=first.high<third.low,bear=first.low>third.high;
  if(bull===bear)continue;
  const direction:Side=bull?'BULLISH':'BEARISH';
  const gapLow=bull?first.high:third.high;
  const gapHigh=bull?third.low:first.low;
  // Both gap endpoints are strictly positive and ordered, so their
  // difference is finite. Half-summing subnormal endpoints can round each
  // half down before addition and move the midpoint by one price ULP,
  // changing first-touch classification. Subtract first, then halve.
  // An unrepresentable midpoint must not be rounded to either gap edge.
  const midpoint=gapLow+(gapHigh-gapLow)/2;
  if(!Number.isFinite(midpoint)||midpoint<=gapLow||midpoint>=gapHigh)
   throw Error('FVG midpoint cannot be represented strictly inside the gap');
  const gates:FvgObservation['gates']={
   midpointTouch:'INSUFFICIENT_DATA',wickRejection:'INSUFFICIENT_DATA',
   verifiedVolume:'INSUFFICIENT_DATA',strictCandidate:'INSUFFICIENT_DATA',
   markout:'INSUFFICIENT_DATA',
  };
  let touch:number|null=null;
  let wickFraction:number|null=null;
  let blind:Markout|null=null,confirmed:Markout|null=null;
  let windowComplete=true;
  let openingGapThrough=false;
  for(let wait=1;wait<=maxTouchWaitBars;wait++){
   const j=i+wait,b=bars[j],prev=bars[j-1];
   if(!b||b.time-prev.time!==HOUR){windowComplete=false;break;}
   // A bar that OPENS beyond the midpoint has already jumped across the
   // proposed limit price. Even if its entire range stays beyond that level,
   // a later return cannot establish that the original order was filled.
   // Freeze the first gap-through rather than cherry-picking a later touch.
   if(bull?b.open<midpoint:b.open>midpoint){
    // Preserve a physical range intersection without asserting a fill.
    if(b.low<=midpoint&&b.high>=midpoint)touch=j;
    openingGapThrough=true;
    gates.midpointTouch='INSUFFICIENT_DATA';
    break;
   }
   if(b.low>midpoint||b.high<midpoint)continue;
   touch=j;
   // An opening gap THROUGH the midpoint is not evidence that a hypothetical
   // limit at midpoint could have filled at that price. Do not skip it.
   const approachesFromGapSide=bull?b.open>=midpoint:b.open<=midpoint;
   if(!approachesFromGapSide){
    gates.midpointTouch='INSUFFICIENT_DATA';
    break;
   }
   gates.midpointTouch='PASS';
   const range=b.high-b.low;
   const wick=bull?Math.min(b.open,b.close)-b.low:
    b.high-Math.max(b.open,b.close);
   wickFraction=range>0?Math.max(0,wick)/range:0;
   const reclaim=bull?b.close>midpoint&&b.close>b.open:
    b.close<midpoint&&b.close<b.open;
   gates.wickRejection=reclaim&&wickMeetsFraction(b,bull,minimumRejectionWickFraction)?
    'PASS':'FAIL';
   gates.verifiedVolume=verifiedVolume(bars,j,source,volumeMultiple);
   gates.strictCandidate=gates.wickRejection==='FAIL'?'FAIL':
    gates.verifiedVolume;
   // Markout horizon is fixed in advance, never the best future close.
   // Both scenarios share the same exit close. The baseline assumes an
   // intrabar midpoint touch, not an observed executable broker fill.
   const exit=bars[j+markoutBars];
   let contiguous=!!exit;
   for(let k=j+1;k<=j+markoutBars;k++){
    if(!bars[k]||bars[k].time-bars[k-1].time!==HOUR){contiguous=false;break;}
   }
   if(contiguous&&exit){
    const exitAt=exit.time+HOUR;
    // OHLC can establish a midpoint intersection only when the touch bar
    // closes. Its open timestamp is NOT an observed intrabar fill time.
    // The hypothetical limit price remains unchanged; no fill is certified.
    const blindCandidate=markout(b.time+HOUR,midpoint,exitAt,exit.close,direction,costs);
    const confirmedCandidate=gates.wickRejection==='PASS'?
     markout(bars[j+1].time,bars[j+1].open,exitAt,exit.close,direction,costs):null;
    // Preserve the matched comparison cohort. If either required return
    // overflows, do not report the other as a selectively retained outcome.
    if(blindCandidate&&(gates.wickRejection!=='PASS'||confirmedCandidate)){
     blind=blindCandidate;
     confirmed=confirmedCandidate;
     gates.markout='PASS';
    }
   }
   break; // FIRST midpoint touch only
  }
  // A fully observed waiting horizon without a touch is a known rejection,
  // not missing evidence. Keep incomplete/gap-through windows unknown.
  if(touch===null&&windowComplete&&!openingGapThrough){
   gates.midpointTouch='FAIL';
   gates.strictCandidate='FAIL';
  }
  observations.push({direction,formationClosedAt:third.time+HOUR,
   gapLow,gapHigh,midpoint,firstTouchClosedAt:touch===null?null:bars[touch].time+HOUR,
   rejectionWickFraction:wickFraction,gates,
   blindMidpointTouch:blind,confirmedNextOpen:confirmed,
   eligibleForLiveTrading:false});
 }
 return {version:HOURLY_FVG_VERSION,source:{...source},
  config:{maxTouchWaitBars,markoutBars,minimumRejectionWickFraction,
   volumeMultiple,hypotheticalRoundTripCostsBps:[...costs]},
  observations,
  warning:'Read-only hourly BID OHLC research. Midpoint touch is a hypothetical blind limit, not an executable fill. Rejection entry uses only the next observed hourly open. Markouts omit intrabar stops, spreads, financing, news, slippage and broker contracts; bps costs are illustrative, not measured. No strategy edge or live execution is established.'};
}
