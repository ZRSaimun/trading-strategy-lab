/**
 * First-touch hourly FVG midpoint study (research only).
 *
 * The three-candle gap is known at the third bar CLOSE. Only the first
 * subsequently observed midpoint touch can qualify; failed touches are not
 * replaced with prettier future rejections. No broker order/fill is modeled.
 */
import type {Bar} from './research.ts';

export const HOURLY_FVG_VERSION='hourly-fvg-first-midpoint-touch-v55';
export type Evidence='PASS'|'FAIL'|'INSUFFICIENT_DATA';
// First-touch volume evidence is not independent broker/source authentication.
export type VolumeEvidenceReason='NOT_EVALUATED'|'SOURCE_UNVERIFIED'|
 'PRIOR20_UNAVAILABLE'|'PRIOR20_GAP'|'MISSING_OR_NONPOSITIVE_VOLUME'|
 'THRESHOLD_NOT_MET'|'THRESHOLD_EXCEEDED';
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
 // The historical BID entry price is evidenced only by its completed bar.
 // A next-open execution time is hypothetical; an intrabar limit time is unknown.
 entryObservedAt:number;hypotheticalEntryAt:number|null;
 entryPrice:number;exitObservedAt:number;exitPrice:number;
 grossBps:number;netBpsByCost:readonly {costBps:number;netBps:number}[];
};
export type FvgObservation={
 direction:Side;formationClosedAt:number;gapLow:number;gapHigh:number;
 midpoint:number;firstTouchClosedAt:number|null;
 // Earliest closed hourly bar at which this disposition is observable.
 // Null means the waiting window is incomplete, not a known negative.
 firstTouchOutcomeObservedAt:number|null;
 // Known strict eligibility is observed only at the touch-bar close or the
 // completed no-touch deadline, not at formation.
 strictCandidateObservedAt:number|null;
 // A hypothetical markout is observed at the exit-bar close, not entry.
 // Known no-entry failure is observed at the completed no-touch deadline.
 markoutOutcomeObservedAt:number|null;
 firstTouchOutcome:FirstTouchOutcome;
  // Missing interior source hours and incomplete archive tails are different
  // evidence gaps; neither can be treated as an observed no-touch failure.
  firstTouchCensorReason:FirstTouchCensorReason|null;
  // A missing interior hour becomes identifiable only after the first
  // subsequently observed hourly bar CLOSES. Null for an incomplete tail,
  // because absence of a future bar is not a timestamped missing-hour receipt.
  firstTouchCensorObservedAt:number|null;
  // A real midpoint intersection can have an unobserved fixed exit.
  // Do not confuse an interior source gap with an as-of/right-censored tail.
  markoutCensorReason:MarkoutCensorReason|null;
  // An interior exit gap is identifiable only at the next completed bar;
  // unrepresentable returns are known at the fixed exit close. A tail has
  // no timestamped missing-hour receipt and stays null.
  markoutCensorObservedAt:number|null;
  rejectionWickFraction:number|null;
 // The first completed touch fixes the volume reason, even when evidence is
 // insufficient. Null means no first-touch volume assessment has occurred.
 volumeEvidenceObservedAt:number|null;
 volumeEvidenceReason:VolumeEvidenceReason;
 gates:{midpointTouch:Evidence;wickRejection:Evidence;verifiedVolume:Evidence;
  strictCandidate:Evidence;markout:Evidence};
 blindMidpointTouch:Markout|null;confirmedNextOpen:Markout|null;
 eligibleForLiveTrading:false;
};
export type EvidenceCounts=Record<Evidence,number>;
export type FirstTouchOutcome='TOUCH'|'NO_TOUCH'|'OPEN_GAP_THROUGH'|'INCOMPLETE_WINDOW';
export type FirstTouchCensorReason='MISSING_HOUR'|'RIGHT_CENSORED';
export type MarkoutCensorReason=FirstTouchCensorReason|'UNREPRESENTABLE_RETURN';
// Exhaustive matched-pair net-sign cells for illustrative costs only.
export type PairedNetSignCells={
 bothPositive:number;blindOnlyPositive:number;
 confirmedOnlyPositive:number;neitherPositive:number;
};
// Directional ordering on the same matured matched fixed-exit population.
// Costs are not applied: equal scenario costs cancel in the comparison.
export type PairedGrossOrderingCells={
 confirmedHigher:number;blindHigher:number;equal:number;
};
export type PairedGrossOrderingCensus={
 all:PairedGrossOrderingCells;strict:PairedGrossOrderingCells;
 strictFail:PairedGrossOrderingCells;strictUnknown:PairedGrossOrderingCells;
};
export type PairedNetSignCostCensus={
 scenarioIndex:number;costBps:number;
 // Partition all matched outcomes by the declared strict evidence state.
 // Unknown volume evidence must not be pooled with a known failed gate.
 all:PairedNetSignCells;strict:PairedNetSignCells;
 strictFail:PairedNetSignCells;strictUnknown:PairedNetSignCells;
};
// Overlap is measured only between matured hypothetical confirmed-entry-to-exit
// windows. It is a dependence warning, not an effective sample-size estimate.
export type PairedWindowOverlapCensus={
 overlappingPairCombinations:number;maxConcurrentPairs:number;
};
// Mixed-evidence pairs overlap too. Keep these cross-status counts distinct
// from the within-status dependence census; no unknown becomes a PASS.
export type PairedCrossStrictOverlapCensus={
 passFail:number;passUnknown:number;failUnknown:number;
};
export type PairedMaximumDisjointCensus={
 all:number;strictPass:number;strictFail:number;strictUnknown:number;
};
export type FvgCohort={
 formations:number;firstTouchOutcome:Record<FirstTouchOutcome,number>;
 // Index zero is the first completed post-formation hour. Only timestamped
 // TOUCH, OPEN_GAP_THROUGH and completed NO_TOUCH outcomes are counted.
 // Missing-hour and right-censored windows cannot become observed negatives.
 firstDispositionWaitBarCounts:Record<'TOUCH'|'OPEN_GAP_THROUGH'|'NO_TOUCH',readonly number[]>;
 // Split the same observed wait population by formation direction; a pooled
 // histogram can hide asymmetric bullish/bearish first-touch attrition.
 firstDispositionWaitBarCountsByDirection:Record<Side,
  Record<'TOUCH'|'OPEN_GAP_THROUGH'|'NO_TOUCH',readonly number[]>>;
  incompleteWindowByReason:Record<FirstTouchCensorReason,number>;
  markoutCensoredByReason:Record<MarkoutCensorReason,number>;
 midpointTouch:EvidenceCounts;strictCandidate:EvidenceCounts;markout:EvidenceCounts;
 volumeEvidenceByReason:Record<VolumeEvidenceReason,number>;
 pairedMarkouts:number;strictPairedMarkouts:number;nonStrictPairedMarkouts:number;
 pairedNetSignByCost:readonly PairedNetSignCostCensus[];
 // Descriptive paired gross-BID markout ordering; not realized execution P&L.
 pairedGrossOrdering:PairedGrossOrderingCensus;
 pairedHoldingWindowOverlap:PairedWindowOverlapCensus;
 // Overlap within each declared strict evidence population; cross-status
 // overlapping pairs are intentionally not assigned to either subgroup.
 pairedHoldingWindowOverlapByStrictCandidate:Record<Evidence,PairedWindowOverlapCensus>;
 // Cross-status pair counts reconcile the full overlap count to its three
 // within-status counts, without treating unverified evidence as PASS.
 pairedHoldingWindowCrossStrictCandidate:PairedCrossStrictOverlapCensus;
 // Maximum non-overlapping completed hypothetical holding windows.
 // Status subset maxima are independently optimized, NOT additive.
 pairedMaximumDisjointWindows:PairedMaximumDisjointCensus;
 // Count matched and right-censored candidates by strict evidence status.
 pairedByStrictCandidate:EvidenceCounts;unpairedByStrictCandidate:EvidenceCounts;
 blindOnlyMarkouts:number;
};
export type FvgCoverage={
 firstBarOpenAt:number|null;lastBarClosedAt:number|null;
 observedBars:number;unobservedHourSlots:number;gapIntervals:number;
};
export type FvgStudy={
 version:typeof HOURLY_FVG_VERSION;source:FvgSource;coverage:FvgCoverage;
 config:Required<FvgConfig>;observations:FvgObservation[];cohort:FvgCohort;
 warning:string;
};
const HOUR=3600;
// Inherited prototype values cannot stand in for actual archive/source fields.
const CANDLE_FIELDS=['time','open','high','low','close','volume','observed_minutes'] as const;
const SOURCE_FIELDS=['datasetId','archiveSha256','instrument','provider',
 'priceSide','volumeType','volumeVerified'] as const;
