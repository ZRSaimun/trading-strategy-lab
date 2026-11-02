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
 readonly checkedFourHourBars:number;
 readonly uncheckableFourHourBars:number;
 /** Exact 4H bucket starts whose complete 16-bar 15m OHLC matched. */
 readonly verifiedFourHourStarts:readonly number[];
 /** Same-archive numeric reconciliation, NOT authenticated market volume. */
 readonly reconciledNumericVolumeStarts:readonly number[];
};
const MIN15=900, FOUR_HOUR=14400, BARS_PER_4H=16;

// Keep an exact, private-in-memory snapshot for each issued report. Re-auditing
// only the counts and timestamps cannot detect coordinated edits to BOTH 4H
// and 15m bars that still reconcile after the report was issued. This is a
// local mutation guard, NOT a cryptographic source-authentication receipt.
// Bind the issued report to the exact pair of source-array instances as well
// as their values. Equal-looking replacements can come from a different
// archive or API response and must undergo their own audit. Array identity
// is a local consistency fence, NOT independent archive provenance.
type IssuedSnapshot={
 fourHour:readonly Bar[];
 fifteenMinute:readonly Bar[];
 // Pin the individual source candle objects, not only their container arrays.
 // Replacing a slot with an equal-valued clone is a new un-audited response.
 fourHourRows:readonly Bar[];
 fifteenMinuteRows:readonly Bar[];
 content:string;
};
const issuedSnapshots=new WeakMap<CrossoverAudit,IssuedSnapshot>();
const BAR_FIELDS=['time','open','high','low','close','volume','observed_minutes'] as const;
function assertOwnDataFields(b:Bar):void{
 // API candles are plain JSON records. Accessor/inherited fields can change
 // between audit, snapshot and certification, or execute code on a read.
 // Reject them before touching any validated candle value.
 if(!b||typeof b!=='object') throw Error('Invalid cross-timeframe candle fields');
 for(const field of BAR_FIELDS){
  const descriptor=Object.getOwnPropertyDescriptor(b,field);
  if(!descriptor||!Object.hasOwn(descriptor,'value'))
   throw Error('Cross-timeframe candle requires own data fields');
 }
}
function assertOwnBarSlots(bars:readonly Bar[]):void{
 // JSON arrays contain direct indexed data entries. Accessor-backed or
 // inherited array elements could swap candle objects between the audit,
 // issued snapshot and certified-copy selection, even when candle fields
 // themselves are ordinary data properties.
 for(let i=0;i<bars.length;i++){
  const descriptor=Object.getOwnPropertyDescriptor(bars,String(i));
  if(!descriptor||!Object.hasOwn(descriptor,'value'))
   throw Error('Cross-timeframe window requires own data entries');
 }
 // Array.isArray and own indexed slots alone are insufficient: a caller
 // can override iteration, map, slice or filter to substitute different
 // candles AFTER indexed validation. API JSON arrays have the standard
 // Array prototype and no own method overrides. Refuse exotic arrays
 // before invoking any caller-supplied iterator or method.
 // Check indexed data first so a missing/inherited slot retains its
 // precise validation error even when the array prototype is exotic.
 if(Object.getPrototypeOf(bars)!==Array.prototype||
  ['map','slice','filter'].some(name=>Object.hasOwn(bars,name))||
  Object.hasOwn(bars,Symbol.iterator)||
  // Array built-ins use ArraySpeciesCreate: even a normal-looking array
  // can execute an own constructor/species getter during map or slice.
  // JSON source arrays never carry an own constructor property.
  Object.hasOwn(bars,'constructor'))
  throw Error('Cross-timeframe window requires ordinary JSON array methods');
}
function candleSnapshot(fourHour:readonly Bar[],fifteenMinute:readonly Bar[]):string{
 const rows=(bars:readonly Bar[])=>{
  assertOwnBarSlots(bars);
  return bars.map(b=>{
  assertOwnDataFields(b);
  return [b.time,b.open,b.high,b.low,b.close,b.volume,b.observed_minutes];
 });
 };
 return JSON.stringify([rows(fourHour),rows(fifteenMinute)]);
}

