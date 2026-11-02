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
// JS Date/ISO rendering stops at ±8.64e15 milliseconds. Safe integer seconds
// alone can still describe an unrenderable completed candle timestamp.
const MAX_ISO_SECONDS=8_640_000_000_000;

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
// Standard Array methods may be replaced on Array.prototype *after* this
// module loads. Own-slot and own-method checks alone cannot prevent a global
// iterator/species/method override from substituting unverified candles.
// Capture the expected intrinsic identities and inspect descriptors without
// invoking potentially hostile accessors. This is a local runtime fence,
// not a sandbox against code that tampered with intrinsics before import.
const STANDARD_ARRAY_METHODS=[
 ['map',Array.prototype.map],['slice',Array.prototype.slice],
 ['filter',Array.prototype.filter],['some',Array.prototype.some],
 ['every',Array.prototype.every],['reduce',Array.prototype.reduce],
 // The audit builds its verified-start and volume-coherence lists with push.
 // A replaced inherited push could forge or silently omit certified buckets.
 ['push',Array.prototype.push],
] as const;
const STANDARD_ARRAY_ITERATOR=Array.prototype[Symbol.iterator];
// Array.prototype.slice/map/filter consult Array[Symbol.species] through
// ArraySpeciesCreate. A changed global getter can substitute an attacker-
// controlled result even if all source arrays and inherited methods are
// otherwise ordinary. Pin the native descriptor before any such allocation.
const STANDARD_ARRAY_SPECIES=Object.getOwnPropertyDescriptor(Array,Symbol.species);
function hasStandardArrayIntrinsics():boolean{
 for(let i=0;i<STANDARD_ARRAY_METHODS.length;i++){
  // Index directly: tuple destructuring itself consults Array iteration.
  const name=STANDARD_ARRAY_METHODS[i][0],method=STANDARD_ARRAY_METHODS[i][1];
  if(Object.getOwnPropertyDescriptor(Array.prototype,name)?.value!==method)
   return false;
 }
 const species=Object.getOwnPropertyDescriptor(Array,Symbol.species);
 return Object.getOwnPropertyDescriptor(Array.prototype,Symbol.iterator)?.value===
   STANDARD_ARRAY_ITERATOR&&
  Object.getOwnPropertyDescriptor(Array.prototype,'constructor')?.value===Array&&
  !!species&&!!STANDARD_ARRAY_SPECIES&&
  species.get===STANDARD_ARRAY_SPECIES.get&&
  species.set===STANDARD_ARRAY_SPECIES.set&&
  species.enumerable===STANDARD_ARRAY_SPECIES.enumerable&&
  species.configurable===STANDARD_ARRAY_SPECIES.configurable&&
  Object.hasOwn(species,'value')===Object.hasOwn(STANDARD_ARRAY_SPECIES,'value');
}
function assertOwnDataFields(b:Bar):void{
 // API candles are plain JSON records. Accessor/inherited fields can change
 // between audit, snapshot and certification, or execute code on a read.
 // Reject them before touching any validated candle value.
 if(!b||typeof b!=='object') throw Error('Invalid cross-timeframe candle fields');
 // A JSON-decoded candle is an ordinary object. Custom/null prototypes can
 // carry inherited source or broker claims that the own-key audit never sees.
 // Refuse these records before reading any of their candle values.
 if(Object.getPrototypeOf(b)!==Object.prototype)
  throw Error('Cross-timeframe candle requires ordinary JSON object prototype');
 for(const field of BAR_FIELDS){
  const descriptor=Object.getOwnPropertyDescriptor(b,field);
  // A field hidden from JSON serialization is not an observed API field.
  // Require enumerable own data even if direct JS property reads succeed.
  if(!descriptor||!Object.hasOwn(descriptor,'value')||!descriptor.enumerable)
   throw Error('Cross-timeframe candle requires own data fields');
 }
 // A source candle is a seven-field JSON record, not a carrier for an
 // unreviewed ASK quote, provider identity or purported verification flag.
 // Check own keys (including non-enumerable keys and symbols) without reading
 // extra values or invoking their accessors. The certified copy uses only
 // declared fields, but silent metadata omission could mislead callers about
 // what the audit actually verified.
 for(const key of Reflect.ownKeys(b)){
  if(typeof key!=='string'||!BAR_FIELDS.some(field=>field===key))
   throw Error('Cross-timeframe candle contains undeclared source metadata');
 }
}
function assertOwnBarSlots(bars:readonly Bar[]):void{
 // JSON arrays contain direct indexed data entries. Accessor-backed or
 // inherited array elements could swap candle objects between the audit,
 // issued snapshot and certified-copy selection, even when candle fields
 // themselves are ordinary data properties.
 // A JSON-decoded array also has enumerable indexed entries; refuse hidden
 // in-memory slots instead of treating an exotic container as source data.
 for(let i=0;i<bars.length;i++){
  const descriptor=Object.getOwnPropertyDescriptor(bars,String(i));
  if(!descriptor||!Object.hasOwn(descriptor,'value')||!descriptor.enumerable)
   throw Error('Cross-timeframe window requires enumerable own data entries');
 }
 // Array.isArray and own indexed slots alone are insufficient: a caller
 // can override iteration, map, slice or filter to substitute different
 // candles AFTER indexed validation. API JSON arrays have the standard
 // Array prototype and no own method overrides. Refuse exotic arrays
 // before invoking any caller-supplied iterator or method.
 // Check indexed data first so a missing/inherited slot retains its
 // precise validation error even when the array prototype is exotic.
 if(Object.getPrototypeOf(bars)!==Array.prototype||
  Object.hasOwn(bars,Symbol.iterator)||
  // Array built-ins use ArraySpeciesCreate; an inherited or own
  // constructor/species getter must not run while certifying evidence.
  Object.hasOwn(bars,'constructor')||!hasStandardArrayIntrinsics())
  throw Error('Cross-timeframe window requires ordinary JSON array methods');
 for(let i=0;i<STANDARD_ARRAY_METHODS.length;i++){
  if(Object.hasOwn(bars,STANDARD_ARRAY_METHODS[i][0]))
   throw Error('Cross-timeframe window requires ordinary JSON array methods');
 }
 // Source arrays must be ordinary JSON candle lists, not containers for
 // undeclared ASK quotes, provider labels or broker-authentication claims.
 // Inspect keys without evaluating any additional property getter. Unknown
 // own metadata is rejected rather than silently ignored as source evidence.
 for(const key of Reflect.ownKeys(bars)){
  if(key==='length')continue;
  if(typeof key==='string'&&/^(0|[1-9][0-9]*)$/.test(key)&&
   Number(key)<bars.length)continue;
  throw Error('Cross-timeframe window contains undeclared source metadata');
 }
}
// JSON.stringify invokes inherited Array/Object.prototype.toJSON hooks.
// A constant-returning hook can mask coordinated edits to both timeframes.
// Serialize validated primitive fields with unambiguous fixed delimiters
// instead, preserving negative zero as a distinct source representation.
function candleSnapshot(fourHour:readonly Bar[],fifteenMinute:readonly Bar[]):string{
 const rows=(bars:readonly Bar[]):string=>{
  assertOwnBarSlots(bars);
  let snapshot=String(bars.length)+':';
  for(let i=0;i<bars.length;i++){
   const bar=bars[i];
   assertOwnDataFields(bar);
   for(const field of BAR_FIELDS){
    const value=bar[field];
    snapshot+=value===null?'null':Object.is(value,-0)?'-0':String(value);
    snapshot+=',';
   }
   snapshot+=';';
  }
  return snapshot;
 };
 return '4H:'+rows(fourHour)+'|15m:'+rows(fifteenMinute);
}