// Only these explicit knobs are part of the frozen, reviewable experiment.
// Unknown own keys (including hidden or symbol keys) must not be ignored.
const CONFIG_FIELDS=['maxTouchWaitBars','markoutBars',
 'minimumRejectionWickFraction','volumeMultiple',
 'hypotheticalRoundTripCostsBps'] as const;
const hasOwnField=(value:object,field:PropertyKey)=>
 Object.prototype.hasOwnProperty.call(value,field);
// Preserve exact provider/instrument identities in exported research reports.
// Reject non-NFC aliases rather than silently normalizing their source bytes.
// Control, format and default-ignorable Unicode code points can conceal or
// spoof feed labels even when their strings look identical in a report.
function validSourceLabel(value:unknown):value is string{
 return typeof value==='string'&&value.length>=1&&value.length<=128&&
  value.trim()===value&&value.normalize('NFC')===value&&
  !/[\p{Cc}\p{Cf}\p{Zl}\p{Zp}\p{Default_Ignorable_Code_Point}]/u.test(value);
}
// A top-level archive array is only an ordered BID-candle population, not a
// container for silently discarded ASK quotes, broker receipts or provenance.
// Reject undeclared own metadata without reading its values. The iterator is
// deliberately ignored because both research paths read bounded own indices.
function validateBarArraySchema(bars:readonly Bar[],count:number){
 for(const key of Reflect.ownKeys(bars)){
  if(key==='length'||key===Symbol.iterator||
   (typeof key==='string'&&/^(0|[1-9][0-9]*)$/.test(key)&&Number(key)<count))
   continue;
  throw Error('Unexpected FVG archive array metadata outside frozen BID-only protocol');
 }
}
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
function verifiedVolume(bars:readonly Bar[],j:number,source:FvgSource,multiple:number):
 {evidence:Evidence;reason:VolumeEvidenceReason}{
 if(!source.volumeVerified||!['exchange','tick'].includes(source.volumeType))
  return {evidence:'INSUFFICIENT_DATA',reason:'SOURCE_UNVERIFIED'};
 if(j<20)return {evidence:'INSUFFICIENT_DATA',reason:'PRIOR20_UNAVAILABLE'};
 const history=bars.slice(j-20,j),now=bars[j];
 if(history.length!==20)return {evidence:'INSUFFICIENT_DATA',reason:'PRIOR20_UNAVAILABLE'};
 if(now.time-history[0].time!==20*HOUR)
  return {evidence:'INSUFFICIENT_DATA',reason:'PRIOR20_GAP'};
 if(now.volume===null||now.volume<=0||
  history.some(b=>b.volume===null||b.volume<=0))
  return {evidence:'INSUFFICIENT_DATA',reason:'MISSING_OR_NONPOSITIVE_VOLUME'};
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
 return lhs>rhs?
  {evidence:'PASS',reason:'THRESHOLD_EXCEEDED'}:
  {evidence:'FAIL',reason:'THRESHOLD_NOT_MET'};
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
 direction:Side,costs:readonly number[],hypotheticalEntryAt:number|null):Markout|null{
 const sign=direction==='BULLISH'?1:-1;
 const grossBps=sign*(exit-entry)/entry*10000;
 // Finite source OHLC can still overflow a bps ratio. Infinity is not a
 // measured return and must never enter a research report.
 if(!Number.isFinite(grossBps))return null;
 const netBpsByCost=costs.map(costBps=>({costBps,netBps:grossBps-costBps}));
 if(netBpsByCost.some(x=>!Number.isFinite(x.netBps)))return null;
 return {entryObservedAt:entryAt,hypotheticalEntryAt,entryPrice:entry,exitObservedAt:exitAt,
  exitPrice:exit,grossBps,netBpsByCost};
}
// Compare the *exact supplied IEEE-754 values* for the hypothetical net
// markout sign. A separately rounded grossBps - costBps can equal zero
// even when the true difference is positive (or vice versa). This is an
// evidence-census comparison, not a broker-executable profit calculation.
function positiveNetAfterCost(entry:number,exit:number,direction:Side,costBps:number):boolean{
 const entryParts=positiveFloatParts(entry),exitParts=positiveFloatParts(exit);
 const commonExponent=Math.min(entryParts.exponent,exitParts.exponent);
 const entryInteger=entryParts.mantissa<<BigInt(entryParts.exponent-commonExponent);
 const exitInteger=exitParts.mantissa<<BigInt(exitParts.exponent-commonExponent);
 const directionalMove=direction==='BULLISH'?
  exitInteger-entryInteger:entryInteger-exitInteger;
 if(directionalMove<=0n)return false;
 const costParts=positiveFloatParts(costBps);
 let lhs=directionalMove*10000n;
 let rhs=entryParts.mantissa*costParts.mantissa;
 const exponentDifference=commonExponent-entryParts.exponent-costParts.exponent;
 if(exponentDifference>=0)lhs<<=BigInt(exponentDifference);
 else rhs<<=BigInt(-exponentDifference);
 return lhs>rhs;
}
// Account for the full observed formation population, not just attractive
// confirmed returns. Unknown outcomes remain unknown, and blind-only markouts
// must not be presented as matched wick-versus-limit comparisons.
function summarizeCohort(observations:readonly FvgObservation[],costs:readonly number[],
 maxTouchWaitBars:number):FvgCohort{
 const count=(gate:'midpointTouch'|'strictCandidate'|'markout'):EvidenceCounts=>{
  const result:EvidenceCounts={PASS:0,FAIL:0,INSUFFICIENT_DATA:0};
  for(const observation of observations)result[observation.gates[gate]]++;
  return result;
 };
 const paired=(o:FvgObservation)=>o.blindMidpointTouch!==null&&o.confirmedNextOpen!==null;
 // Shared fixed-exit research windows make matched observations dependent.
 // Count pairwise overlaps on [hypothetical confirmed next-open, exit close),
 // not the unknown intrabar blind-limit fill time. An exit exactly at the
 // next entry is not an overlap. The sweep is O(n log n), bounded by the
 // validated 20,000-candle source population.
 const countOverlaps=(eligible:readonly FvgObservation[]):PairedWindowOverlapCensus=>{
 const pairedWindows=eligible.map(o=>{
  const confirmed=o.confirmedNextOpen!;
  const start=confirmed.hypotheticalEntryAt;
  if(start===null||start>=confirmed.exitObservedAt)
   throw Error('Paired FVG holding window evidence is inconsistent');
  return {start,end:confirmed.exitObservedAt};
 }).sort((a,b)=>a.start-b.start||a.end-b.end);
 const sortedEnds=pairedWindows.map(w=>w.end).sort((a,b)=>a-b);
 let expired=0,overlappingPairCombinations=0,maxConcurrentPairs=0;
 for(let index=0;index<pairedWindows.length;index++){
  while(expired<index&&sortedEnds[expired]<=pairedWindows[index].start)expired++;
  const concurrent=index-expired+1;
  overlappingPairCombinations+=concurrent-1;
  maxConcurrentPairs=Math.max(maxConcurrentPairs,concurrent);
 }
 return {overlappingPairCombinations,maxConcurrentPairs};
 };
 const matured=observations.filter(paired);
 // Earliest-finish interval scheduling maximizes the number of disjoint
 // completed hypothetical holding windows. This is a dependence sensitivity
 // count, not a statistically independent sample size or broker exposure.
 const maximumDisjoint=(eligible:readonly FvgObservation[]):number=>{
  const windows=eligible.map(o=>{
   const confirmed=o.confirmedNextOpen!;
   const start=confirmed.hypotheticalEntryAt;
   if(start===null||start>=confirmed.exitObservedAt)
    throw Error('Paired FVG holding window evidence is inconsistent');
   return {start,end:confirmed.exitObservedAt};
  }).sort((a,b)=>a.end-b.end||a.start-b.start);
  let count=0,lastExit=-Infinity;
  for(const window of windows){
   if(window.start>=lastExit){
    count++;
    lastExit=window.end;
   }
  }
  return count;
 };
 const pairedMaximumDisjointWindows:PairedMaximumDisjointCensus={
  all:maximumDisjoint(matured),
  strictPass:maximumDisjoint(matured.filter(o=>o.gates.strictCandidate==='PASS')),
  strictFail:maximumDisjoint(matured.filter(o=>o.gates.strictCandidate==='FAIL')),
  strictUnknown:maximumDisjoint(matured.filter(o=>
   o.gates.strictCandidate==='INSUFFICIENT_DATA')),
 };
 const pairedHoldingWindowOverlap=countOverlaps(matured);
 const pairedHoldingWindowOverlapByStrictCandidate:Record<Evidence,PairedWindowOverlapCensus>={
  PASS:countOverlaps(matured.filter(o=>o.gates.strictCandidate==='PASS')),
  FAIL:countOverlaps(matured.filter(o=>o.gates.strictCandidate==='FAIL')),
  INSUFFICIENT_DATA:countOverlaps(matured.filter(o=>o.gates.strictCandidate==='INSUFFICIENT_DATA')),
 };
 // The three within-status overlap counts omit pairs whose evidence states
 // differ. Count those disjoint cross-status combinations using the same
 // half-open completed holding windows. The O(n log n) sweep expires windows
 // at their exact exit time before admitting a new entry at that timestamp.
 const countCrossStrictOverlaps=(eligible:readonly FvgObservation[]):PairedCrossStrictOverlapCensus=>{
  const windows=eligible.map(o=>{
   const confirmed=o.confirmedNextOpen!;
   const start=confirmed.hypotheticalEntryAt;
   if(start===null||start>=confirmed.exitObservedAt)
    throw Error('Paired FVG holding window evidence is inconsistent');
   return {start,end:confirmed.exitObservedAt,status:o.gates.strictCandidate};
  }).sort((a,b)=>a.start-b.start||a.end-b.end);
  const byEnd=[...windows].sort((a,b)=>a.end-b.end);
  const active:EvidenceCounts={PASS:0,FAIL:0,INSUFFICIENT_DATA:0};
  const cross:PairedCrossStrictOverlapCensus={
   passFail:0,passUnknown:0,failUnknown:0,
  };
  let expired=0;
  for(const current of windows){
   while(expired<byEnd.length&&byEnd[expired].end<=current.start){
    active[byEnd[expired].status]--;
    expired++;
   }
   if(current.status==='PASS'){
    cross.passFail+=active.FAIL;
    cross.passUnknown+=active.INSUFFICIENT_DATA;
   }else if(current.status==='FAIL'){
    cross.passFail+=active.PASS;
    cross.failUnknown+=active.INSUFFICIENT_DATA;
   }else{
    cross.passUnknown+=active.PASS;
    cross.failUnknown+=active.FAIL;
   }
   active[current.status]++;
  }
  return cross;
 };
 const pairedHoldingWindowCrossStrictCandidate=countCrossStrictOverlaps(matured);
 const withinStatusOverlaps=Object.values(pairedHoldingWindowOverlapByStrictCandidate)
  .reduce((sum,group)=>sum+group.overlappingPairCombinations,0);
 const crossStatusOverlaps=Object.values(pairedHoldingWindowCrossStrictCandidate)
  .reduce((sum,count)=>sum+count,0);
 if(withinStatusOverlaps+crossStatusOverlaps!==
    pairedHoldingWindowOverlap.overlappingPairCombinations)
  throw Error('Paired FVG overlap populations do not reconcile');
 const volumeEvidenceByReason:Record<VolumeEvidenceReason,number>={
  NOT_EVALUATED:0,SOURCE_UNVERIFIED:0,PRIOR20_UNAVAILABLE:0,
  PRIOR20_GAP:0,MISSING_OR_NONPOSITIVE_VOLUME:0,
  THRESHOLD_NOT_MET:0,THRESHOLD_EXCEEDED:0,
 };
 for(const observation of observations)
  volumeEvidenceByReason[observation.volumeEvidenceReason]++;
 const pairedByStrictCandidate:EvidenceCounts={PASS:0,FAIL:0,INSUFFICIENT_DATA:0};
 const unpairedByStrictCandidate:EvidenceCounts={PASS:0,FAIL:0,INSUFFICIENT_DATA:0};
 for(const observation of observations){
  const counts=paired(observation)?pairedByStrictCandidate:unpairedByStrictCandidate;
  counts[observation.gates.strictCandidate]++;
 }
 // Compare the two fixed-exit gross BID markouts only after BOTH outcomes
 // mature. This ranking does not depend on an illustrative cost scenario
 // because both comparators subtract the same declared bps cost. It does
 // not establish an executable advantage or equal exposure/holding time.
 const emptyOrdering=():PairedGrossOrderingCells=>({
  confirmedHigher:0,blindHigher:0,equal:0,
 });
 const pairedGrossOrdering:PairedGrossOrderingCensus={
  all:emptyOrdering(),strict:emptyOrdering(),
  strictFail:emptyOrdering(),strictUnknown:emptyOrdering(),
 };
 for(const observation of observations){
  if(!paired(observation))continue;
  // For a shared positive exit, gross directional return is strictly
  // monotone in entry: lower is better for longs, higher for shorts.
  // Comparing rounded bps can falsely call one-ULP entry differences equal.
  const blindEntry=observation.blindMidpointTouch!.entryPrice;
  const confirmedEntry=observation.confirmedNextOpen!.entryPrice;
  const cell:keyof PairedGrossOrderingCells=blindEntry===confirmedEntry?'equal':
   observation.direction==='BULLISH'?
    confirmedEntry<blindEntry?'confirmedHigher':'blindHigher':
    confirmedEntry>blindEntry?'confirmedHigher':'blindHigher';
  pairedGrossOrdering.all[cell]++;
  if(observation.gates.strictCandidate==='PASS')pairedGrossOrdering.strict[cell]++;
  else if(observation.gates.strictCandidate==='FAIL')pairedGrossOrdering.strictFail[cell]++;
  else pairedGrossOrdering.strictUnknown[cell]++;
 }
 // Count every matured matched pair, not only attractive strict candidates.
 // Unpaired, right-censored and opening-gap-through outcomes are excluded.
 // Costs are hypothetical; zero net bps is nonpositive.
 const pairedNetSignByCost:PairedNetSignCostCensus[]=costs.map((costBps,scenarioIndex)=>{
  const empty=():PairedNetSignCells=>({
   bothPositive:0,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0,
  });
  const all=empty(),strict=empty(),strictFail=empty(),strictUnknown=empty();
  for(const observation of observations){
   if(!paired(observation))continue;
   const blind=observation.blindMidpointTouch!.netBpsByCost[scenarioIndex];
   const confirmed=observation.confirmedNextOpen!.netBpsByCost[scenarioIndex];
   if(!blind||!confirmed||blind.costBps!==costBps||confirmed.costBps!==costBps)
    throw Error('Paired FVG cost evidence is inconsistent');
   // Classify signs from exact validated entry/exit/cost floats, not from
   // rounded descriptive bps fields (which may display a false zero).
   const blindPositive=positiveNetAfterCost(
    observation.blindMidpointTouch!.entryPrice,observation.blindMidpointTouch!.exitPrice,
    observation.direction,costBps);
   const confirmedPositive=positiveNetAfterCost(
    observation.confirmedNextOpen!.entryPrice,observation.confirmedNextOpen!.exitPrice,
    observation.direction,costBps);
   const cell:keyof PairedNetSignCells=blindPositive?
    confirmedPositive?'bothPositive':'blindOnlyPositive':
    confirmedPositive?'confirmedOnlyPositive':'neitherPositive';
   all[cell]++;
   if(observation.gates.strictCandidate==='PASS')strict[cell]++;
   else if(observation.gates.strictCandidate==='FAIL')strictFail[cell]++;
   else strictUnknown[cell]++;
  }
  return {scenarioIndex,costBps,all,strict,strictFail,strictUnknown};
 });
 const firstTouchOutcome:Record<FirstTouchOutcome,number>={
  TOUCH:0,NO_TOUCH:0,OPEN_GAP_THROUGH:0,INCOMPLETE_WINDOW:0,
 };
 const incompleteWindowByReason:Record<FirstTouchCensorReason,number>={
  MISSING_HOUR:0,RIGHT_CENSORED:0,
 };
 const markoutCensoredByReason:Record<MarkoutCensorReason,number>={
  MISSING_HOUR:0,RIGHT_CENSORED:0,UNREPRESENTABLE_RETURN:0,
 };
 const emptyWaitCounts=():Record<'TOUCH'|'OPEN_GAP_THROUGH'|'NO_TOUCH',number[]>=>({
  TOUCH:Array(maxTouchWaitBars).fill(0),
  OPEN_GAP_THROUGH:Array(maxTouchWaitBars).fill(0),
  NO_TOUCH:Array(maxTouchWaitBars).fill(0),
 });
 const firstDispositionWaitBarCounts=emptyWaitCounts();
 const firstDispositionWaitBarCountsByDirection:Record<Side,
  Record<'TOUCH'|'OPEN_GAP_THROUGH'|'NO_TOUCH',number[]>>={
   BULLISH:emptyWaitCounts(),BEARISH:emptyWaitCounts(),
  };
 for(const observation of observations){
  firstTouchOutcome[observation.firstTouchOutcome]++;
  if(observation.firstTouchOutcome!=='INCOMPLETE_WINDOW'){
   const observedAt=observation.firstTouchOutcomeObservedAt;
   const wait=observedAt===null?NaN:
    (observedAt-observation.formationClosedAt)/HOUR;
   if(!Number.isSafeInteger(wait)||wait<1||wait>maxTouchWaitBars)
    throw Error('Observed FVG first-disposition wait is inconsistent');
   firstDispositionWaitBarCounts[observation.firstTouchOutcome][wait-1]++;
   firstDispositionWaitBarCountsByDirection[observation.direction]
    [observation.firstTouchOutcome][wait-1]++;
  }
  if(observation.firstTouchCensorReason!==null)
   incompleteWindowByReason[observation.firstTouchCensorReason]++;
  if(observation.markoutCensorReason!==null)
   markoutCensoredByReason[observation.markoutCensorReason]++;
 }
 for(const outcome of ['TOUCH','OPEN_GAP_THROUGH','NO_TOUCH'] as const){
  const accounted=firstDispositionWaitBarCounts[outcome].reduce((sum,n)=>sum+n,0);
  if(accounted!==firstTouchOutcome[outcome])
   throw Error('Observed FVG first-disposition wait census does not reconcile');
  const directionalAccounted=(['BULLISH','BEARISH'] as const).reduce((sum,side)=>
   sum+firstDispositionWaitBarCountsByDirection[side][outcome]
    .reduce((total,n)=>total+n,0),0);
  if(directionalAccounted!==accounted)
   throw Error('Directional FVG first-disposition wait census does not reconcile');
 }
 return {
  formations:observations.length,firstTouchOutcome,firstDispositionWaitBarCounts,
  firstDispositionWaitBarCountsByDirection,
  incompleteWindowByReason,
  pairedNetSignByCost,pairedGrossOrdering,pairedHoldingWindowOverlap,
  pairedHoldingWindowOverlapByStrictCandidate,
  pairedHoldingWindowCrossStrictCandidate,pairedMaximumDisjointWindows,
  markoutCensoredByReason,
  midpointTouch:count('midpointTouch'),volumeEvidenceByReason,
  strictCandidate:count('strictCandidate'),
  markout:count('markout'),
  pairedMarkouts:observations.filter(paired).length,
  pairedByStrictCandidate,unpairedByStrictCandidate,
  // A wick-only paired result is NOT a strict volume-qualified result.
  // The PASS label is based on caller-declared volume provenance; it is
  // not independent broker or exchange authentication.
  strictPairedMarkouts:observations.filter(o=>
   o.blindMidpointTouch!==null&&o.confirmedNextOpen!==null&&
   o.gates.strictCandidate==='PASS').length,
  nonStrictPairedMarkouts:observations.filter(o=>
   o.blindMidpointTouch!==null&&o.confirmedNextOpen!==null&&
   o.gates.strictCandidate!=='PASS').length,
  blindOnlyMarkouts:observations.filter(o=>
   o.blindMidpointTouch!==null&&o.confirmedNextOpen===null).length,
 };
}
// Count unobserved UTC hourly slots without treating session closures as
// feed errors or filling those slots with invented candles.
function summarizeCoverage(bars:readonly Bar[]):FvgCoverage{
 let unobservedHourSlots=0,gapIntervals=0;
 for(let i=1;i<bars.length;i++){
  const unobserved=(bars[i].time-bars[i-1].time)/HOUR-1;
  if(unobserved>0){unobservedHourSlots+=unobserved;gapIntervals++;}
 }
 return {firstBarOpenAt:bars.length?bars[0].time:null,
  lastBarClosedAt:bars.length?bars[bars.length-1].time+HOUR:null,
  observedBars:bars.length,unobservedHourSlots,gapIntervals};
}
export function studyHourlyFvgMidpoint(
 suppliedBars:readonly Bar[],source:FvgSource,config:FvgConfig={},
):FvgStudy{
 // Capture each supplied candle field exactly once before validation.
 // Accessor-backed/mutable input objects must not change between the
 // evidence check and the later formation, volume or return calculation.
 // Bound the array before copying; holes/invalid fields fail validation.
 if(!Array.isArray(suppliedBars)||suppliedBars.length>20000)
  throw Error('Invalid or oversized hourly research window');
 // Snapshot the population size as well as each candle. A getter may append
 // or remove elements while we read them; never let the loop expand to
 // include those late arrivals or silently accept a truncated population.
 const barCount=suppliedBars.length;
 validateBarArraySchema(suppliedBars,barCount);
 // Do not invoke a caller-controlled Symbol.iterator: a short Array can
 // otherwise yield unbounded or substituted candles despite the length cap.
 // Indexed reads keep the snapshot bounded and preserve sparse-hole rejection.
 const bars:Bar[]=[];
 for(let index=0;index<barCount;index++){
  // A hole may resolve through Array.prototype or a custom prototype to a
  // plausible candle. That is not an observed archive row: fail closed.
  if(!Object.prototype.hasOwnProperty.call(suppliedBars,index))
   throw Error('Hourly research array contains missing own-index candle evidence');
  const b=suppliedBars[index];
  if(!b||typeof b!=='object'||!CANDLE_FIELDS.every(field=>hasOwnField(b,field)))
   throw Error('Hourly research candle lacks own field evidence');
  // Undeclared price-side or broker-certification metadata must not be
  // silently dropped from a report describing a seven-field BID candle.
  // Inspect keys before any unknown accessor can execute.
  for(const key of Reflect.ownKeys(b)){
   if(!CANDLE_FIELDS.some(field=>field===key))
    throw Error('Unexpected FVG candle field outside frozen archive schema');
  }
  bars.push({
   time:b.time,open:b.open,high:b.high,low:b.low,close:b.close,
   volume:b.volume,observed_minutes:b.observed_minutes,
  });
 }
 if(suppliedBars.length!==barCount)
  throw Error('Hourly research candle array length changed during snapshot');
 // A research setting must be explicitly supplied or use its frozen default.
 // An inherited prototype value can silently shorten the touch window,
 // change the wick/volume threshold or replace the cost scenarios.
 // Never evaluate an inherited accessor while checking this boundary.
 if(!config||typeof config!=='object')
  throw Error('Invalid FVG study settings');
 // A typo or extra JSON key must not silently run with default settings
 // while the exported report appears to represent the caller's experiment.
 // Reflect.ownKeys catches nonenumerable and symbol fields without reading
 // their potentially hostile values or invoking property getters.
 for(const key of Reflect.ownKeys(config)){
  if(!CONFIG_FIELDS.some(field=>field===key))
   throw Error('Unexpected FVG study setting outside frozen protocol');
 }
 const readOwnSetting=<K extends keyof FvgConfig>(field:K):FvgConfig[K]|undefined=>{
  if(!hasOwnField(config,field)){
   if(field in config)
    throw Error('Inherited FVG study settings are not explicit research evidence');
   return undefined;
  }
  // An explicitly present null/undefined is a malformed declared experiment,
  // not permission to silently fall back to a different frozen setting.
  // Read the own value once so accessor-backed inputs cannot change later.
  const value=config[field];
  if(value===undefined||value===null)
   throw Error('Explicit nullish FVG study setting cannot select a frozen default');
  return value;
 };
 const maxTouchWaitBars=readOwnSetting('maxTouchWaitBars')??12;
 const markoutBars=readOwnSetting('markoutBars')??3;
 const minimumRejectionWickFraction=readOwnSetting('minimumRejectionWickFraction')??0.5;
 const volumeMultiple=readOwnSetting('volumeMultiple')??1.5;
 // Snapshot each caller-declared cost once before validating it. Array#some
 // skips sparse holes, and accessor-backed arrays can change after validation.
 // Array.from materializes holes as undefined (which fails validation) and
 // prevents a second read from silently changing reported net markouts.
 const suppliedCosts=readOwnSetting('hypotheticalRoundTripCostsBps')??[0,5,15];
 // Reject oversized arrays BEFORE Array.from: copying an untrusted array
 // with a huge declared length can exhaust memory before the later settings
 // validation runs. No scenario elements are read on this rejection path.
 if(!Array.isArray(suppliedCosts)||suppliedCosts.length<1||suppliedCosts.length>10)
  throw Error('Invalid source identity, volume provenance or frozen FVG study settings');
 // Likewise, an overridden iterator must not replace the validated cost
 // population or bypass the ten-scenario allocation bound. Fix the count
 // before reading getters, and reject an array resized during capture.
 const costCount=suppliedCosts.length;
 // A bps-only scenario list must not silently discard extra claimed broker
 // spreads, financing or certification fields. Inspect own keys without
 // evaluating unknown accessors. A custom iterator is ignored, not invoked:
 // index-only snapshots preserve the existing bounded-array contract.
 const allowedCostIndices=new Set(Array.from({length:costCount},(_,i)=>String(i)));
 for(const key of Reflect.ownKeys(suppliedCosts)){
  if(key==='length'||key===Symbol.iterator||
     (typeof key==='string'&&allowedCostIndices.has(key)))continue;
  throw Error('Unexpected FVG cost scenario field outside frozen bps-only protocol');
 }
 const costs:number[]=[];
 for(let index=0;index<costCount;index++){
  // Never allow inherited values to fill a missing cost-scenario cell.
  if(!Object.prototype.hasOwnProperty.call(suppliedCosts,index))
   throw Error('Invalid source identity, volume provenance or frozen FVG study settings');
  costs.push(suppliedCosts[index]);
 }
 if(suppliedCosts.length!==costCount)
  throw Error('Hypothetical CFD cost array length changed during snapshot');
 // Snapshot the seven allowlisted source fields exactly once. A mutable or
 // accessor-backed declaration must not pass validation as one identity,
 // qualify volume under another, then export a third identity.
 // This is consistency only; declarations are not independently authenticated.
 if(!source||typeof source!=='object'||
  !SOURCE_FIELDS.every(field=>hasOwnField(source,field)))
  throw Error('Invalid source identity, volume provenance or frozen FVG study settings');
 // Reject undeclared own source keys before reading their values. An extra
 // certification or side alias must not silently disappear from the exported
 // provenance while a researcher believes it was part of the study.
 // Reflect.ownKeys also catches hidden properties and symbols without
 // invoking unrecognized getters. This validates declarations, not vendors.
 for(const key of Reflect.ownKeys(source)){
  if(!SOURCE_FIELDS.some(field=>field===key))
   throw Error('Unexpected FVG source declaration outside frozen provenance schema');
 }
 const declaredSource:FvgSource={
  datasetId:source.datasetId,archiveSha256:source.archiveSha256,
  instrument:source.instrument,provider:source.provider,
  priceSide:source.priceSide,volumeType:source.volumeType,
  volumeVerified:source.volumeVerified,
 };
 // RegExp#test coerces objects via toString/Symbol.toPrimitive. A forged
 // object could pass a hash-shaped check then leak into exported provenance.
 // Require primitive strings before testing the exact lowercase SHA form.
 if(typeof declaredSource.datasetId!=='string'||
  typeof declaredSource.archiveSha256!=='string'||
  !/^[a-f0-9]{64}$/.test(declaredSource.datasetId)||
  !/^[a-f0-9]{64}$/.test(declaredSource.archiveSha256)||
  !validSourceLabel(declaredSource.instrument)||!validSourceLabel(declaredSource.provider)||
  declaredSource.priceSide!=='bid'||typeof declaredSource.volumeVerified!=='boolean'||
  !['exchange','tick','none','unverified'].includes(declaredSource.volumeType)||
  (declaredSource.volumeVerified&&!['exchange','tick'].includes(declaredSource.volumeType))||
  !Number.isSafeInteger(maxTouchWaitBars)||maxTouchWaitBars<1||maxTouchWaitBars>48||
  !Number.isSafeInteger(markoutBars)||markoutBars<1||markoutBars>48||
  !Number.isFinite(minimumRejectionWickFraction)||
  minimumRejectionWickFraction<0||minimumRejectionWickFraction>1||
  !Number.isFinite(volumeMultiple)||volumeMultiple<1||volumeMultiple>10||
  !Array.isArray(costs)||costs.length<1||costs.length>10||
  // A cost stress axis must be unique and ascending. Repeated or reversed
  // scenarios otherwise duplicate or scramble the paired outcome census.
  costs.some((x,i)=>!Number.isFinite(x)||x<0||x>1000||
   (i>0&&x<=costs[i-1])))
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
  let volumeEvidenceReason:VolumeEvidenceReason='NOT_EVALUATED';
  let volumeEvidenceObservedAt:number|null=null;
  let blind:Markout|null=null,confirmed:Markout|null=null;
  let markoutExitObservedAt:number|null=null;
  let windowComplete=true;
  let censorReason:FirstTouchCensorReason|null=null;
  let censorObservedAt:number|null=null;
  let markoutCensorReason:MarkoutCensorReason|null=null;
  let markoutCensorObservedAt:number|null=null;
  let openingGapThrough=false;
  let outcomeObservedAt:number|null=null;
  for(let wait=1;wait<=maxTouchWaitBars;wait++){
   const j=i+wait,b=bars[j],prev=bars[j-1];
   if(!b||b.time-prev.time!==HOUR){
    windowComplete=false;
    // A missing interior hour and a not-yet-observed tail are both unknown,
    // but have different data-quality implications for later validation.
    censorReason=!b?'RIGHT_CENSORED':'MISSING_HOUR';
    if(b)censorObservedAt=b.time+HOUR;
    break;
   }
   // A bar that OPENS beyond the midpoint has already jumped across the
   // proposed limit price. Even if its entire range stays beyond that level,
   // a later return cannot establish that the original order was filled.
   // Freeze the first gap-through rather than cherry-picking a later touch.
   if(bull?b.open<midpoint:b.open>midpoint){
    // Preserve a physical range intersection without asserting a fill.
    if(b.low<=midpoint&&b.high>=midpoint)touch=j;
    openingGapThrough=true;
    // An hourly historical open is not first-available tick evidence;
    // the complete gap-through bar is only observable at its close.
    outcomeObservedAt=b.time+HOUR;
    gates.midpointTouch='INSUFFICIENT_DATA';
    break;
   }
   if(b.low>midpoint||b.high<midpoint)continue;
   touch=j;
   outcomeObservedAt=b.time+HOUR;
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
   const volumeEvidence=verifiedVolume(bars,j,declaredSource,volumeMultiple);
   gates.verifiedVolume=volumeEvidence.evidence;
   volumeEvidenceReason=volumeEvidence.reason;
   // Do not backdate an unavailable source/volume reason to formation.
   volumeEvidenceObservedAt=outcomeObservedAt;
   gates.strictCandidate=gates.wickRejection==='FAIL'?'FAIL':
    gates.verifiedVolume;
   // Markout horizon is fixed in advance, never the best future close.
   // Both scenarios share the same exit close. The baseline assumes an
   // intrabar midpoint touch, not an observed executable broker fill.
   const exit=bars[j+markoutBars];
   let contiguous=true;
   for(let k=j+1;k<=j+markoutBars;k++){
    if(!bars[k]){
     contiguous=false;
     markoutCensorReason='RIGHT_CENSORED';
     break;
    }
    if(bars[k].time-bars[k-1].time!==HOUR){
     contiguous=false;
     markoutCensorReason='MISSING_HOUR';
     markoutCensorObservedAt=bars[k].time+HOUR;
     break;
    }
   }
   if(contiguous&&exit){
    const exitAt=exit.time+HOUR;
    // OHLC can establish a midpoint intersection only when the touch bar
    // closes. Its open timestamp is NOT an observed intrabar fill time.
    // The hypothetical limit price remains unchanged; no fill is certified.
    const blindCandidate=markout(b.time+HOUR,midpoint,exitAt,exit.close,direction,costs,null);
    // The next-open BID is a hypothetical execution price, not an independently
    // timestamped first-available quote. Completed OHLC proves that price only
    // at the NEXT bar close; keep the proposed opening time separately.
    const confirmedCandidate=gates.wickRejection==='PASS'?
     markout(bars[j+1].time+HOUR,bars[j+1].open,exitAt,exit.close,
      direction,costs,bars[j+1].time):null;
    // Preserve the matched comparison cohort. If either required return
    // overflows, do not report the other as a selectively retained outcome.
    if(blindCandidate&&(gates.wickRejection!=='PASS'||confirmedCandidate)){
     blind=blindCandidate;
     confirmed=confirmedCandidate;
     gates.markout='PASS';
     markoutExitObservedAt=exitAt;
    }else{
     // Both matched returns are withheld if one cannot be represented.
     // This is not missing market history and must not be pooled with it.
     markoutCensorReason='UNREPRESENTABLE_RETURN';
     markoutCensorObservedAt=exitAt;
    }
   }
   break; // FIRST midpoint touch only
  }
  // A fully observed waiting horizon without a touch is a known rejection,
  // not missing evidence. Keep incomplete/gap-through windows unknown.
  if(touch===null&&windowComplete&&!openingGapThrough){
   // A NO_TOUCH verdict requires all configured waiting bars to close.
   outcomeObservedAt=bars[i+maxTouchWaitBars].time+HOUR;
   gates.midpointTouch='FAIL';
   gates.strictCandidate='FAIL';
   // All waiting bars were observed without a fill opportunity. This is a
   // known no-entry outcome, not a missing future return. Keep gap-through
   // and truncated windows unknown; neither establishes a limit fill.
   gates.markout='FAIL';
  }
  observations.push({direction,formationClosedAt:third.time+HOUR,
   gapLow,gapHigh,midpoint,firstTouchClosedAt:touch===null?null:bars[touch].time+HOUR,
   firstTouchOutcomeObservedAt:outcomeObservedAt,
   strictCandidateObservedAt:gates.strictCandidate==='INSUFFICIENT_DATA'?null:outcomeObservedAt,
   markoutOutcomeObservedAt:gates.markout==='PASS'?markoutExitObservedAt:
    gates.markout==='FAIL'?outcomeObservedAt:null,
   firstTouchOutcome:openingGapThrough?'OPEN_GAP_THROUGH':
    touch!==null?'TOUCH':windowComplete?'NO_TOUCH':'INCOMPLETE_WINDOW',
   firstTouchCensorReason:censorReason,firstTouchCensorObservedAt:censorObservedAt,
   markoutCensorReason,markoutCensorObservedAt,
   rejectionWickFraction:wickFraction,volumeEvidenceObservedAt,
   volumeEvidenceReason,gates,
   blindMidpointTouch:blind,confirmedNextOpen:confirmed,
   eligibleForLiveTrading:false});
 }
 // The report and volume gates share the same validated allowlisted snapshot.
 return {version:HOURLY_FVG_VERSION,source:declaredSource,
   coverage:summarizeCoverage(bars),
  config:{maxTouchWaitBars,markoutBars,minimumRejectionWickFraction,
   volumeMultiple,hypotheticalRoundTripCostsBps:[...costs]},
  observations,cohort:summarizeCohort(observations,costs,maxTouchWaitBars),
  warning:'Read-only hourly BID OHLC research. Midpoint touch is a hypothetical blind limit, not an executable fill. Rejection entry uses only the next observed hourly open. Markouts omit intrabar stops, spreads, financing, news, slippage and broker contracts; bps costs are illustrative, not measured. No strategy edge or live execution is established.'};
}