function assertComplete(b:Bar,seconds:number){
 assertOwnDataFields(b);
 if(!Number.isSafeInteger(b.time)||b.time<0||b.time%seconds!==0||
  // A safe bucket start can still overflow JS integer precision at close.
  // CRT decisions require exact completed-bar timestamps, never rounded ends.
  !Number.isSafeInteger(b.time+seconds)||
  b.observed_minutes!==seconds/60||
  ![b.open,b.high,b.low,b.close].every(x=>Number.isFinite(x)&&x>0)||
  b.low>Math.min(b.open,b.close)||b.high<Math.max(b.open,b.close)||
  b.low>b.high||
  (b.volume!==null&&(!Number.isFinite(b.volume)||b.volume<0)))
  throw Error('Incomplete or invalid cross-timeframe input');
}
function samePrice(a:number,b:number){
 // Both timeframes come from the SAME archived M1 prices: open/close are
 // selected observations and high/low are extrema, not arithmetic estimates.
 // A relative/absolute epsilon can hide a real price change at very large
 // or very small nominal scales. Refuse any mismatch rather than guessing
 // the instrument's tick size or certifying rounded API responses.
 return a===b;
}

// Exact binary-fraction counts need no heuristic 64-ULP allowance. When
// every constituent is an exactly representable integer number of 2^-k
// units and their scaled sum remains safe, IEEE-754 power-of-two scaling
// and integer addition are exact. Refuse even one scaled-unit mismatch.
// Other reported decimal fractions retain the conservative tolerance below.
function dyadicVolumeMismatch(values:readonly number[],aggregate:number):boolean|null{
 for(let power=0;power<=16;power++){
  const factor=2**power;
  let unitsTotal=0,exact=true;
  for(const value of values){
   const units=value*factor;
   if(!Number.isSafeInteger(units)||!Number.isSafeInteger(unitsTotal+units)){
    exact=false;break;
   }
   unitsTotal+=units;
  }
  if(exact){
   const aggregateUnits=aggregate*factor;
   return !Number.isSafeInteger(aggregateUnits)||aggregateUnits!==unitsTotal;
  }
 }
 return null;
}

