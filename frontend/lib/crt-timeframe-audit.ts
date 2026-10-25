/**
 * Verify that two API timeframe responses from the same immutable archive
 * actually describe the same historical BID candles.
 *
 * The source manifest/hash check alone cannot detect an aggregation defect,
 * cache skew, or an accidental timeframe-specific API response.
 *
 * Only fully overlapped 4H bars are compared; edge 4H bars outside the
 * loaded 15m window cannot be certified and are counted separately.
 * Fail closed on missing 15m buckets inside a fully overlapped 4H bar.
 */
import type {Bar} from './research.ts';

export type CrossoverAudit={
 checkedFourHourBars:number;
 uncheckableFourHourBars:number;
 /** Exact 4H bucket starts whose complete 16-bar 15m OHLC matched. */
 verifiedFourHourStarts:number[];
};
const MIN15=900, FOUR_HOUR=14400, BARS_PER_4H=16;

function assertComplete(b:Bar,seconds:number){
 if(!Number.isSafeInteger(b.time)||b.time<0||b.time%seconds!==0||
  b.observed_minutes!==seconds/60||
  ![b.open,b.high,b.low,b.close].every(x=>Number.isFinite(x)&&x>0)||
  b.low>Math.min(b.open,b.close)||b.high<Math.max(b.open,b.close)||
  b.low>b.high||
  (b.volume!==null&&(!Number.isFinite(b.volume)||b.volume<0)))
  throw Error('Incomplete or invalid cross-timeframe input');
}
function samePrice(a:number,b:number){
 // Allow only floating-point serialization noise, never a real price tick.
 return Math.abs(a-b)<=1e-10*Math.max(1,Math.abs(a),Math.abs(b));
}

export function auditCrtCrossTimeframe(
 fourHour:readonly Bar[],fifteenMinute:readonly Bar[],
):CrossoverAudit{
 if(!Array.isArray(fourHour)||!Array.isArray(fifteenMinute)||
  fourHour.length>20000||fifteenMinute.length>20000)
  throw Error('Invalid or oversized cross-timeframe window');
 for(let i=0;i<fourHour.length;i++){
  assertComplete(fourHour[i],FOUR_HOUR);
  if(i>0&&fourHour[i].time<=fourHour[i-1].time)
   throw Error('Out-of-order 4H cross-timeframe candles');
 }
 for(let i=0;i<fifteenMinute.length;i++){
  assertComplete(fifteenMinute[i],MIN15);
  if(i>0&&fifteenMinute[i].time<=fifteenMinute[i-1].time)
   throw Error('Out-of-order 15m cross-timeframe candles');
 }
 let checked=0,uncheckable=0,index=0;
 const verifiedFourHourStarts:number[]=[];
 const start=fifteenMinute[0]?.time,end=fifteenMinute[fifteenMinute.length-1]?.time;
 for(const h4 of fourHour){
  // An overlapping but incomplete boundary block must be classified as
  // uncheckable, not silently counted as verified.
  if(start===undefined||end===undefined||h4.time<start||
   h4.time+FOUR_HOUR>end+MIN15){
   uncheckable++;
   continue;
  }
  while(index<fifteenMinute.length&&fifteenMinute[index].time<h4.time)index++;
  if(index+BARS_PER_4H>fifteenMinute.length)
   throw Error('Missing complete 15m coverage for overlapping 4H candle');
  const subset=fifteenMinute.slice(index,index+BARS_PER_4H);
  if(subset.some((b,j)=>b.time!==h4.time+j*MIN15))
   throw Error('Missing or noncontiguous 15m bars within completed 4H candle');
  const observed={
   open:subset[0].open,
   high:Math.max(...subset.map(x=>x.high)),
   low:Math.min(...subset.map(x=>x.low)),
   close:subset[BARS_PER_4H-1].close,
  };
  if(!samePrice(h4.open,observed.open)||!samePrice(h4.high,observed.high)||
   !samePrice(h4.low,observed.low)||!samePrice(h4.close,observed.close))
   throw Error('4H/15m OHLC mismatch for same historical archive');
  checked++;
  verifiedFourHourStarts.push(h4.time);
  index+=BARS_PER_4H;
 }
 return {checkedFourHourBars:checked,uncheckableFourHourBars:uncheckable,
  verifiedFourHourStarts};
}

/**
 * Keep only 4H buckets independently reconciled to complete source-matched
 * 15m OHLC. Re-audit the CURRENT candle inputs: a previous report alone is
 * not proof, because prices or coverage may have changed since it was made.
 * In particular, a forged report can substitute an uncheckable 4H timestamp
 * while preserving its verified/uncheckable counts.
 */
export function certifiedCrtFourHourBars(
 fourHour:readonly Bar[],fifteenMinute:readonly Bar[],audit:CrossoverAudit,
):Bar[]{
 const current=auditCrtCrossTimeframe(fourHour,fifteenMinute);
 if(!audit||!Array.isArray(audit.verifiedFourHourStarts)||
  current.checkedFourHourBars!==audit.checkedFourHourBars||
  current.uncheckableFourHourBars!==audit.uncheckableFourHourBars||
  current.verifiedFourHourStarts.length!==audit.verifiedFourHourStarts.length||
  current.verifiedFourHourStarts.some((time,i)=>time!==audit.verifiedFourHourStarts[i]))
  throw Error('Stale or inconsistent 4H/15m certification report');
 const verified=new Set(current.verifiedFourHourStarts);
 return fourHour.filter(b=>verified.has(b.time));
}