// Evaluate an immutable completed-hour prefix even when a chart has already
// loaded later candles. Future OHLC/volume are never inspected. The cutoff
// is the close of the latest hour permitted to influence this report.
export function studyHourlyFvgMidpointAsOf(
 suppliedBars:readonly Bar[],source:FvgSource,asOfClosedAt:number,config:FvgConfig={},
):FvgStudy{
 if(!Number.isSafeInteger(asOfClosedAt)||asOfClosedAt<HOUR||asOfClosedAt%HOUR!==0)
  throw Error('Invalid UTC hourly as-of close');
 if(!Array.isArray(suppliedBars)||suppliedBars.length>20000)
  throw Error('Invalid or oversized hourly research window');
 const barCount=suppliedBars.length;
 validateBarArraySchema(suppliedBars,barCount);
 const prefix:Bar[]=[];
 let previousTime:number|null=null;
 for(let index=0;index<barCount;index++){
  // Even a future timestamp must be backed by an actual archive slot;
  // future OHLC, volume and minute coverage remain unread.
  if(!Object.prototype.hasOwnProperty.call(suppliedBars,index))
   throw Error('Hourly as-of input contains missing own-index candle evidence');
  const bar=suppliedBars[index];
  if(!bar||typeof bar!=='object'||!hasOwnField(bar,'time'))
   throw Error('Hourly as-of timestamp lacks own field evidence');
  // Check every supplied timestamp, including future timestamps, to reject
  // out-of-order/duplicate archives that could otherwise silently truncate
  // an eligible historical prefix at the first misplaced future candle.
  // Never inspect OHLC, volume or coverage of a future candle.
  const time=bar?.time;
  if(!Number.isSafeInteger(time)||time<0||time%HOUR!==0||
   !Number.isSafeInteger(time+HOUR)||
   (previousTime!==null&&time<=previousTime))
   throw Error('Invalid or unordered hourly as-of input timestamp');
  previousTime=time;
  if(time+HOUR>asOfClosedAt)continue;
  // Future OHLC remains unread; completed historical rows need own fields.
  if(!CANDLE_FIELDS.every(field=>hasOwnField(bar,field)))
   throw Error('Hourly as-of candle lacks own field evidence');
  // For completed candles only, reject unreviewed ASK/spread/source fields.
  // Future candles remain timestamp-only: do not inspect future metadata.
  for(const key of Reflect.ownKeys(bar)){
   if(!CANDLE_FIELDS.some(field=>field===key))
    throw Error('Unexpected FVG candle field outside frozen archive schema');
  }
  prefix.push({time,open:bar.open,high:bar.high,low:bar.low,
   close:bar.close,volume:bar.volume,observed_minutes:bar.observed_minutes});
 }
 if(suppliedBars.length!==barCount)
  throw Error('Hourly research candle array length changed during snapshot');
 return studyHourlyFvgMidpoint(prefix,source,config);
}