export function auditCrtCrossTimeframe(
 fourHour:readonly Bar[],fifteenMinute:readonly Bar[],
):CrossoverAudit{
 if(!Array.isArray(fourHour)||!Array.isArray(fifteenMinute)||
  fourHour.length>20000||fifteenMinute.length>20000)
  throw Error('Invalid or oversized cross-timeframe window');
 assertOwnBarSlots(fourHour);
 assertOwnBarSlots(fifteenMinute);
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
 const reconciledNumericVolumeStarts:number[]=[];
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
  // When both responses actually report volume, inconsistent aggregation
  // is an archive-integrity failure. This does NOT authenticate volume
  // provenance: null values remain unknown, never zero-filled or certified.
  if(h4.volume!==null&&subset.every(b=>b.volume!==null)){
   const total=subset.reduce((sum,b)=>sum+(b.volume??0),0);
   // Even fractional reported volumes cannot justify a whole-unit mismatch:
   // the unbounded scale-relative error budget previously allowed one-unit
   // drifts in large aggregates. A 0.25-unit cap is a conservative audit
   // ceiling, not a source-certified volume precision or broker tick size.
   // Do not impose a 1-unit scale floor: near-zero fractional volume must
   // not receive a fixed absolute error allowance larger than the data.
   const tolerance=Math.min(0.25,
    64*Number.EPSILON*Math.max(Math.abs(h4.volume),Math.abs(total)));
   // Integer constituent volumes represent exact counts, not floating-point
   // estimates. A scale-relative epsilon could otherwise hide one or more
   // real counts in a large archive. Refuse sums outside safe integer range.
   // Keep bounded summation tolerance only for genuinely fractional volumes.
   const integerCounts=subset.every(b=>b.volume!==null&&Number.isSafeInteger(b.volume));
   // Even fractional inputs become ambiguous once their integer magnitude
   // exceeds the safe range: JS doubles cannot retain one-unit differences.
   // A rounded 4H total may equal a rounded sum without proving coherence.
   const safeMagnitude=Number.isSafeInteger(Math.trunc(h4.volume))&&
    Number.isSafeInteger(Math.trunc(total))&&
    subset.every(b=>b.volume!==null&&Number.isSafeInteger(Math.trunc(b.volume)));
   const exactDyadicMismatch=dyadicVolumeMismatch(
    subset.map(b=>b.volume as number),h4.volume);
   const mismatch=exactDyadicMismatch??(integerCounts
    ? !Number.isSafeInteger(h4.volume)||!Number.isSafeInteger(total)||h4.volume!==total
    : Math.abs(h4.volume-total)>tolerance);
   if(!Number.isFinite(total)||!safeMagnitude||mismatch)
    throw Error('4H/15m volume mismatch for same historical archive');
   reconciledNumericVolumeStarts.push(h4.time);
  }
  checked++;
  verifiedFourHourStarts.push(h4.time);
  index+=BARS_PER_4H;
 }
 // Freeze the issued certificate AND its nested timestamp list. A caller
 // must not be able to rewrite displayed verification evidence in place;
 // re-audit instead of editing a previously issued report.
 const report:CrossoverAudit=Object.freeze({
  checkedFourHourBars:checked,uncheckableFourHourBars:uncheckable,
  verifiedFourHourStarts:Object.freeze(verifiedFourHourStarts),
  reconciledNumericVolumeStarts:Object.freeze(reconciledNumericVolumeStarts),
 });
 issuedSnapshots.set(report,{
  fourHour,fifteenMinute,
  fourHourRows:fourHour.slice(),fifteenMinuteRows:fifteenMinute.slice(),
  content:candleSnapshot(fourHour,fifteenMinute),
 });
 return report;
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
):readonly Bar[]{
 // A coherent change to both timeframe arrays can pass a fresh OHLC audit
 // while invalidating the original evidence snapshot. Never certify it with
 // a stale (or independently fabricated) report.
 const issued=audit&&issuedSnapshots.get(audit);
 // Do not reuse a certificate for replacement arrays, even when every
 // visible candle field happens to match. Re-audit the new source window.
 if(!issued||issued.fourHour!==fourHour||
  issued.fifteenMinute!==fifteenMinute||
  issued.content!==candleSnapshot(fourHour,fifteenMinute)||
  // Equal numeric values do not make a newly substituted candle object
  // part of the original audited response. Require a fresh audit for it.
  issued.fourHourRows.length!==fourHour.length||
  issued.fifteenMinuteRows.length!==fifteenMinute.length||
  issued.fourHourRows.some((bar,i)=>bar!==fourHour[i])||
  issued.fifteenMinuteRows.some((bar,i)=>bar!==fifteenMinute[i]))
  throw Error('Stale or inconsistent 4H/15m certification report');
 const current=auditCrtCrossTimeframe(fourHour,fifteenMinute);
 if(!Array.isArray(audit.verifiedFourHourStarts)||
  current.checkedFourHourBars!==audit.checkedFourHourBars||
  current.uncheckableFourHourBars!==audit.uncheckableFourHourBars||
  current.verifiedFourHourStarts.length!==audit.verifiedFourHourStarts.length||
  current.verifiedFourHourStarts.some((time,i)=>time!==audit.verifiedFourHourStarts[i])||
  current.reconciledNumericVolumeStarts.length!==audit.reconciledNumericVolumeStarts.length||
  current.reconciledNumericVolumeStarts.some((time,i)=>time!==audit.reconciledNumericVolumeStarts[i]))
  throw Error('Stale or inconsistent 4H/15m certification report');
 const verified=new Set(current.verifiedFourHourStarts);
 const reconciledVolume=new Set(current.reconciledNumericVolumeStarts);
 // Return detached, frozen evidence snapshots. Aliasing the mutable API bars
 // would let a later caller mutation silently rewrite an already-certified
 // CRT reference/sweep without re-running the source-coherence audit.
 // Freeze the collection as well as each candle: a consumer must not be
 // able to append a fabricated reference or remove an audited sweep after
 // certification, even if the individual candle objects are immutable.
 // An issued certificate covers only the seven validated Bar fields.
 // Object spread would also copy undeclared own keys and execute arbitrary
 // metadata getters, potentially laundering unverified feed claims into the
 // supposedly certified evidence or changing source state during cloning.
 return Object.freeze(fourHour.filter(b=>verified.has(b.time)).map(b=>Object.freeze({
  time:b.time,open:b.open,high:b.high,low:b.low,close:b.close,
  // Never carry an uncheckable 4H volume into a price-only certificate.
  // Even a reconciled total is NOT authenticated exchange/tick volume.
  volume:reconciledVolume.has(b.time)?b.volume:null,observed_minutes:b.observed_minutes,
 } satisfies Bar)));
}