function assertComplete(b:Bar,seconds:number){
 assertOwnDataFields(b);
 if(!Number.isSafeInteger(b.time)||b.time<0||b.time%seconds!==0||
  // A safe bucket start can still overflow JS integer precision at close.
  // CRT decisions require exact completed-bar timestamps, never rounded ends.
  !Number.isSafeInteger(b.time+seconds)||
  // Historical CRT timestamps are displayed with Date.toISOString(). Do not
  // certify an otherwise safe-integer bar whose completed close cannot render.
  b.time+seconds>MAX_ISO_SECONDS||
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

// Power-of-two scaling preserves the exact binary64 value of each reported
// volume. Number-safe scaled sums are unnecessarily restrictive: a 16-bar
// aggregate can exceed 2^53 scaled units even when the original total is
// within the safe-magnitude policy. Accumulate the scaled integers as BigInt
// to reject a real fractional-unit mismatch rather than falling back to a
// permissive 64-ULP tolerance. Search up to 2^32 fractional units: stopping
// at 2^32 could miss exactly represented 2^-40 source increments whose
// aggregate drift falls inside a loose 64-ULP tolerance. Search through
// 2^52 units, within the binary64 significand precision range.
// A power-of-two multiply only shifts a finite binary64 exponent; BigInt
// then accumulates the resulting integral units without Number sum rounding. This only reconciles the numbers RECEIVED;
// it cannot recover precision already lost by the upstream data source.
function dyadicVolumeMismatch(values:readonly number[],aggregate:number):boolean|null{
 for(let power=0;power<=52;power++){
  const factor=2**power;
  let unitsTotal=0n,exact=true;
  for(const value of values){
   const units=value*factor;
   if(!Number.isInteger(units)){
    exact=false;break;
   }
   unitsTotal+=BigInt(units);
  }
  if(exact){
   const aggregateUnits=aggregate*factor;
   return !Number.isInteger(aggregateUnits)||
    BigInt(aggregateUnits)!==unitsTotal;
  }
 }
 return null;
}

// Even incomplete 4H coverage can disprove reported numeric volume: each
// observed nonnegative 15m contribution is a lower bound on its 4H total.
// Compare exactly when both sides admit a common binary-fraction scale;
// otherwise permit only bounded floating-point summation noise. This never
// certifies partial volume or authenticates its upstream source.
// Nonnegative 15m volumes form a lower bound on the containing 4H total.
// If one observed constituent already equals the entire reported total,
// any other strictly positive constituent is a definite contradiction,
// even when large-number Number addition and a capped tolerance hide it.
// This does not require knowing any missing constituent volume.
function exactContributorExceedsAggregate(observed:readonly number[],aggregate:number):boolean{
 let matchesAggregate=false,positiveContributors=0;
 for(const volume of observed){
  if(volume>0)positiveContributors++;
  if(volume>0&&volume===aggregate)matchesAggregate=true;
 }
 return matchesAggregate&&positiveContributors>1;
}

// All finite positive IEEE-754 volumes are exact multiples of 2^-1074.
// Comparing those integer units can prove a *specific* omitted positive
// constituent even when adding it to a large fractional 4H total rounds away.
// Require exact equality after removing one reported contributor: ordinary
// aggregate rounding (e.g. decimal 0.1 volumes) is not itself a failure.
// This checks only received numeric coherence, never volume source identity.
function exactBinaryVolumeUnits(value:number):bigint{
 if(value===0)return 0n;
 const bits=new DataView(new ArrayBuffer(8));
 bits.setFloat64(0,value);
 const high=bits.getUint32(0),low=bits.getUint32(4);
 const exponent=(high>>>20)&0x7ff;
 const fraction=(BigInt(high&0xfffff)<<32n)|BigInt(low);
 const significand=exponent===0?fraction:(1n<<52n)|fraction;
 return significand<<BigInt(exponent===0?0:exponent-1);
}
function exactOmittedPositiveVolume(observed:readonly number[],aggregate:number):boolean{
 if(observed.length<2)return false;
 const total=observed.reduce((sum,value)=>sum+exactBinaryVolumeUnits(value),0n);
 const omitted=total-exactBinaryVolumeUnits(aggregate);
 return omitted>0n&&observed.some(value=>
  value>0&&exactBinaryVolumeUnits(value)===omitted);
}

function partialVolumeExceeds(observed:readonly number[],aggregate:number):boolean{
 if(exactContributorExceedsAggregate(observed,aggregate)||
  exactOmittedPositiveVolume(observed,aggregate))return true;
 for(let power=0;power<=52;power++){
  const factor=2**power,scaledAggregate=aggregate*factor;
  if(!Number.isInteger(scaledAggregate))continue;
  let units=0n,exact=true;
  for(const value of observed){
   const scaled=value*factor;
   if(!Number.isInteger(scaled)){exact=false;break;}
   units+=BigInt(scaled);
  }
  if(exact)return units>BigInt(scaledAggregate);
 }
 // Non-dyadic fractions such as 0.1 may never reach integral scaled
 // units in the bounded dyadic search. A Number sum can round a positive
 // remainder away at the safe-integer ceiling. Compare the received whole
 // parts exactly before trusting that rounded fallback sum.
 const wholeParts=observed.reduce((sum,value)=>
  sum+BigInt(Math.trunc(value)),0n);
 const aggregateWhole=BigInt(Math.trunc(aggregate));
 if(wholeParts>aggregateWhole||
  (wholeParts===aggregateWhole&&aggregate%1===0&&
   observed.some(value=>value%1!==0)))return true;
 const sum=observed.reduce((total,value)=>total+value,0);
 const tolerance=Math.min(0.25,
  64*Number.EPSILON*Math.max(aggregate,sum));
 return !Number.isFinite(sum)||sum>aggregate+tolerance;
}

// A partially loaded 4H bucket cannot be fully certified. However, any
// actually observed constituent 15m high above its reported 4H high, low
// below its 4H low, or a known first-open/last-close disagreement is already
// a definitive contradiction. Do not hide that inconsistency under the
// "uncheckable boundary" label. Missing constituents are never fabricated.
// Binary search avoids scanning the full 15m window for each outside bar.
function assertPartialOverlapConsistent(h4:Bar,fifteenMinute:readonly Bar[]):void{
 let left=0,right=fifteenMinute.length;
 while(left<right){
  const mid=Math.floor((left+right)/2);
  if(fifteenMinute[mid].time<h4.time)left=mid+1;
  else right=mid;
 }
 const knownVolumes:number[]=[];
 for(let i=left;i<fifteenMinute.length;i++){
  const q=fifteenMinute[i];
  if(q.time>=h4.time+FOUR_HOUR)break;
  if(q.high>h4.high||q.low<h4.low||
   (q.time===h4.time&&q.open!==h4.open)||
   (q.time===h4.time+FOUR_HOUR-MIN15&&q.close!==h4.close))
   throw Error('Partial 4H/15m OHLC contradiction for same historical archive');
  if(h4.volume!==null&&q.volume!==null)knownVolumes.push(q.volume);
 }
 if(h4.volume!==null&&knownVolumes.length>0&&
  partialVolumeExceeds(knownVolumes,h4.volume))
  throw Error('Partial 4H/15m volume contradiction for same historical archive');
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
 // A missing 4H response can be hidden between two valid 4H candles even
 // while the same archive supplies all sixteen completed 15m constituents.
 // A normal market closure has no complete constituent bucket; do not
 // invent 4H candles for partial 15m data or outside the 4H response range.
 const firstFourHour=fourHour[0]?.time;
 const lastFourHour=fourHour[fourHour.length-1]?.time;
 if(firstFourHour!==undefined&&lastFourHour!==undefined){
  const fourHourTimes=new Set(fourHour.map(b=>b.time));
  for(let i=0;i+BARS_PER_4H<=fifteenMinute.length;i++){
   const bucket=fifteenMinute[i].time;
   if(bucket<=firstFourHour||bucket>=lastFourHour||
    bucket%FOUR_HOUR!==0||fourHourTimes.has(bucket))continue;
   let complete=true;
   for(let j=1;j<BARS_PER_4H;j++){
    if(fifteenMinute[i+j].time!==bucket+j*MIN15){
     complete=false;break;
    }
   }
   if(complete)
    throw Error('Missing 4H candle for complete 15m source bucket');
  }
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
   assertPartialOverlapConsistent(h4,fifteenMinute);
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
  // A null constituent prevents full numeric volume reconciliation,
  // but the other nonnegative 15m volumes still impose a hard lower bound
  // on the reported 4H total. Reject an impossible total without filling
  // the missing observation or upgrading it to volume certification.
  if(h4.volume!==null){
   const knownVolumes=subset.filter(b=>b.volume!==null)
    .map(b=>b.volume as number);
   if(knownVolumes.length>0&&knownVolumes.length<BARS_PER_4H&&
    partialVolumeExceeds(knownVolumes,h4.volume))
    throw Error('4H/15m partial volume contradiction for same historical archive');
  }
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
   // The rounded Number sum can remain <= MAX_SAFE_INTEGER even when the
   // true sum of the received nonnegative binary64 constituents is larger.
   // For example MAX_SAFE_INTEGER + 0.1 rounds back to MAX_SAFE_INTEGER.
   // Count integral parts exactly and conservatively bound the <1 remainders
   // before permitting a fractional-volume coherence certificate.
   const wholeUnits=subset.reduce((sum,b)=>
    sum+BigInt(Math.trunc(b.volume as number)),0n);
   const remainingUnits=BigInt(Number.MAX_SAFE_INTEGER)-wholeUnits;
   const fractionalRemainders=subset.reduce((sum,b)=>
    sum+((b.volume as number)%1),0);
   const sourceSumWithinSafeMagnitude=remainingUnits>=0n&&
    (fractionalRemainders===0||remainingUnits>16n||
     fractionalRemainders<Number(remainingUnits));
   // At a large nominal total, Number addition can erase a small but
   // positive constituent even below MAX_SAFE_INTEGER (e.g. 1e12 + 1e-8
   // rounds to 1e12). An integer aggregate cannot equal those same whole
   // units PLUS observed positive fractional volume.
   const roundedAwayPositiveFraction=Number.isInteger(h4.volume)&&
    wholeUnits===BigInt(h4.volume)&&fractionalRemainders>0;
   const exactDyadicMismatch=dyadicVolumeMismatch(
    subset.map(b=>b.volume as number),h4.volume);
   const mismatch=exactDyadicMismatch??(integerCounts
    ? !Number.isSafeInteger(h4.volume)||!Number.isSafeInteger(total)||h4.volume!==total
    : Math.abs(h4.volume-total)>tolerance);
   if(!Number.isFinite(total)||!safeMagnitude||
    !sourceSumWithinSafeMagnitude||roundedAwayPositiveFraction||
    (exactContributorExceedsAggregate(subset.map(b=>b.volume as number),h4.volume)||
     exactOmittedPositiveVolume(subset.map(b=>b.volume as number),h4.volume))||mismatch)
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
