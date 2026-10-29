import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpoint,studyHourlyFvgMidpointAsOf,type FvgSource,type FvgConfig} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

const H=3600,BASE=Date.UTC(2026,9,20)/1000;
const source:FvgSource={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'NSXUSD-CFD',provider:'authorized-test-archive',
 priceSide:'bid',volumeType:'exchange',volumeVerified:true};
const candle=(i:number,open=100,high=102,low=98,close=100,volume:number|null=100):Bar=>({
 time:BASE+i*H,open,high,low,close,volume,observed_minutes:60,
});
function fixture(){
 const bars=Array.from({length:40},(_,i)=>candle(i));
 bars[30]=candle(30,99,100,98,99);
 bars[31]=candle(31,100,102,99,101);
 bars[32]=candle(32,105,106,104,105);
 bars[33]=candle(33,105,106,101,105.5,200);
 bars[34]=candle(34,105.5,107,105,106);
 bars[35]=candle(35,106,108,105,107);
 bars[36]=candle(36,107,111,106,110);
 return bars;
}
const target=(bars:Bar[],s:FvgSource=source)=>{
 const observations=studyHourlyFvgMidpoint(bars,s).observations;
 const found=observations.find(x=>x.formationClosedAt===BASE+33*H);
 assert.ok(found,'expected exact 3-candle FVG');
 return found;
};
test('touched FVG markout censoring distinguishes missing exit hours, tails and overflow',()=>{
 for(const bearish of [false,true]){
  const flip=(series:Bar[])=>bearish?series.map(b=>({...b,
   open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close})):series;
  const missing=flip(fixture().filter(b=>b.time!==BASE+35*H));
  const tail=flip(fixture().slice(0,35));
  const overflow=flip(fixture());
  overflow[36]={...overflow[36],high:Number.MAX_VALUE,close:Number.MAX_VALUE};
  for(const [series,reason] of [
   [missing,'MISSING_HOUR'],[tail,'RIGHT_CENSORED'],
   [overflow,'UNREPRESENTABLE_RETURN'],
  ] as const){
   const observation=target(series);
   assert.equal(observation.firstTouchOutcome,'TOUCH');
   assert.equal(observation.firstTouchCensorReason,null);
   assert.equal(observation.gates.markout,'INSUFFICIENT_DATA');
   assert.equal(observation.markoutCensorReason,reason);
   assert.equal(observation.markoutOutcomeObservedAt,null);
   assert.equal(observation.blindMidpointTouch,null);
   assert.equal(observation.confirmedNextOpen,null);
   const report=studyHourlyFvgMidpoint(series,source);
   assert.ok(report.cohort.markoutCensoredByReason[reason]>0);
   const total=Object.values(report.cohort.markoutCensoredByReason)
    .reduce((sum,n)=>sum+n,0);
   assert.equal(total,report.observations.filter(o=>
    o.firstTouchOutcome==='TOUCH'&&o.gates.markout==='INSUFFICIENT_DATA').length);
  }
  assert.equal(target(flip(fixture())).markoutCensorReason,null);
 }
});

test('incomplete first-touch windows separate missing archive hours from right-censored tails',()=>{
 for(const bearish of [false,true]){
  const flip=(series:Bar[])=>bearish?series.map(b=>({...b,
   open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close})):series;
  const missing=flip(fixture().filter(b=>b.time!==BASE+33*H));
  const tail=flip(fixture().slice(0,33));
  for(const [series,reason] of [
   [missing,'MISSING_HOUR'],[tail,'RIGHT_CENSORED'],
  ] as const){
   const observation=target(series);
   assert.equal(observation.firstTouchOutcome,'INCOMPLETE_WINDOW');
   assert.equal(observation.firstTouchCensorReason,reason);
   assert.equal(observation.firstTouchOutcomeObservedAt,null);
   assert.equal(observation.gates.midpointTouch,'INSUFFICIENT_DATA');
   assert.equal(observation.gates.strictCandidate,'INSUFFICIENT_DATA');
   assert.equal(observation.gates.markout,'INSUFFICIENT_DATA');
   const report=studyHourlyFvgMidpoint(series,source);
   assert.ok(report.cohort.incompleteWindowByReason[reason]>0);
   assert.equal(report.cohort.incompleteWindowByReason.MISSING_HOUR+
    report.cohort.incompleteWindowByReason.RIGHT_CENSORED,
    report.cohort.firstTouchOutcome.INCOMPLETE_WINDOW);
  }
  assert.equal(target(flip(fixture())).firstTouchCensorReason,null);
 }
});

test('as-of hourly study never reads future OHLC or promotes right-censored returns',()=>{
 const bars=fixture();
 const formationClose=BASE+33*H,touchClose=BASE+34*H,exitClose=BASE+37*H;
 const formationOnly=studyHourlyFvgMidpointAsOf(bars,source,formationClose);
 assert.deepEqual(formationOnly,studyHourlyFvgMidpoint(bars.slice(0,33),source));
 const before=formationOnly.observations.find(x=>x.formationClosedAt===formationClose);
 assert.ok(before);
 assert.equal(before.gates.strictCandidate,'INSUFFICIENT_DATA');
 assert.equal(before.gates.markout,'INSUFFICIENT_DATA');
 assert.equal(before.firstTouchOutcomeObservedAt,null);
 const futureProtected=fixture();
 Object.defineProperty(futureProtected[34],'open',{get(){throw Error('future open read');}});
 Object.defineProperty(futureProtected[34],'volume',{get(){throw Error('future volume read');}});
 const touchOnly=studyHourlyFvgMidpointAsOf(futureProtected,source,touchClose);
 assert.deepEqual(touchOnly,studyHourlyFvgMidpoint(bars.slice(0,34),source));
 const atTouch=touchOnly.observations.find(x=>x.formationClosedAt===formationClose);
 assert.ok(atTouch);
 assert.equal(atTouch.gates.strictCandidate,'PASS');
 assert.equal(atTouch.gates.markout,'INSUFFICIENT_DATA');
 assert.equal(atTouch.markoutOutcomeObservedAt,null);
 const atExit=studyHourlyFvgMidpointAsOf(bars,source,exitClose);
 assert.deepEqual(atExit,studyHourlyFvgMidpoint(bars.slice(0,37),source));
 const matured=atExit.observations.find(x=>x.formationClosedAt===formationClose);
 assert.ok(matured);
 assert.equal(matured.gates.markout,'PASS');
 assert.equal(matured.markoutOutcomeObservedAt,exitClose);
 for(const cutoff of [NaN,Infinity,-H,BASE+H/2,Number.MAX_SAFE_INTEGER])
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,cutoff),/Invalid UTC hourly as-of close/);
});

test('as-of prefix rejects out-of-order future timestamps without reading future prices',()=>{
 const bars=fixture(),cutoff=BASE+33*H;
 const baseline=studyHourlyFvgMidpoint(bars.slice(0,33),source);
 const protectedFuture=fixture();
 let futureTimeReads=0;
 for(let i=33;i<protectedFuture.length;i++){
  const time=protectedFuture[i].time;
  Object.defineProperty(protectedFuture[i],'time',{get(){
   futureTimeReads++;
   return time;
  }});
  for(const field of ['open','high','low','close','volume','observed_minutes'])
   Object.defineProperty(protectedFuture[i],field,{get(){
    throw Error('future '+field+' must not be inspected');
   }});
 }
 assert.deepEqual(studyHourlyFvgMidpointAsOf(protectedFuture,source,cutoff),baseline);
 assert.equal(futureTimeReads,protectedFuture.length-33,
  'all future timestamps are checked for ordering without reading future prices');
 // Previously the first future candle terminated the scan, silently hiding
 // an older eligible candle and producing a plausible but incomplete report.
 const interleaved=[...bars.slice(0,33),bars[35],bars[33],bars[34]];
 assert.throws(()=>studyHourlyFvgMidpointAsOf(interleaved,source,cutoff),
  /Invalid or unordered hourly as-of input timestamp/);
 const duplicatedFuture=[...bars.slice(0,33),bars[34],bars[34]];
 assert.throws(()=>studyHourlyFvgMidpointAsOf(duplicatedFuture,source,cutoff),
  /Invalid or unordered hourly as-of input timestamp/);
 const invalidFuture=[...bars.slice(0,33),{...bars[34],time:bars[34].time+1}];
 assert.throws(()=>studyHourlyFvgMidpointAsOf(invalidFuture,source,cutoff),
  /Invalid or unordered hourly as-of input timestamp/);
});

test('strict and markout clocks are causal for bullish/bearish paired, rejected and censored cases',()=>{
 for(const bearish of [false,true]){
  const flip=(series:Bar[])=>bearish?series.map(b=>({...b,
   open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close})):series;
  const paired=target(flip(fixture()));
  assert.equal(paired.formationClosedAt,BASE+33*H);
  assert.equal(paired.firstTouchOutcomeObservedAt,BASE+34*H);
  assert.equal(paired.gates.strictCandidate,'PASS');
  assert.equal(paired.strictCandidateObservedAt,BASE+34*H);
  assert.equal(paired.gates.markout,'PASS');
  assert.equal(paired.markoutOutcomeObservedAt,BASE+37*H);
  assert.equal(paired.markoutOutcomeObservedAt,paired.blindMidpointTouch?.exitObservedAt);
  assert.ok((paired.markoutOutcomeObservedAt??0)>(paired.strictCandidateObservedAt??0));
  const failed=fixture();failed[33]=candle(33,105,106,101,102.5,200);
  const blindOnly=target(flip(failed));
  assert.equal(blindOnly.gates.strictCandidate,'FAIL');
  assert.equal(blindOnly.strictCandidateObservedAt,BASE+34*H);
  assert.equal(blindOnly.gates.markout,'PASS');
  assert.equal(blindOnly.markoutOutcomeObservedAt,BASE+37*H);
  const untouched=fixture();
  for(let i=33;i<=44;i++){
   if(i>=untouched.length)untouched.push(candle(i,105,106,104,105));
   else untouched[i]=candle(i,105,106,104,105);
  }
  const noTouch=target(flip(untouched));
  assert.equal(noTouch.gates.strictCandidate,'FAIL');
  assert.equal(noTouch.gates.markout,'FAIL');
  assert.equal(noTouch.strictCandidateObservedAt,BASE+45*H);
  assert.equal(noTouch.markoutOutcomeObservedAt,BASE+45*H);
  const censored=target(flip(untouched.slice(0,44)));
  assert.equal(censored.strictCandidateObservedAt,null);
  assert.equal(censored.markoutOutcomeObservedAt,null);
  const gap=fixture();gap[33]=candle(33,101,106,100,105.5,200);
  const unobservable=target(flip(gap));
  assert.equal(unobservable.gates.strictCandidate,'INSUFFICIENT_DATA');
  assert.equal(unobservable.strictCandidateObservedAt,null);
  assert.equal(unobservable.markoutOutcomeObservedAt,null);
 }
});

test('bounded FVG studies ignore untrusted array iterators for candles and costs',()=>{
 const baseline=studyHourlyFvgMidpoint(fixture(),source);
 const candles=fixture();
 const costs=[0,5,15];
 // Array.from and for...of can invoke an attacker-controlled iterator
 // that yields an unlimited or substituted stream despite a short length.
 Object.defineProperty(candles,Symbol.iterator,{value(){
  throw Error('untrusted candle iterator invoked');
 }});
 Object.defineProperty(costs,Symbol.iterator,{value(){
  throw Error('untrusted cost iterator invoked');
 }});
 const settings={hypotheticalRoundTripCostsBps:costs};
 assert.deepEqual(studyHourlyFvgMidpoint(candles,source,settings),baseline);
 const asOf=BASE+37*H;
 assert.deepEqual(studyHourlyFvgMidpointAsOf(candles,source,asOf,settings),
  studyHourlyFvgMidpointAsOf(fixture(),source,asOf));
 // Sparse indexed candles must still fail closed rather than being
 // filled or hidden by a custom iterator.
 const sparse=fixture();
 delete (sparse as Array<Bar|undefined>)[33];
 Object.defineProperty(sparse,Symbol.iterator,{value(){
  throw Error('sparse candle iterator invoked');
 }});
 assert.throws(()=>studyHourlyFvgMidpoint(sparse as Bar[],source),
  /own-index candle evidence/);
});

test('research rejects candle and cost array resizing during evidence snapshots',()=>{
 const appended=fixture();
 let candleReads=0;
 Object.defineProperty(appended[0],'open',{get(){
  candleReads++;
  appended.push(candle(40));
  return 100;
 }});
 assert.throws(()=>studyHourlyFvgMidpoint(appended,source),
  /Hourly research candle array length changed during snapshot/);
 assert.equal(candleReads,1,'candle getter must be evaluated only once');

 const futureTruncated=fixture();
 const cutoff=BASE+33*H;
 const last=futureTruncated[futureTruncated.length-1];
 Object.defineProperty(last,'time',{get(){
  futureTruncated.pop();
  return BASE+39*H;
 }});
 assert.throws(()=>studyHourlyFvgMidpointAsOf(futureTruncated,source,cutoff),
  /Hourly research candle array length changed during snapshot/);

 const costs=[0,5,15];
 let costReads=0;
 Object.defineProperty(costs,'0',{get(){
  costReads++;
  costs.push(25);
  return 0;
 }});
 assert.throws(()=>studyHourlyFvgMidpoint(fixture(),source,{
  hypotheticalRoundTripCostsBps:costs,
 }),/Hypothetical CFD cost array length changed during snapshot/);
 assert.equal(costReads,1,'cost getter must be evaluated only once');
 assert.deepEqual(studyHourlyFvgMidpoint(fixture(),source).config.hypotheticalRoundTripCostsBps,
  [0,5,15],'stable research configurations remain valid');
});

test('hourly candle fields are snapshotted once before validation and research',()=>{
 const stable=target(fixture());
 const bars=fixture();
 let highReads=0,volumeReads=0;
 // Accessor-backed inputs can be valid at validation and turn invalid or
 // change identity before the return/volume gate is computed. Snapshot once.
 Object.defineProperty(bars[33],'high',{get(){
  highReads++;
  return highReads===1?106:NaN;
 }});
 Object.defineProperty(bars[33],'volume',{get(){
  volumeReads++;
  return volumeReads===1?200:NaN;
 }});
 assert.deepEqual(target(bars),stable);
 assert.equal(highReads,1,'OHLC must not be reread after its initial snapshot');
 assert.equal(volumeReads,1,'volume must not change after validation');
 const invalid=fixture();
 Object.defineProperty(invalid[33],'low',{get(){return NaN;}});
 assert.throws(()=>studyHourlyFvgMidpoint(invalid,source),/Invalid, incomplete/);
});

test('source metadata is snapshotted once across validation, volume gates and export',()=>{
 const baseline=studyHourlyFvgMidpoint(fixture(),source);
 const changing={...source};
 const reads:Partial<Record<keyof FvgSource,number>>={};
 for(const field of Object.keys(source) as (keyof FvgSource)[]){
  let count=0;
  Object.defineProperty(changing,field,{get(){
   count++;
   reads[field]=count;
   return count===1?source[field]:undefined;
  }});
 }
 const report=studyHourlyFvgMidpoint(fixture(),changing);
 assert.deepEqual(report,baseline,
  'a validated declaration must not change before volume gating or export');
 for(const field of Object.keys(source) as (keyof FvgSource)[])
  assert.equal(reads[field],1,field+' must be read exactly once');
 const invalid={...source};
 let providerReads=0;
 Object.defineProperty(invalid,'provider',{get(){
  providerReads++;
  return providerReads===1?' invalid-source':'valid-source';
 }});
 assert.throws(()=>studyHourlyFvgMidpoint(fixture(),invalid),/Invalid source/);
 assert.equal(providerReads,1,'invalid initial identity must not be reread into validity');
});

test('archive hashes must be primitive strings, not coercible objects',()=>{
 for(const field of ['datasetId','archiveSha256'] as const){
  let coercions=0;
  // RegExp#test historically coerced this object into a valid-looking hash,
  // while the report exported the original object as its source identity.
  const forged={
   [Symbol.toPrimitive](){coercions++;return source[field];},
   privatePayload:'not-a-hash',
  };
  const untrusted={...source,[field]:forged} as unknown as FvgSource;
  assert.throws(()=>studyHourlyFvgMidpoint(fixture(),untrusted),/Invalid source/);
  assert.equal(coercions,0,'hash validation must not invoke user coercion');
  const boxed={...source,[field]:new String(source[field])} as unknown as FvgSource;
  assert.throws(()=>studyHourlyFvgMidpoint(fixture(),boxed),/Invalid source/);
 }
 // Proper lowercase primitive hashes remain valid and preserve exact identity.
 const valid=studyHourlyFvgMidpoint(fixture(),source);
 assert.equal(valid.source.datasetId,source.datasetId);
 assert.equal(valid.source.archiveSha256,source.archiveSha256);
});

test('oversized hypothetical cost arrays fail before allocation or element access',()=>{
 const oversized:number[]=[];
 // Array.from would try to materialize one billion elements before the
 // old post-copy length check, risking browser memory exhaustion.
 oversized.length=1_000_000_000;
 let reads=0;
 Object.defineProperty(oversized,'0',{get(){
  reads++;
  throw Error('oversized array element must not be evaluated');
 }});
 assert.throws(()=>studyHourlyFvgMidpoint(fixture(),source,{
  hypotheticalRoundTripCostsBps:oversized,
 }),/Invalid source identity, volume provenance or frozen FVG study settings/);
 assert.equal(reads,0,'reject array length before accessing any cost element');
 assert.throws(()=>studyHourlyFvgMidpoint(fixture(),source,{
  hypotheticalRoundTripCostsBps:[],
 }),/Invalid source/);
 const valid=studyHourlyFvgMidpoint(fixture(),source,{
  hypotheticalRoundTripCostsBps:[0,5,15],
 });
 assert.deepEqual(valid.config.hypotheticalRoundTripCostsBps,[0,5,15]);
});

test('formation census preserves unknown outcomes and distinguishes paired from blind-only markouts',()=>{
 const bars=[
  candle(0,99,100,98,99),candle(1,100,102,99,101),
  candle(2,105,106,104,105),candle(3,105,106,101,105.5,200),
  candle(4,105.5,107,105,106),candle(5,106,108,105,107),
  candle(6,107,111,106,110),
 ];
 const run=(series:Bar[])=>studyHourlyFvgMidpoint(series,source);
 const paired=run(bars);
 assert.equal(paired.observations.length,1);
 assert.deepEqual(paired.cohort,{
  formations:1,
  firstTouchOutcome:{TOUCH:1,NO_TOUCH:0,OPEN_GAP_THROUGH:0,INCOMPLETE_WINDOW:0},
  firstTouchOpportunityBounds:{
   all:{formations:1,observedTouches:1,observedNoTouches:0,
    unresolvedGapThrough:0,unresolvedIncomplete:0,
    lowerObservedTouchFraction:1,upperPossibleTouchFraction:1},
   byDirection:{
    BULLISH:{formations:1,observedTouches:1,observedNoTouches:0,
     unresolvedGapThrough:0,unresolvedIncomplete:0,
     lowerObservedTouchFraction:1,upperPossibleTouchFraction:1},
    BEARISH:{formations:0,observedTouches:0,observedNoTouches:0,
     unresolvedGapThrough:0,unresolvedIncomplete:0,
     lowerObservedTouchFraction:null,upperPossibleTouchFraction:null},
   },
  },
  firstDispositionWaitBarCounts:{
   TOUCH:[1,...Array(11).fill(0)],
   OPEN_GAP_THROUGH:Array(12).fill(0),
   NO_TOUCH:Array(12).fill(0),
  },
  firstDispositionWaitBarCountsByDirection:{
   BULLISH:{TOUCH:[1,...Array(11).fill(0)],
    OPEN_GAP_THROUGH:Array(12).fill(0),NO_TOUCH:Array(12).fill(0)},
   BEARISH:{TOUCH:Array(12).fill(0),
    OPEN_GAP_THROUGH:Array(12).fill(0),NO_TOUCH:Array(12).fill(0)},
  },
  firstTouchStrictCandidateByWait:{
   PASS:Array(12).fill(0),FAIL:Array(12).fill(0),
   INSUFFICIENT_DATA:[1,...Array(11).fill(0)],
  },
  firstTouchStrictCandidateByWaitByDirection:{
   BULLISH:{PASS:Array(12).fill(0),FAIL:Array(12).fill(0),
    INSUFFICIENT_DATA:[1,...Array(11).fill(0)]},
   BEARISH:{PASS:Array(12).fill(0),FAIL:Array(12).fill(0),
    INSUFFICIENT_DATA:Array(12).fill(0)},
  },
  firstTouchPairedByWaitAndStrictCandidate:{
   PASS:Array(12).fill(0),FAIL:Array(12).fill(0),
   INSUFFICIENT_DATA:[1,...Array(11).fill(0)],
  },
  firstTouchUnpairedByWaitAndStrictCandidate:{
   PASS:Array(12).fill(0),FAIL:Array(12).fill(0),
   INSUFFICIENT_DATA:Array(12).fill(0),
  },
  firstTouchPairedByWaitAndStrictCandidateByDirection:{
   BULLISH:{PASS:Array(12).fill(0),FAIL:Array(12).fill(0),
    INSUFFICIENT_DATA:[1,...Array(11).fill(0)]},
   BEARISH:{PASS:Array(12).fill(0),FAIL:Array(12).fill(0),
    INSUFFICIENT_DATA:Array(12).fill(0)},
  },
  firstTouchUnpairedByWaitAndStrictCandidateByDirection:{
   BULLISH:{PASS:Array(12).fill(0),FAIL:Array(12).fill(0),
    INSUFFICIENT_DATA:Array(12).fill(0)},
   BEARISH:{PASS:Array(12).fill(0),FAIL:Array(12).fill(0),
    INSUFFICIENT_DATA:Array(12).fill(0)},
  },
  firstTouchObservedExposureByWait:[1,...Array(11).fill(0)],
  firstTouchObservedExposureByWaitByDirection:{
   BULLISH:[1,...Array(11).fill(0)],BEARISH:Array(12).fill(0),
  },
  firstTouchCensoredAfterWaitByReason:{
   MISSING_HOUR:Array(12).fill(0),RIGHT_CENSORED:Array(12).fill(0),
  },
  firstTouchCensoredAfterWaitByReasonByDirection:{
   BULLISH:{MISSING_HOUR:Array(12).fill(0),RIGHT_CENSORED:Array(12).fill(0)},
   BEARISH:{MISSING_HOUR:Array(12).fill(0),RIGHT_CENSORED:Array(12).fill(0)},
  },
  incompleteWindowByReason:{MISSING_HOUR:0,RIGHT_CENSORED:0},
  firstTouchMissingHourSeverity:{single:0,multiple:0,unobservedSlots:0},
  markoutMissingHourSeverity:{single:0,multiple:0,unobservedSlots:0},
  markoutCensoredByReason:{MISSING_HOUR:0,RIGHT_CENSORED:0,UNREPRESENTABLE_RETURN:0},
  markoutCensoredByReasonByStrictCandidate:{
   PASS:{MISSING_HOUR:0,RIGHT_CENSORED:0,UNREPRESENTABLE_RETURN:0},
   FAIL:{MISSING_HOUR:0,RIGHT_CENSORED:0,UNREPRESENTABLE_RETURN:0},
   INSUFFICIENT_DATA:{MISSING_HOUR:0,RIGHT_CENSORED:0,UNREPRESENTABLE_RETURN:0},
  },
  markoutCensoredByReasonByDirectionAndStrictCandidate:{
   BULLISH:{
    PASS:{MISSING_HOUR:0,RIGHT_CENSORED:0,UNREPRESENTABLE_RETURN:0},
    FAIL:{MISSING_HOUR:0,RIGHT_CENSORED:0,UNREPRESENTABLE_RETURN:0},
    INSUFFICIENT_DATA:{MISSING_HOUR:0,RIGHT_CENSORED:0,UNREPRESENTABLE_RETURN:0},
   },
   BEARISH:{
    PASS:{MISSING_HOUR:0,RIGHT_CENSORED:0,UNREPRESENTABLE_RETURN:0},
    FAIL:{MISSING_HOUR:0,RIGHT_CENSORED:0,UNREPRESENTABLE_RETURN:0},
    INSUFFICIENT_DATA:{MISSING_HOUR:0,RIGHT_CENSORED:0,UNREPRESENTABLE_RETURN:0},
   },
  },
  pairedGrossOrdering:{
   all:{confirmedHigher:0,blindHigher:1,equal:0},
   strict:{confirmedHigher:0,blindHigher:0,equal:0},
   strictFail:{confirmedHigher:0,blindHigher:0,equal:0},
   strictUnknown:{confirmedHigher:0,blindHigher:1,equal:0},
   byDirection:{
    BULLISH:{
     all:{confirmedHigher:0,blindHigher:1,equal:0},
     strict:{confirmedHigher:0,blindHigher:0,equal:0},
     strictFail:{confirmedHigher:0,blindHigher:0,equal:0},
     strictUnknown:{confirmedHigher:0,blindHigher:1,equal:0},
    },
    BEARISH:{
     all:{confirmedHigher:0,blindHigher:0,equal:0},
     strict:{confirmedHigher:0,blindHigher:0,equal:0},
     strictFail:{confirmedHigher:0,blindHigher:0,equal:0},
     strictUnknown:{confirmedHigher:0,blindHigher:0,equal:0},
    },
   },
  },
  pairedNetSignByCost:[0,5,15].map((costBps,scenarioIndex)=>({
   scenarioIndex,costBps,
   all:{bothPositive:1,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0},
   strict:{bothPositive:0,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0},
   strictFail:{bothPositive:0,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0},
   strictUnknown:{bothPositive:1,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0},
   byFirstTouchWaitAndStrictCandidate:{
    PASS:Array.from({length:12},()=>({bothPositive:0,blindOnlyPositive:0,
     confirmedOnlyPositive:0,neitherPositive:0})),
    FAIL:Array.from({length:12},()=>({bothPositive:0,blindOnlyPositive:0,
     confirmedOnlyPositive:0,neitherPositive:0})),
    INSUFFICIENT_DATA:[{bothPositive:1,blindOnlyPositive:0,
     confirmedOnlyPositive:0,neitherPositive:0},
     ...Array.from({length:11},()=>({bothPositive:0,blindOnlyPositive:0,
      confirmedOnlyPositive:0,neitherPositive:0}))],
   },
   byDirectionAndFirstTouchWaitAndStrictCandidate:{
    BULLISH:{PASS:Array.from({length:12},()=>({bothPositive:0,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0})),FAIL:Array.from({length:12},()=>({bothPositive:0,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0})),
     INSUFFICIENT_DATA:[{bothPositive:1,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0},...Array.from({length:11},()=>({bothPositive:0,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0}))]},
    BEARISH:{PASS:Array.from({length:12},()=>({bothPositive:0,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0})),FAIL:Array.from({length:12},()=>({bothPositive:0,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0})),
     INSUFFICIENT_DATA:Array.from({length:12},()=>({bothPositive:0,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0}))},
   },
   byDirection:{
    BULLISH:{
     all:{bothPositive:1,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0},
     strict:{bothPositive:0,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0},
     strictFail:{bothPositive:0,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0},
     strictUnknown:{bothPositive:1,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0},
    },
    BEARISH:{
     all:{bothPositive:0,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0},
     strict:{bothPositive:0,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0},
     strictFail:{bothPositive:0,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0},
     strictUnknown:{bothPositive:0,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0},
    },
   },
  })),
  midpointTouch:{PASS:1,FAIL:0,INSUFFICIENT_DATA:0},
  strictCandidate:{PASS:0,FAIL:0,INSUFFICIENT_DATA:1},
  markout:{PASS:1,FAIL:0,INSUFFICIENT_DATA:0},
  pairedHoldingWindowOverlap:{overlappingPairCombinations:0,maxConcurrentPairs:1},
  pairedHoldingWindowOverlapByDirection:{
   BULLISH:{overlappingPairCombinations:0,maxConcurrentPairs:1},
   BEARISH:{overlappingPairCombinations:0,maxConcurrentPairs:0},
  },
  pairedHoldingWindowCrossDirection:0,
  pairedHoldingWindowOverlapByStrictCandidate:{
   PASS:{overlappingPairCombinations:0,maxConcurrentPairs:0},
   FAIL:{overlappingPairCombinations:0,maxConcurrentPairs:0},
   INSUFFICIENT_DATA:{overlappingPairCombinations:0,maxConcurrentPairs:1},
  },
  pairedHoldingWindowCrossStrictCandidate:{passFail:0,passUnknown:0,failUnknown:0},
  pairedMaximumDisjointWindows:{all:1,strictPass:0,strictFail:0,strictUnknown:1},
  volumeEvidenceByReason:{
   NOT_EVALUATED:0,SOURCE_UNVERIFIED:0,PRIOR20_UNAVAILABLE:1,
   PRIOR20_GAP:0,MISSING_OR_NONPOSITIVE_VOLUME:0,
   THRESHOLD_NOT_MET:0,THRESHOLD_EXCEEDED:0,
  },
  volumeEvidenceByReasonByDirection:{
   BULLISH:{NOT_EVALUATED:0,SOURCE_UNVERIFIED:0,PRIOR20_UNAVAILABLE:1,
    PRIOR20_GAP:0,MISSING_OR_NONPOSITIVE_VOLUME:0,
    THRESHOLD_NOT_MET:0,THRESHOLD_EXCEEDED:0},
   BEARISH:{NOT_EVALUATED:0,SOURCE_UNVERIFIED:0,PRIOR20_UNAVAILABLE:0,
    PRIOR20_GAP:0,MISSING_OR_NONPOSITIVE_VOLUME:0,
    THRESHOLD_NOT_MET:0,THRESHOLD_EXCEEDED:0},
  },
  pairedMarkouts:1,strictPairedMarkouts:0,nonStrictPairedMarkouts:1,
  pairedByStrictCandidate:{PASS:0,FAIL:0,INSUFFICIENT_DATA:1},
  unpairedByStrictCandidate:{PASS:0,FAIL:0,INSUFFICIENT_DATA:0},
  pairedByDirectionAndStrictCandidate:{
   BULLISH:{PASS:0,FAIL:0,INSUFFICIENT_DATA:1},
   BEARISH:{PASS:0,FAIL:0,INSUFFICIENT_DATA:0},
  },
  unpairedByDirectionAndStrictCandidate:{
   BULLISH:{PASS:0,FAIL:0,INSUFFICIENT_DATA:0},
   BEARISH:{PASS:0,FAIL:0,INSUFFICIENT_DATA:0},
  },
  blindOnlyMarkouts:0,
 });
 const failedWick=[...bars];
 failedWick[3]=candle(3,105,106,101,102.5,200);
 const rejected=run(failedWick).cohort;
 assert.equal(rejected.strictCandidate.FAIL,1);
 assert.equal(rejected.markout.PASS,1,'blind-only result is still observed');
 assert.equal(rejected.pairedMarkouts,0,'failed wick cannot enter matched cohort');
 assert.equal(rejected.blindOnlyMarkouts,1);
 const openingGap=[...bars];
 openingGap[3]=candle(3,101,106,100,105.5,200);
 const unknown=run(openingGap).cohort;
 assert.equal(unknown.midpointTouch.INSUFFICIENT_DATA,1);
 assert.equal(unknown.strictCandidate.INSUFFICIENT_DATA,1);
 assert.equal(unknown.markout.INSUFFICIENT_DATA,1);
 assert.equal(unknown.pairedMarkouts,0);
 assert.equal(unknown.blindOnlyMarkouts,0);
 const missingExit=run(bars.slice(0,4)).cohort;
 assert.equal(missingExit.midpointTouch.PASS,1);
 assert.equal(missingExit.markout.INSUFFICIENT_DATA,1);
 assert.equal(missingExit.pairedMarkouts,0);
 assert.equal(missingExit.blindOnlyMarkouts,0);
 const missingTouch=run(bars.slice(0,3)).cohort;
 assert.equal(missingTouch.midpointTouch.INSUFFICIENT_DATA,1);
 assert.equal(missingTouch.formations,1);
});
test('paired FVG census does not conflate wick-only pairs with strict declared-volume candidates',()=>{
 const declared=studyHourlyFvgMidpoint(fixture(),source);
 const strictObservation=target(fixture());
 assert.equal(strictObservation.gates.strictCandidate,'PASS');
 assert.ok(declared.cohort.strictPairedMarkouts>=1);
 const unknownSource={...source,volumeType:'unverified' as const,volumeVerified:false};
 const unknown=studyHourlyFvgMidpoint(fixture(),unknownSource);
 assert.equal(target(fixture(),unknownSource).gates.strictCandidate,'INSUFFICIENT_DATA');
 assert.equal(unknown.cohort.strictPairedMarkouts,0);
 assert.ok(unknown.cohort.nonStrictPairedMarkouts>=1,
  'a valid wick alone must not be counted as strict volume evidence');
 const below=fixture();
 below[33].volume=120;
 assert.equal(target(below).gates.strictCandidate,'FAIL');
 const rejected=studyHourlyFvgMidpoint(below,source);
 for(const report of [declared,unknown,rejected]){
  assert.equal(report.cohort.pairedMarkouts,
   report.cohort.strictPairedMarkouts+report.cohort.nonStrictPairedMarkouts);
 }
 assert.equal(rejected.cohort.strictPairedMarkouts,0);
 assert.ok(rejected.cohort.nonStrictPairedMarkouts>=1);
 // Even a synthetic strict PASS is only a caller declaration, not proof of
 // authenticated source volume, an executable fill or profitability.
 assert.equal(strictObservation.eligibleForLiveTrading,false);
});
test('first-touch census distinguishes observed no-touch, gap-through and missing history',()=>{
 const noTouch=fixture();
 for(let i=33;i<45;i++)noTouch[i]=candle(i,105,106,104,105);
 const gapThrough=fixture();
 gapThrough[33]=candle(33,100,101,99,100,200);
 const crossingGap=fixture();
 crossingGap[33]=candle(33,101,106,100,105.5,200);
 const missing=fixture().filter(b=>b.time!==BASE+33*H);
 const cases:[Bar[],string][]=[
  [fixture(),'TOUCH'],[noTouch,'NO_TOUCH'],
  [gapThrough,'OPEN_GAP_THROUGH'],[crossingGap,'OPEN_GAP_THROUGH'],
  [missing,'INCOMPLETE_WINDOW'],[fixture().slice(0,33),'INCOMPLETE_WINDOW'],
 ];
 for(const bearish of [false,true])for(const [input,expected] of cases){
  const bars=bearish?input.map(b=>({...b,open:220-b.open,
   high:220-b.low,low:220-b.high,close:220-b.close})):input;
  const report=studyHourlyFvgMidpoint(bars,source);
  const formation=report.observations.find(o=>o.formationClosedAt===BASE+33*H);
  assert.ok(formation);
  assert.equal(formation.firstTouchOutcome,expected);
  if(expected==='OPEN_GAP_THROUGH'){
   assert.equal(formation.gates.midpointTouch,'INSUFFICIENT_DATA');
   assert.equal(formation.blindMidpointTouch,null);
  }
  if(expected==='NO_TOUCH')assert.equal(formation.gates.midpointTouch,'FAIL');
  if(expected==='INCOMPLETE_WINDOW')
   assert.equal(formation.gates.midpointTouch,'INSUFFICIENT_DATA');
  const counts=report.cohort.firstTouchOutcome;
  assert.equal(counts.TOUCH+counts.NO_TOUCH+counts.OPEN_GAP_THROUGH+
   counts.INCOMPLETE_WINDOW,report.cohort.formations);
  for(const outcome of Object.keys(counts) as (keyof typeof counts)[])
   assert.equal(counts[outcome],report.observations.filter(o=>o.firstTouchOutcome===outcome).length);
 }
});
test('first-touch dispositions become known only at completed-bar close',()=>{
 const untouched=fixture();
 for(let i=33;i<=44;i++){
  const bar=candle(i,105,106,104,105);
  if(i<untouched.length)untouched[i]=bar;
  else untouched.push(bar);
 }
 const gapThrough=fixture();
 gapThrough[33]=candle(33,100,101,99,100,200);
 for(const bearish of [false,true]){
  const side=(bars:Bar[])=>bearish?bars.map(b=>({...b,
   open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close})):bars;
  const touch=target(side(fixture()));
  assert.equal(touch.firstTouchOutcome,'TOUCH');
  assert.equal(touch.firstTouchOutcomeObservedAt,BASE+34*H);
  assert.equal(touch.firstTouchOutcomeObservedAt,touch.firstTouchClosedAt);
  const partial=target(side(untouched.slice(0,44)));
  assert.equal(partial.firstTouchOutcome,'INCOMPLETE_WINDOW');
  assert.equal(partial.firstTouchOutcomeObservedAt,null,
   'eleven observed no-touch bars cannot establish a twelve-bar negative');
  const complete=target(side(untouched));
  assert.equal(complete.firstTouchOutcome,'NO_TOUCH');
  assert.equal(complete.firstTouchOutcomeObservedAt,BASE+45*H);
  assert.equal(complete.firstTouchClosedAt,null);
  const gap=target(side(gapThrough));
  assert.equal(gap.firstTouchOutcome,'OPEN_GAP_THROUGH');
  assert.equal(gap.firstTouchOutcomeObservedAt,BASE+34*H,
   'historical hourly OHLC cannot certify the opening quote before close');
  assert.equal(gap.firstTouchClosedAt,null);
  const missing=target(side(fixture().filter(b=>b.time!==BASE+33*H)));
  assert.equal(missing.firstTouchOutcome,'INCOMPLETE_WINDOW');
  assert.equal(missing.firstTouchOutcomeObservedAt,null);
 }
});
test('paired and censored strict-gate cohorts reconcile without promoting missing evidence',()=>{
 const failedWick=fixture();
 failedWick[33]=candle(33,105,106,101,102.5,200);
 const gapThrough=fixture();
 gapThrough[33]=candle(33,100,101,99,100,200);
 const reports=[
  studyHourlyFvgMidpoint(fixture(),source),
  studyHourlyFvgMidpoint(fixture().slice(0,35),source),
  studyHourlyFvgMidpoint(fixture(),{...source,volumeType:'unverified',volumeVerified:false}),
  studyHourlyFvgMidpoint(failedWick,source),
  studyHourlyFvgMidpoint(gapThrough,source),
 ];
 for(const {cohort} of reports){
  for(const gate of ['PASS','FAIL','INSUFFICIENT_DATA'] as const)
   assert.equal(cohort.pairedByStrictCandidate[gate]+cohort.unpairedByStrictCandidate[gate],
    cohort.strictCandidate[gate],'no candidate may disappear from the cohort');
  const sum=(counts:typeof cohort.strictCandidate)=>
   counts.PASS+counts.FAIL+counts.INSUFFICIENT_DATA;
  assert.equal(sum(cohort.pairedByStrictCandidate),cohort.pairedMarkouts);
  assert.equal(sum(cohort.unpairedByStrictCandidate),cohort.formations-cohort.pairedMarkouts);
  assert.equal(cohort.pairedByStrictCandidate.PASS,cohort.strictPairedMarkouts);
  assert.equal(cohort.pairedByStrictCandidate.FAIL+
   cohort.pairedByStrictCandidate.INSUFFICIENT_DATA,cohort.nonStrictPairedMarkouts);
 }
 assert.ok(reports[0].cohort.pairedByStrictCandidate.PASS>0);
 assert.ok(reports[1].cohort.unpairedByStrictCandidate.PASS>0,
  'strictly qualified touch without a complete exit must stay unpaired');
 assert.ok(reports[2].cohort.pairedByStrictCandidate.INSUFFICIENT_DATA>0,
  'a paired wick-only return cannot authenticate unknown volume');
 assert.ok(reports[3].cohort.unpairedByStrictCandidate.FAIL>0);
 assert.ok(reports[4].cohort.unpairedByStrictCandidate.INSUFFICIENT_DATA>0,
  'opening gap-through cannot become a paired return');
});
test('research report rejects extra source fields without leaking caller private metadata',()=>{
 // TypeScript structural typing does not remove runtime fields. Reject a
 // richer vendor object instead of silently dropping unsupported claims or
 // accidentally exporting credential-like data in a research report.
 const richerSource={...source,debugAccessToken:'synthetic-private-marker',
  rawVendorPayload:{account:'synthetic-account-marker'}};
 for(const study of [
  ()=>studyHourlyFvgMidpoint(fixture(),richerSource),
  ()=>studyHourlyFvgMidpointAsOf(fixture(),richerSource,BASE+37*H),
 ]){
  assert.throws(study,(error:unknown)=>error instanceof Error&&
   /Unexpected FVG source declaration/.test(error.message)&&
   !error.message.includes('synthetic-private-marker')&&
   !error.message.includes('synthetic-account-marker'));
 }
 const report=studyHourlyFvgMidpoint(fixture(),source);
 assert.deepEqual(report.source,source);
 assert.deepEqual(Object.keys(report.source).sort(),Object.keys(source).sort());
 assert.equal(report.version,'hourly-fvg-first-midpoint-touch-v92');
});
test('ambiguous source labels and contradictory volume evidence fail closed',()=>{
 // These are declared metadata, not independent vendor authentication.
 // Exact source identities must not acquire aliases or log delimiters.
 for(const invalid of [
  {...source,instrument:' NSXUSD-CFD'},
  {...source,instrument:'NSXUSD-CFD '},
  {...source,provider:'feed\nsecond'},
  {...source,provider:'feed\u2028second'},
  {...source,provider:'p'.repeat(129)},
  {...source,volumeType:'none' as const,volumeVerified:true},
  {...source,volumeType:'unverified' as const,volumeVerified:true},
 ]){
  assert.throws(()=>studyHourlyFvgMidpoint(fixture(),invalid),/Invalid source/);
 }
 const exact={...source,instrument:'NSXUSD-CFD / BID',provider:'Research feed A'};
 assert.deepEqual(studyHourlyFvgMidpoint(fixture(),exact).source,exact);
});
test('invisible and bidirectional Unicode source controls cannot spoof feed identity',()=>{
 // Control characters can reverse or hide displayed instrument/provider
 // names without changing their exact strings. Do not export such labels.
 for(const character of ['\u202e','\u202a','\u2066','\u2069','\u200b','\u200d','\u061c','\ufeff']){
  for(const field of ['provider','instrument'] as const){
   assert.throws(()=>studyHourlyFvgMidpoint(fixture(),{
    ...source,[field]:field==='provider'?'feed'+character+'A':'NSX'+character+'USD',
   }),/Invalid source/);
  }
 }
 // Legitimate non-ASCII provider identities remain distinguishable.
 const legitimate={...source,provider:'Données marché',instrument:'Índice Oro'};
 assert.deepEqual(studyHourlyFvgMidpoint(fixture(),legitimate).source,legitimate);
});
test('v52 source identities reject noncanonical and default-ignorable Unicode aliases',()=>{
 // Two visually identical labels must not silently form separate source IDs.
 // Do not normalize a declaration on behalf of a source or claim authentication.
 const bars=fixture(),cutoff=BASE+37*H;
 const baseline=studyHourlyFvgMidpoint(bars,source);
 const canonical={...source,provider:'Caf\u00e9 market',instrument:'\u00cdndice Oro'};
 const valid=studyHourlyFvgMidpoint(bars,canonical);
 assert.deepEqual(valid.source,canonical,'NFC non-ASCII identities remain exact');
 assert.deepEqual(studyHourlyFvgMidpointAsOf(bars,canonical,cutoff).source,canonical);
 for(const invalid of [
  {...source,provider:'Cafe\u0301 market'},
  {...source,instrument:'I\u0301ndice Oro'},
  {...source,provider:'feed\u00adA'}, // soft hyphen, Unicode format
  {...source,provider:'feed\u034fA'}, // combining grapheme joiner
  {...source,instrument:'NSX\u115fUSD'}, // Hangul filler
 ]){
  assert.throws(()=>studyHourlyFvgMidpoint(bars,invalid),/Invalid source/,
   'noncanonical or invisible source labels must fail closed');
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,invalid,cutoff),
   /Invalid source/,'as-of replay enforces identical identity checks');
 }
 assert.deepEqual(studyHourlyFvgMidpoint(bars,source),baseline);
 assert.ok(valid.observations.every(o=>o.eligibleForLiveTrading===false),
  'no observation grants live trading permission');
});
test('v61 source labels reject lone surrogates and Unicode noncharacters in both replay paths',()=>{
 const bars=fixture(),cutoff=BASE+37*H;
 // These strings can display as the same replacement glyph while encoding
 // different source identities. Neither may be silently exported as verified.
 const invalidCharacters=['\uD800','\uDC00','\uFDD0','\uFFFE','\u{1FFFF}','\u{10FFFF}'];
 for(const character of invalidCharacters){
  for(const field of ['provider','instrument'] as const){
   const invalid={...source,[field]:'feed'+character+'A'};
   assert.throws(()=>studyHourlyFvgMidpoint(bars,invalid),/Invalid source/);
   assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,invalid,cutoff),/Invalid source/);
  }
 }
 // A valid supplementary-plane Unicode scalar is not an unpaired surrogate.
 const valid={...source,provider:'Market 📈',instrument:'Gold 📊'};
 assert.deepEqual(studyHourlyFvgMidpoint(bars,valid).source,valid);
 assert.deepEqual(studyHourlyFvgMidpointAsOf(bars,valid,cutoff).source,valid);
 assert.equal(studyHourlyFvgMidpoint(bars,valid).version,
  'hourly-fvg-first-midpoint-touch-v92');
});
test('v63 source labels reject Unicode space lookalikes without banning ASCII spaces',()=>{
 const bars=fixture(),cutoff=BASE+37*H;
 // Nonbreaking, figure, narrow, en and ideographic spaces can make different
 // source identities render almost identically to an ordinary ASCII space.
 for(const character of ['\u00a0','\u2002','\u2007','\u202f','\u3000']){
  for(const field of ['provider','instrument'] as const){
   const invalid={...source,[field]:'Research'+character+'Feed'};
   assert.throws(()=>studyHourlyFvgMidpoint(bars,invalid),/Invalid source/);
   assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,invalid,cutoff),/Invalid source/);
  }
 }
 const legitimate={...source,provider:'Research Feed A',instrument:'Gold Spot BID'};
 assert.deepEqual(studyHourlyFvgMidpoint(bars,legitimate).source,legitimate);
 assert.deepEqual(studyHourlyFvgMidpointAsOf(bars,legitimate,cutoff).source,legitimate);
 assert.equal(studyHourlyFvgMidpoint(bars,legitimate).version,
  'hourly-fvg-first-midpoint-touch-v92');
});
test('first bullish midpoint touch has a hypothetical blind limit and later next-open rejection markout',()=>{
 const x=target(fixture());
 assert.equal(x.direction,'BULLISH');
 assert.equal(x.gapLow,100);
 assert.equal(x.gapHigh,104);
 assert.equal(x.midpoint,102);
 assert.equal(x.formationClosedAt,BASE+33*H);
 assert.equal(x.firstTouchClosedAt,BASE+34*H);
 assert.equal(x.gates.midpointTouch,'PASS');
 assert.equal(x.gates.wickRejection,'PASS');
 assert.equal(x.gates.verifiedVolume,'PASS');
 assert.equal(x.gates.strictCandidate,'PASS');
 assert.equal(x.gates.markout,'PASS');
 assert.equal(x.blindMidpointTouch?.entryPrice,102);
 assert.equal(x.confirmedNextOpen?.entryPrice,105.5);
 assert.equal(x.confirmedNextOpen?.entryObservedAt,BASE+35*H);
 assert.equal(x.confirmedNextOpen?.hypotheticalEntryAt,BASE+34*H);
 assert.equal(x.blindMidpointTouch?.exitObservedAt,BASE+37*H);
 assert.equal(x.confirmedNextOpen?.exitObservedAt,BASE+37*H);
 assert.ok((x.blindMidpointTouch?.grossBps??0)>(x.confirmedNextOpen?.grossBps??0));
 assert.equal(x.eligibleForLiveTrading,false);
});
test('hypothetical next-open entry time is not mislabelled as observed BID evidence',()=>{
 for(const bearish of [false,true]){
  const bars=bearish?fixture().map(b=>({...b,open:220-b.open,
   high:220-b.low,low:220-b.high,close:220-b.close})):fixture();
  const x=target(bars);
  assert.equal(x.gates.wickRejection,'PASS');
  assert.equal(x.blindMidpointTouch?.hypotheticalEntryAt,null,
   'hourly OHLC has no observed intrabar midpoint execution timestamp');
  assert.equal(x.blindMidpointTouch?.entryObservedAt,BASE+34*H);
  assert.equal(x.confirmedNextOpen?.hypotheticalEntryAt,BASE+34*H,
   'the hypothetical entry is at the following hourly opening');
  assert.equal(x.confirmedNextOpen?.entryObservedAt,BASE+35*H,
   'historical next-open BID is evidenced only when its full bar closes');
  assert.equal(x.confirmedNextOpen?.entryPrice,bars[34].open);
  assert.equal(x.confirmedNextOpen?.exitObservedAt,BASE+37*H);
  assert.equal(x.eligibleForLiveTrading,false);
 }
});
test('blind midpoint observation is timestamped at touch close, never at bar open',()=>{
 for(const bars of [fixture(),fixture().map(b=>({...b,
  open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close}))]){
  const x=target(bars);
  assert.equal(x.gates.midpointTouch,'PASS');
  assert.equal(x.blindMidpointTouch?.entryObservedAt,x.firstTouchClosedAt);
  assert.equal(x.blindMidpointTouch?.entryObservedAt,BASE+34*H);
  assert.notEqual(x.blindMidpointTouch?.entryObservedAt,bars[33].time,
   'a touch cannot be inferred from a completed hourly range at its opening');
 }
 // The same causal timestamp applies to a failed rejection: the blind
 // comparator must not borrow information from a later attractive touch.
 const failed=fixture();
 failed[33]=candle(33,105,106,101,102.5,200);
 const x=target(failed);
 assert.equal(x.gates.wickRejection,'FAIL');
 assert.equal(x.blindMidpointTouch?.entryObservedAt,x.firstTouchClosedAt);
});

test('a failed first touch cannot be replaced by a prettier later rejection',()=>{
 const bars=fixture();
 bars[33]=candle(33,105,106,101,102.5,200); // 1st touch, closes lower
 bars[34]=candle(34,105,106,101,105.5,200); // tempting later PASS
 const x=target(bars);
 assert.equal(x.gates.wickRejection,'FAIL');
 assert.equal(x.gates.strictCandidate,'FAIL');
 assert.equal(x.firstTouchClosedAt,BASE+34*H);
 assert.equal(x.confirmedNextOpen,null);
 assert.ok(x.blindMidpointTouch);
});
test('a touch bar is never used as the rejection entry and later prices do not rewrite the signal',()=>{
 const bars=fixture();
 const first=target(bars);
 bars[37]=candle(37,1,2,.5,1);
 bars[38]=candle(38,1,2,.5,1);
 const second=target(bars);
 assert.equal(first.firstTouchClosedAt,second.firstTouchClosedAt);
 assert.equal(first.gates.wickRejection,second.gates.wickRejection);
 assert.equal(first.confirmedNextOpen?.entryPrice,second.confirmedNextOpen?.entryPrice);
 assert.equal(first.confirmedNextOpen?.grossBps,second.confirmedNextOpen?.grossBps);
});
test('unverified, placeholder or insufficient 20-bar volume cannot pass',()=>{
 const bars=fixture();
 const unknown=target(bars,{...source,volumeType:'unverified',volumeVerified:false});
 assert.equal(unknown.gates.verifiedVolume,'INSUFFICIENT_DATA');
 assert.equal(unknown.gates.strictCandidate,'INSUFFICIENT_DATA');
 const zero=fixture();zero[31].volume=0;
 assert.equal(target(zero).gates.verifiedVolume,'INSUFFICIENT_DATA');
 const low=fixture();low[33].volume=120;
 assert.equal(target(low).gates.verifiedVolume,'FAIL');
 assert.equal(target(low).gates.strictCandidate,'FAIL');
});
test('verified prior-20 volume uses a scale-safe strict threshold for extreme finite values',()=>{
 // The naive sum of twenty 1e308 values is Infinity, hiding a valid PASS.
 // Dividing each 5e-324 value by 20 underflows and also loses the comparison.
 for(const {baseline,touch,expected} of [
  {baseline:1e308,touch:1.7e308,expected:'PASS'},
  {baseline:1e308,touch:1.4e308,expected:'FAIL'},
  {baseline:5e-324,touch:1e-323,expected:'PASS'},
  {baseline:5e-324,touch:5e-324,expected:'FAIL'},
 ] as const){
  const bars=fixture();
  for(let i=13;i<=32;i++)bars[i].volume=baseline;
  bars[33].volume=touch;
  const x=target(bars);
  assert.equal(x.gates.midpointTouch,'PASS');
  assert.equal(x.gates.wickRejection,'PASS');
  assert.equal(x.gates.verifiedVolume,expected);
  assert.equal(x.gates.strictCandidate,expected);
 }
});

test('50% wick threshold uses exact observed prices rather than rounded wick/range',()=>{
 const bars=fixture();
 // 200 - 1e-200 rounds to 200, and 400 - 1e-200 rounds to 400.
 // Their displayed quotient is 0.5, but the exact source-float wick
 // fraction is strictly BELOW one half. Do not admit a false candidate.
 bars[33]=candle(33,200,400,1e-200,250,200);
 const rounded=(200-1e-200)/(400-1e-200);
 assert.equal(rounded,0.5);
 const below=target(bars);
 assert.equal(below.gates.midpointTouch,'PASS');
 assert.equal(below.rejectionWickFraction,0.5);
 assert.equal(below.gates.wickRejection,'FAIL');
 assert.equal(below.gates.strictCandidate,'FAIL');
 // A genuine exact 50% lower wick remains eligible on the same source.
 bars[33]=candle(33,250,400,100,300,200);
 const equal=target(bars);
 assert.equal(equal.gates.wickRejection,'PASS');
 assert.equal(equal.gates.strictCandidate,'PASS');
});

test('strict prior-20 volume threshold does not round a true exceedance into equality',()=>{
 // 1.5000000000000001e100 is strictly above 1.5 times the exact
 // IEEE-754 value 1e100, but the old ratio rounds to precisely 1.5.
 const bars=fixture();
 for(let i=13;i<=32;i++)bars[i].volume=1e100;
 bars[33].volume=1.5000000000000001e100;
 assert.equal(bars[33].volume!/bars[32].volume!,1.5);
 assert.equal(target(bars).gates.verifiedVolume,'PASS');
 assert.equal(target(bars).gates.strictCandidate,'PASS');
 bars[33].volume=150;
 for(let i=13;i<=32;i++)bars[i].volume=100;
 assert.equal(target(bars).gates.verifiedVolume,'FAIL',
  'an exactly equal 1.5x threshold must not pass');
});
test('complete no-touch horizon is a known candidate failure, while truncated horizon stays unknown',()=>{
 const bars=fixture();
 for(let i=33;i<45;i++){
  if(i>=bars.length)bars.push(candle(i,105,106,104,105));
  else bars[i]=candle(i,105,106,104,105);
 }
 for(const bearish of [false,true]){
  const series=bearish?bars.map(b=>({...b,open:220-b.open,
   high:220-b.low,low:220-b.high,close:220-b.close})):bars;
  const complete=target(series);
  assert.equal(complete.gates.midpointTouch,'FAIL');
  assert.equal(complete.gates.strictCandidate,'FAIL',
   'observed no-touch must count as a known rejection, not missingness');
  assert.equal(complete.firstTouchClosedAt,null);
  assert.equal(complete.gates.markout,'FAIL',
   'fully observed no-touch has no possible comparator entry');
  assert.equal(complete.blindMidpointTouch,null);
  assert.equal(complete.confirmedNextOpen,null);
  const cohort=studyHourlyFvgMidpoint(series,source).cohort;
  assert.ok(cohort.markout.FAIL>=1,'known no-touch belongs in the markout attrition census');
  const truncated=target(series.slice(0,44));
  assert.equal(truncated.gates.midpointTouch,'INSUFFICIENT_DATA');
  assert.equal(truncated.gates.strictCandidate,'INSUFFICIENT_DATA');
  assert.equal(truncated.gates.markout,'INSUFFICIENT_DATA',
   'right-censored waiting windows cannot be marked as known no-entry');
 }
});
test('missing 1H bar in pre-touch path is unknown, not a false negative or later cherry-picked touch',()=>{
 const bars=fixture().filter(b=>b.time!==BASE+33*H);
 const x=target(bars);
 assert.equal(x.gates.midpointTouch,'INSUFFICIENT_DATA');
 assert.equal(x.firstTouchClosedAt,null);
 assert.equal(x.blindMidpointTouch,null);
});
test('missing future markout does not fabricate a profit or a losing return',()=>{
 const bars=fixture().slice(0,35);
 const x=target(bars);
 assert.equal(x.gates.wickRejection,'PASS');
 assert.equal(x.gates.markout,'INSUFFICIENT_DATA');
 assert.equal(x.blindMidpointTouch,null);
 assert.equal(x.confirmedNextOpen,null);
});
test('an opening gap through midpoint is not a verified blind limit fill',()=>{
 const bars=fixture();
 bars[33]=candle(33,101,106,100,105.5,200);
 const x=target(bars);
 assert.equal(x.gates.midpointTouch,'INSUFFICIENT_DATA');
 assert.equal(x.firstTouchClosedAt,BASE+34*H); // physical touch, not executable fill
 assert.equal(x.blindMidpointTouch,null);
 assert.equal(x.confirmedNextOpen,null);
});
test('opening gap entirely below bullish midpoint blocks a later attractive return',()=>{
 const bars=fixture();
 bars[33]=candle(33,100,101,99,100,200); // jumped below 102 without touching
 bars[34]=candle(34,105,106,101,105.5,200); // later tempting wick rejection
 const x=target(bars);
 assert.equal(x.gates.midpointTouch,'INSUFFICIENT_DATA');
 assert.equal(x.firstTouchClosedAt,null); // no observed midpoint touch
 assert.equal(x.gates.strictCandidate,'INSUFFICIENT_DATA');
 assert.equal(x.blindMidpointTouch,null);
 assert.equal(x.confirmedNextOpen,null);
});
test('gap-through after an initially untouched hour still freezes the candidate',()=>{
 const bars=fixture();
 bars[33]=candle(33,105,106,104,105,200); // no touch, correct side
 bars[34]=candle(34,100,101,99,100,200); // crossed midpoint between bars
 bars[35]=candle(35,105,106,101,105.5,200); // later tempting touch
 const x=target(bars);
 assert.equal(x.gates.midpointTouch,'INSUFFICIENT_DATA');
 assert.equal(x.firstTouchClosedAt,null);
 assert.equal(x.blindMidpointTouch,null);
});
test('bearish opening gap entirely above midpoint blocks a later return',()=>{
 const bars=fixture();
 bars[33]=candle(33,100,101,99,100,200);
 bars[34]=candle(34,105,106,101,105.5,200);
 const bearish=bars.map(b=>({...b,open:220-b.open,high:220-b.low,
  low:220-b.high,close:220-b.close}));
 const x=target(bearish);
 assert.equal(x.direction,'BEARISH');
 assert.equal(x.gates.midpointTouch,'INSUFFICIENT_DATA');
 assert.equal(x.firstTouchClosedAt,null);
 assert.equal(x.blindMidpointTouch,null);
 assert.equal(x.confirmedNextOpen,null);
});
test('sparse and changing cost arrays cannot pass validation then rewrite net markouts',()=>{
 const sparse=new Array<number>(3);
 sparse[0]=0;sparse[2]=15;
 assert.throws(()=>studyHourlyFvgMidpoint(fixture(),source,{
  hypotheticalRoundTripCostsBps:sparse,
 }),/Invalid source/,'missing cost cells must not serialize as null scenarios');
 let reads=0;
 const changing=[0,5,15];
 Object.defineProperty(changing,1,{enumerable:true,configurable:true,
  get(){reads++;return reads===1?5:Number.NaN;}});
 const report=studyHourlyFvgMidpoint(fixture(),source,{
  hypotheticalRoundTripCostsBps:changing,
 });
 assert.equal(reads,1,'each supplied cost must be captured exactly once');
 assert.deepEqual(report.config.hypotheticalRoundTripCostsBps,[0,5,15]);
 const observation=report.observations.find(o=>o.formationClosedAt===BASE+33*H);
 assert.ok(observation?.blindMidpointTouch&&observation.confirmedNextOpen);
 for(const result of [observation.blindMidpointTouch,observation.confirmedNextOpen]){
  assert.deepEqual(result.netBpsByCost.map(x=>x.costBps),[0,5,15]);
  assert.ok(result.netBpsByCost.every(x=>Number.isFinite(x.netBps)));
 }
});
test('hypothetical costs are deducted identically and cannot be confused with broker quotes',()=>{
 const x=target(fixture());
 for(const result of [x.blindMidpointTouch,x.confirmedNextOpen]){
  assert.ok(result);
  assert.deepEqual(result.netBpsByCost.map(r=>r.costBps),[0,5,15]);
  assert.ok(Math.abs(result.netBpsByCost[2].netBps-(result.grossBps-15))<1e-10);
 }
});
test('bearish midpoint rejection uses upper wick and directional next-open markout',()=>{
 const bars=fixture().map(b=>({...b,open:220-b.open,high:220-b.low,
  low:220-b.high,close:220-b.close}));
 const x=target(bars);
 assert.equal(x.direction,'BEARISH');
 assert.equal(x.gates.wickRejection,'PASS');
 assert.equal(x.gates.verifiedVolume,'PASS');
 assert.ok((x.confirmedNextOpen?.grossBps??0)>0);
});

test('large finite FVG endpoints yield a finite interior midpoint',()=>{
 const bars=fixture();
 bars[30]=candle(30,1.2e308,1.3e308,1.1e308,1.2e308);
 bars[31]=candle(31,1.3e308,1.4e308,1.2e308,1.3e308);
 bars[32]=candle(32,1.6e308,1.7e308,1.5e308,1.6e308);
 const x=target(bars);
 assert.equal(x.direction,'BULLISH');
 assert.ok(Number.isFinite(x.midpoint));
 assert.ok(x.midpoint>x.gapLow&&x.midpoint<x.gapHigh);
});

test('subnormal midpoint uses a single rounded half-gap and does not fabricate a gap-through',()=>{
 // With separately halved endpoints, rounding moves the midpoint one ULP
 // upward. The first touch then looks like an opening gap-through instead.
 const low=3.9866600654518847e-308,high=3.986660065451928e-308;
 const expected=low+(high-low)/2;
 assert.ok(expected>low&&expected<high);
 assert.notEqual(low/2+high/2,expected);
 const bars=[
  candle(0,low,low,low,low),
  candle(1,low,low,low,low),
  candle(2,high,high,high,high),
  candle(3,expected,expected,expected,expected),
 ];
 const x=studyHourlyFvgMidpoint(bars,source,{maxTouchWaitBars:1})
  .observations.find(o=>o.formationClosedAt===BASE+3*H);
 assert.ok(x);
 assert.equal(x.midpoint,expected);
 assert.equal(x.firstTouchClosedAt,BASE+4*H);
 assert.equal(x.gates.midpointTouch,'PASS');
 assert.equal(x.gates.wickRejection,'FAIL');
 assert.equal(x.gates.markout,'INSUFFICIENT_DATA');
 assert.equal(x.eligibleForLiveTrading,false);
});

test('unrepresentable midpoint rejects the window instead of rounding to a boundary',()=>{
 const bars=fixture();
 bars[30]=candle(30,1,1.0000000000000002,0.9,1);
 bars[31]=candle(31,1.0000000000000002,1.0000000000000004,1,1.0000000000000002);
 bars[32]=candle(32,1.0000000000000007,1.0000000000000009,
  1.0000000000000004,1.0000000000000007);
 assert.throws(()=>studyHourlyFvgMidpoint(bars,source),/midpoint cannot be represented/);
});

test('nonfinite gross markouts are insufficient in bullish and bearish studies',()=>{
 for(const bearish of [false,true]){
  const bars=bearish?fixture().map(b=>({...b,open:220-b.open,high:220-b.low,
   low:220-b.high,close:220-b.close})):fixture();
  bars[36]=candle(36,1e308,1.1e308,9e307,1e308);
  const x=target(bars);
  assert.equal(x.gates.midpointTouch,'PASS');
  assert.equal(x.gates.wickRejection,'PASS');
  assert.equal(x.gates.markout,'INSUFFICIENT_DATA');
  assert.equal(x.blindMidpointTouch,null);
  assert.equal(x.confirmedNextOpen,null);
 }
});

test('an overflowing next-open comparator suppresses both matched markouts',()=>{
 const bars=fixture();
 // Blind midpoint return stays finite; next-open return cannot be
 // represented in basis points and must not be cherry-picked away.
 bars[34]=candle(34,1e-308,107,1e-308,106);
 const x=target(bars);
 assert.equal(x.gates.wickRejection,'PASS');
 assert.equal(x.gates.markout,'INSUFFICIENT_DATA');
 assert.equal(x.markoutCensorReason,'UNREPRESENTABLE_RETURN');
 assert.equal(x.blindMidpointTouch,null);
 assert.equal(x.confirmedNextOpen,null);
});
test('completed hourly timestamps are safe and numeric rule changes have a new version',()=>{
 const report=studyHourlyFvgMidpoint(fixture(),source);
 assert.equal(report.version,'hourly-fvg-first-midpoint-touch-v92');
 const lastSafeAlignedOpen=Math.floor(Number.MAX_SAFE_INTEGER/H)*H;
 assert.equal(Number.isSafeInteger(lastSafeAlignedOpen),true);
 assert.equal(Number.isSafeInteger(lastSafeAlignedOpen+H),false);
 // Previously this open passed validation but its close could not be
 // represented as an exact second for formation/touch/markout evidence.
 assert.throws(()=>studyHourlyFvgMidpoint([
  {...candle(0),time:lastSafeAlignedOpen},
 ],source),/Invalid, incomplete/);
 assert.equal(studyHourlyFvgMidpoint([
  {...candle(0),time:lastSafeAlignedOpen-H},
 ],source).observations.length,0);
});

test('invalid source, incomplete candles and unsafe settings fail closed',()=>{
 assert.throws(()=>studyHourlyFvgMidpoint(fixture(),{...source,archiveSha256:'wrong'}),/Invalid source/);
 const bad=fixture();bad[20].observed_minutes=59;
 assert.throws(()=>studyHourlyFvgMidpoint(bad,source),/Invalid, incomplete/);
 const badOrder=fixture();badOrder[22].time=badOrder[21].time;
 assert.throws(()=>studyHourlyFvgMidpoint(badOrder,source),/Invalid, incomplete/);
 assert.throws(()=>studyHourlyFvgMidpoint(fixture(),source,{maxTouchWaitBars:0}),/Invalid source/);
 assert.throws(()=>studyHourlyFvgMidpoint(fixture(),source,{hypotheticalRoundTripCostsBps:[-5]}),/Invalid source/);
});

test('inherited array slots never substitute for observed archive rows or declared costs',()=>{
 const stable=studyHourlyFvgMidpoint(fixture(),source);
 const bars=fixture();
 const candlePrototype=Object.create(Array.prototype);
 Object.defineProperty(candlePrototype,'0',{value:bars[0],configurable:true});
 assert.equal(Reflect.deleteProperty(bars,'0'),true);
 Object.setPrototypeOf(bars,candlePrototype);
 assert.throws(()=>studyHourlyFvgMidpoint(bars,source),/own-index candle evidence/);
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,BASE+33*H),
  /own-index candle evidence/);
 const future=fixture();
 const futurePrototype=Object.create(Array.prototype);
 Object.defineProperty(futurePrototype,'39',{value:future[39],configurable:true});
 assert.equal(Reflect.deleteProperty(future,'39'),true);
 Object.setPrototypeOf(future,futurePrototype);
 assert.throws(()=>studyHourlyFvgMidpointAsOf(future,source,BASE+33*H),
  /own-index candle evidence/,
  'future timestamp audit must reject an inherited row without reading future OHLC');
 const costs=[0,5,15];
 const costPrototype=Object.create(Array.prototype);
 Object.defineProperty(costPrototype,'1',{value:5,configurable:true});
 assert.equal(Reflect.deleteProperty(costs,'1'),true);
 Object.setPrototypeOf(costs,costPrototype);
 assert.throws(()=>studyHourlyFvgMidpoint(fixture(),source,{
  hypotheticalRoundTripCostsBps:costs,
 }),/Invalid source/);
 assert.deepEqual(studyHourlyFvgMidpoint(fixture(),source),stable);
});

// UTC calendar gaps may be genuine closures, not automatically missing feeds.
test('coverage counts unobserved hours without leaking future gaps into as-of reports',()=>{
 const bars=fixture().filter(b=>b.time!==BASE+20*H&&b.time!==BASE+21*H);
 const full=studyHourlyFvgMidpoint(bars,source);
 assert.deepEqual(full.coverage,{
  firstBarOpenAt:BASE,lastBarClosedAt:BASE+40*H,
  observedBars:38,unobservedHourSlots:2,gapIntervals:1,
  singleMissingHourGapIntervals:0,multiMissingHourGapIntervals:1,longestUnobservedHourRun:2,
   observedThreeBarWindows:36,completeThreeBarWindows:34,
   skippedThreeBarWindowsWithGaps:2,
   skippedThreeBarWindowsWithOneGapEdge:2,
   skippedThreeBarWindowsWithTwoGapEdges:0,
 });
 const before=studyHourlyFvgMidpointAsOf(bars,source,BASE+20*H);
 assert.deepEqual(before.coverage,{
  firstBarOpenAt:BASE,lastBarClosedAt:BASE+20*H,
  observedBars:20,unobservedHourSlots:0,gapIntervals:0,
  singleMissingHourGapIntervals:0,multiMissingHourGapIntervals:0,longestUnobservedHourRun:0,
   observedThreeBarWindows:18,completeThreeBarWindows:18,
   skippedThreeBarWindowsWithGaps:0,
   skippedThreeBarWindowsWithOneGapEdge:0,
   skippedThreeBarWindowsWithTwoGapEdges:0,
 });
 const after=studyHourlyFvgMidpointAsOf(bars,source,BASE+24*H);
 assert.deepEqual(after.coverage,{
  firstBarOpenAt:BASE,lastBarClosedAt:BASE+24*H,
  observedBars:22,unobservedHourSlots:2,gapIntervals:1,
  singleMissingHourGapIntervals:0,multiMissingHourGapIntervals:1,longestUnobservedHourRun:2,
   observedThreeBarWindows:20,completeThreeBarWindows:18,
   skippedThreeBarWindowsWithGaps:2,
   skippedThreeBarWindowsWithOneGapEdge:2,
   skippedThreeBarWindowsWithTwoGapEdges:0,
 });
 const empty=studyHourlyFvgMidpointAsOf(bars,source,H);
 assert.deepEqual(empty.coverage,{
  firstBarOpenAt:null,lastBarClosedAt:null,
  observedBars:0,unobservedHourSlots:0,gapIntervals:0,
  singleMissingHourGapIntervals:0,multiMissingHourGapIntervals:0,longestUnobservedHourRun:0,
   observedThreeBarWindows:0,completeThreeBarWindows:0,
   skippedThreeBarWindowsWithGaps:0,
   skippedThreeBarWindowsWithOneGapEdge:0,
   skippedThreeBarWindowsWithTwoGapEdges:0,
 });
 assert.equal(full.coverage.observedBars+full.coverage.unobservedHourSlots,40);
});


function onePairedFvgFixture():Bar[]{
 const bars=Array.from({length:27},(_,i)=>candle(i));
 bars[20]=candle(20,99,100,98,99);
 bars[21]=candle(21,100,102,99,101);
 bars[22]=candle(22,105,106,104,105);
 bars[23]=candle(23,105,106,101,105.5,200);
 bars[24]=candle(24,105.5,107,105,106);
 bars[25]=candle(25,106,108,105,107);
 bars[26]=candle(26,107,111,106,110);
 return bars;
}
const sumNetCells=(x:{bothPositive:number;blindOnlyPositive:number;
 confirmedOnlyPositive:number;neitherPositive:number})=>
 x.bothPositive+x.blindOnlyPositive+x.confirmedOnlyPositive+x.neitherPositive;

test('paired hypothetical net-sign census preserves every cost and as-of exit boundary',()=>{
 for(const bearish of [false,true]){
  const base=onePairedFvgFixture();
  const bars=bearish?base.map(b=>({...b,open:220-b.open,
   high:220-b.low,low:220-b.high,close:220-b.close})):base;
  const settings={hypotheticalRoundTripCostsBps:[0,500,900]};
  const study=studyHourlyFvgMidpoint(bars,source,settings);
  assert.equal(study.cohort.pairedMarkouts,1);
  assert.equal(study.cohort.strictPairedMarkouts,1);
  const scenarios=study.cohort.pairedNetSignByCost;
  assert.deepEqual(scenarios.map(x=>x.costBps),[0,500,900]);
  assert.deepEqual(scenarios.map(x=>x.scenarioIndex),[0,1,2]);
  assert.equal(scenarios[0].all.bothPositive,1);
  assert.equal(scenarios[1].all.blindOnlyPositive,1);
  assert.equal(scenarios[2].all.neitherPositive,1);
  for(const scenario of scenarios){
   assert.equal(sumNetCells(scenario.all),study.cohort.pairedMarkouts);
   assert.equal(sumNetCells(scenario.strict),study.cohort.strictPairedMarkouts);
   assert.deepEqual(scenario.strict,scenario.all);
  }
  const beforeExit=studyHourlyFvgMidpointAsOf(bars,source,BASE+26*H,settings);
  assert.equal(beforeExit.cohort.pairedMarkouts,0);
  assert.ok(beforeExit.cohort.pairedNetSignByCost.every(x=>
   sumNetCells(x.all)===0&&sumNetCells(x.strict)===0));
  const afterExit=studyHourlyFvgMidpointAsOf(bars,source,BASE+27*H,settings);
  assert.deepEqual(afterExit.cohort.pairedNetSignByCost,scenarios);
  const unverified=studyHourlyFvgMidpoint(bars,{...source,volumeVerified:false},settings);
  assert.equal(unverified.cohort.pairedMarkouts,1);
  assert.equal(unverified.cohort.strictPairedMarkouts,0);
  assert.ok(unverified.cohort.pairedNetSignByCost.every(x=>
   sumNetCells(x.all)===1&&sumNetCells(x.strict)===0));
 }
});

test('favorable next-open hypothetical entry is counted without blind-only bias',()=>{
 for(const bearish of [false,true]){
  const base=onePairedFvgFixture();
  base[24]=candle(24,101,107,100,106);
  base[26]=candle(26,107,111,102,103);
  const bars=bearish?base.map(b=>({...b,open:220-b.open,
   high:220-b.low,low:220-b.high,close:220-b.close})):base;
  const study=studyHourlyFvgMidpoint(bars,source,{
   hypotheticalRoundTripCostsBps:[120],
  });
  assert.equal(study.cohort.pairedMarkouts,1);
  assert.equal(study.cohort.pairedNetSignByCost[0].all.confirmedOnlyPositive,1);
  assert.equal(study.cohort.pairedNetSignByCost[0].strict.confirmedOnlyPositive,1);
 }
});


test('matched net-sign costs partition strict pass, known fail and unknown evidence without as-of leakage',()=>{
 for(const bearish of [false,true]){
  const baseline=onePairedFvgFixture();
  const flipped=(rows:Bar[])=>bearish?rows.map(b=>({...b,
   open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close})):rows;
  const settings={hypotheticalRoundTripCostsBps:[0,500,900]};
  const passed=studyHourlyFvgMidpoint(flipped(baseline),source,settings);
  const failed=baseline.map(b=>({...b}));
  failed[23]={...failed[23],volume:100}; // Exactly prior-20 mean: known FAIL.
  const knownFail=studyHourlyFvgMidpoint(flipped(failed),source,settings);
  const unknown=studyHourlyFvgMidpoint(flipped(baseline),{
   ...source,volumeType:'none',volumeVerified:false,
  },settings);
  const groups=[
   [passed,'strict'],[knownFail,'strictFail'],[unknown,'strictUnknown'],
  ] as const;
  for(const [study,expected] of groups){
   assert.equal(study.cohort.pairedMarkouts,1);
   assert.equal(study.cohort.pairedByStrictCandidate.PASS,
    expected==='strict'?1:0);
   assert.equal(study.cohort.pairedByStrictCandidate.FAIL,
    expected==='strictFail'?1:0);
   assert.equal(study.cohort.pairedByStrictCandidate.INSUFFICIENT_DATA,
    expected==='strictUnknown'?1:0);
   for(const scenario of study.cohort.pairedNetSignByCost){
    assert.equal(sumNetCells(scenario.all),1);
    assert.deepEqual(scenario[expected],scenario.all);
    for(const key of ['strict','strictFail','strictUnknown'] as const){
     if(key!==expected)assert.equal(sumNetCells(scenario[key]),0);
    }
    for(const cell of ['bothPositive','blindOnlyPositive',
     'confirmedOnlyPositive','neitherPositive'] as const){
     assert.equal(scenario.all[cell],
      scenario.strict[cell]+scenario.strictFail[cell]+scenario.strictUnknown[cell]);
    }
   }
   const asOf=studyHourlyFvgMidpointAsOf(flipped(expected==='strictFail'?failed:baseline),
    expected==='strictUnknown'?{...source,volumeType:'none',volumeVerified:false}:source,
    BASE+26*H,settings);
   assert.equal(asOf.cohort.pairedMarkouts,0);
   for(const scenario of asOf.cohort.pairedNetSignByCost){
    assert.equal(sumNetCells(scenario.all),0);
    assert.equal(sumNetCells(scenario.strict),0);
    assert.equal(sumNetCells(scenario.strictFail),0);
    assert.equal(sumNetCells(scenario.strictUnknown),0);
   }
  }
 }
});

test('matured paired gross ordering preserves adverse, favorable and equal next-open entries',()=>{
 const sum=(cells:{confirmedHigher:number;blindHigher:number;equal:number})=>
  cells.confirmedHigher+cells.blindHigher+cells.equal;
 for(const bearish of [false,true]){
  const flip=(bars:Bar[])=>bearish?bars.map(b=>({...b,
   open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close})):bars;
  for(const [nextOpen,expected] of [
   [105.5,'blindHigher'],[101,'confirmedHigher'],[102,'equal'],
  ] as const){
   const base=onePairedFvgFixture();
   base[24]=candle(24,nextOpen,107,100,106);
   const bars=flip(base);
   const report=studyHourlyFvgMidpoint(bars,source,{
    hypotheticalRoundTripCostsBps:[0,500,900],
   });
   const ordering=report.cohort.pairedGrossOrdering;
   assert.equal(report.cohort.pairedMarkouts,1);
   assert.equal(sum(ordering.all),1);
   assert.equal(ordering.all[expected],1);
   assert.deepEqual(ordering.strict,ordering.all);
   assert.equal(sum(ordering.strictFail),0);
   assert.equal(sum(ordering.strictUnknown),0);
   // An observed touch is not a completed fixed-exit comparison.
   const before=studyHourlyFvgMidpointAsOf(bars,source,BASE+26*H);
   assert.equal(before.cohort.pairedMarkouts,0);
   assert.equal(sum(before.cohort.pairedGrossOrdering.all),0);
   const matured=studyHourlyFvgMidpointAsOf(bars,source,BASE+27*H);
   assert.deepEqual(matured.cohort.pairedGrossOrdering,ordering);
   // A known failed volume gate and an unauthenticated volume declaration
   // must remain distinct partitions, without altering the matched basis.
   const failed=base.map(b=>({...b}));
   failed[23].volume=100;
   const failReport=studyHourlyFvgMidpoint(flip(failed),source);
   assert.deepEqual(failReport.cohort.pairedGrossOrdering.strictFail,ordering.all);
   assert.equal(sum(failReport.cohort.pairedGrossOrdering.strict),0);
   const unknown=studyHourlyFvgMidpoint(bars,{
    ...source,volumeType:'unverified',volumeVerified:false,
   });
   assert.deepEqual(unknown.cohort.pairedGrossOrdering.strictUnknown,ordering.all);
   assert.equal(sum(unknown.cohort.pairedGrossOrdering.strict),0);
  }
 }
});

test('paired gross ordering does not turn one-ULP entry differences into rounded-bps ties',()=>{
 // Distinct entry prices can produce identical rounded IEEE-754 gross bps.
 for(const bearish of [false,true]){
  const base=onePairedFvgFixture();
  const bars=bearish?base.map(b=>({...b,open:220-b.open,
   high:220-b.low,low:220-b.high,close:220-b.close})):base;
  const midpoint=bearish?118:102;
  const nextOpen=bearish?118.00000000000001:102.00000000000001;
  const exit=bearish?25.80036566242495:9886164.165972022;
  bars[24]={...bars[24],open:nextOpen,
   high:bearish?119:107,low:bearish?113:100};
  bars[26]={...bars[26],high:bearish?114:exit,
   low:bearish?25:106,close:exit};
  const report=studyHourlyFvgMidpoint(bars,source);
  const matched=report.observations.find(o=>o.midpoint===midpoint&&
   o.blindMidpointTouch!==null&&o.confirmedNextOpen!==null);
  assert.ok(matched,'expected mature first-touch matched pair');
  assert.equal(matched.blindMidpointTouch!.grossBps,
   matched.confirmedNextOpen!.grossBps,
   'fixture must exercise the actual rounded-bps tie');
  const expected=bearish?'confirmedHigher':'blindHigher';
  assert.equal(report.cohort.pairedMarkouts,1);
  assert.equal(report.cohort.pairedGrossOrdering.all[expected],1);
  assert.equal(report.cohort.pairedGrossOrdering.all.equal,0);
  const before=studyHourlyFvgMidpointAsOf(bars,source,BASE+26*H);
  assert.equal(before.cohort.pairedMarkouts,0);
  assert.equal(before.cohort.pairedGrossOrdering.all[expected],0);
  const mature=studyHourlyFvgMidpointAsOf(bars,source,BASE+27*H);
  assert.deepEqual(mature.cohort.pairedGrossOrdering,
   report.cohort.pairedGrossOrdering);
 }
});


test('matched cost-sign census uses exact price-vs-cost threshold despite rounded zero bps',()=>{
 // 0.3 bps is not exactly representable as a binary float. Both the
 // bullish and mirrored bearish prices produce a rounded grossBps of 0.3
 // and a displayed netBps of zero, despite a strictly positive exact
 // directional move after the supplied float cost.
 const entry=3.0517578125,exit=3.051849365234375;
 const base=Array.from({length:27},(_,i)=>candle(i,3,3.5,2.5,3));
 base[20]=candle(20,2.8,2.9267578125,2.7,2.8);
 base[21]=candle(21,2.9,3,2.8,2.95);
 base[22]=candle(22,3.25,3.4,3.1767578125,3.25);
 base[23]=candle(23,3.3,3.4,3,3.32,200);
 base[24]=candle(24,entry,3.5,3,3.3);
 base[25]=candle(25,3.3,3.6,3,3.4);
 base[26]=candle(26,3.4,3.5,3,exit);
 const settings={hypotheticalRoundTripCostsBps:[0,0.3,1]};
 for(const bearish of [false,true]){
  const pivot=2*entry;
  const bars=bearish?base.map(b=>({...b,open:pivot-b.open,
   high:pivot-b.low,low:pivot-b.high,close:pivot-b.close})):base;
  const report=studyHourlyFvgMidpoint(bars,source,settings);
  assert.equal(report.cohort.formations,1);
  assert.equal(report.cohort.pairedMarkouts,1);
  const matched=report.observations[0];
  assert.equal(matched.midpoint,entry);
  assert.equal(matched.gates.strictCandidate,'PASS');
  for(const candidate of [matched.blindMidpointTouch,matched.confirmedNextOpen]){
   assert.ok(candidate);
   assert.equal(candidate.entryPrice,entry);
   assert.equal(candidate.grossBps,0.3);
   assert.equal(candidate.netBpsByCost[1].netBps,0,
    'descriptive rounded net bps cannot decide the sign');
  }
  const [zero,threshold,high]=report.cohort.pairedNetSignByCost;
  assert.equal(zero.all.bothPositive,1);
  assert.equal(threshold.all.bothPositive,1,
   'strictly positive exact net must not be counted as a zero');
  assert.deepEqual(threshold.strict,threshold.all);
  assert.equal(high.all.neitherPositive,1);
  const beforeExit=studyHourlyFvgMidpointAsOf(bars,source,BASE+26*H,settings);
  assert.equal(beforeExit.cohort.pairedMarkouts,0);
  assert.equal(sumNetCells(beforeExit.cohort.pairedNetSignByCost[1].all),0);
  const atExit=studyHourlyFvgMidpointAsOf(bars,source,BASE+27*H,settings);
  assert.deepEqual(atExit.cohort.pairedNetSignByCost,report.cohort.pairedNetSignByCost);
  // Exact zero gross return must remain nonpositive even at zero cost.
  const flat=bars.map(b=>({...b}));
  flat[26]={...flat[26],close:entry};
  const flatReport=studyHourlyFvgMidpoint(flat,source,{hypotheticalRoundTripCostsBps:[0]});
  assert.equal(flatReport.cohort.pairedNetSignByCost[0].all.neitherPositive,1);
 }
});


test('v66 cross-direction overlapping hypothetical FVG windows remain visible and causal',()=>{
 const base=Array.from({length:46},(_,i)=>candle(i,115,116,110,115));
 const first=onePairedFvgFixture();
 for(let i=0;i<first.length;i++)base[i]=first[i];
 for(let i=26;i<=29;i++)base[i]=candle(i,106,110,103,106);
 base[30]=candle(30,114,116,114,115);
 base[31]=candle(31,114,116,109,115,200);
 for(let i=32;i<46;i++)base[i]=candle(i,115,116,110,115);
 // Retain the earlier bullish setup and mirror the later setup into bearish.
 const mixed=base.map((bar,i)=>i<28?bar:{...bar,
  open:220-bar.open,high:220-bar.low,low:220-bar.high,close:220-bar.close});
 const settings={markoutBars:14};
 const empty={overlappingPairCombinations:0,maxConcurrentPairs:0};
 const single={overlappingPairCombinations:0,maxConcurrentPairs:1};
 const full=studyHourlyFvgMidpoint(mixed,source,settings);
 assert.equal(full.cohort.pairedMarkouts,2);
 assert.deepEqual(full.observations.filter(o=>o.confirmedNextOpen!==null)
  .map(o=>o.direction),['BULLISH','BEARISH']);
 assert.deepEqual(full.cohort.pairedHoldingWindowOverlapByDirection,{
  BULLISH:single,BEARISH:single,
 });
 assert.equal(full.cohort.pairedHoldingWindowCrossDirection,1);
 assert.equal(full.cohort.pairedHoldingWindowOverlap.overlappingPairCombinations,1);
 const before=studyHourlyFvgMidpointAsOf(mixed,source,BASE+37*H,settings);
 assert.deepEqual(before.cohort.pairedHoldingWindowOverlapByDirection,{
  BULLISH:empty,BEARISH:empty,
 });
 assert.equal(before.cohort.pairedHoldingWindowCrossDirection,0);
 const firstExit=studyHourlyFvgMidpointAsOf(mixed,source,BASE+38*H,settings);
 assert.deepEqual(firstExit.cohort.pairedHoldingWindowOverlapByDirection,{
  BULLISH:single,BEARISH:empty,
 });
 assert.equal(firstExit.cohort.pairedHoldingWindowCrossDirection,0);
 const both=studyHourlyFvgMidpointAsOf(mixed,source,BASE+46*H,settings);
 assert.deepEqual(both.cohort.pairedHoldingWindowOverlapByDirection,
  full.cohort.pairedHoldingWindowOverlapByDirection);
 assert.equal(both.cohort.pairedHoldingWindowCrossDirection,1);
 const disjoint=studyHourlyFvgMidpoint(mixed,source,{markoutBars:8});
 assert.equal(disjoint.cohort.pairedHoldingWindowCrossDirection,0,
  'a holding window ending exactly at another entry is not overlapping');
});

test('paired FVG holding windows disclose overlap without leaking immature exits',()=>{
 for(const bearish of [false,true]){
  const base=Array.from({length:46},(_,i)=>candle(i,115,116,110,115));
  const first=onePairedFvgFixture();
  for(let i=0;i<first.length;i++)base[i]=first[i];
  for(let i=26;i<=29;i++)base[i]=candle(i,106,110,103,106);
  base[30]=candle(30,114,116,114,115);
  base[31]=candle(31,114,116,109,115,200);
  for(let i=32;i<46;i++)base[i]=candle(i,115,116,110,115);
  const bars=bearish?base.map(b=>({...b,open:220-b.open,
   high:220-b.low,low:220-b.high,close:220-b.close})):base;
  const settings={markoutBars:14};
  const full=studyHourlyFvgMidpoint(bars,source,settings);
  assert.equal(full.cohort.pairedMarkouts,2);
  assert.deepEqual(full.cohort.pairedHoldingWindowOverlap,{
   overlappingPairCombinations:1,maxConcurrentPairs:2,
  });
  const before=studyHourlyFvgMidpointAsOf(bars,source,BASE+37*H,settings);
  assert.equal(before.cohort.pairedMarkouts,0);
  assert.deepEqual(before.cohort.pairedHoldingWindowOverlap,{
   overlappingPairCombinations:0,maxConcurrentPairs:0,
  });
  const firstExit=studyHourlyFvgMidpointAsOf(bars,source,BASE+38*H,settings);
  assert.equal(firstExit.cohort.pairedMarkouts,1);
  assert.deepEqual(firstExit.cohort.pairedHoldingWindowOverlap,{
   overlappingPairCombinations:0,maxConcurrentPairs:1,
  });
  const both=studyHourlyFvgMidpointAsOf(bars,source,BASE+46*H,settings);
  assert.deepEqual(both.cohort.pairedHoldingWindowOverlap,
   full.cohort.pairedHoldingWindowOverlap);
  const disjoint=studyHourlyFvgMidpoint(bars,source,{markoutBars:3});
  assert.equal(disjoint.cohort.pairedMarkouts,2);
  assert.deepEqual(disjoint.cohort.pairedHoldingWindowOverlap,{
   overlappingPairCombinations:0,maxConcurrentPairs:1,
  });
 }
});


test('overlap dependence is partitioned by strict evidence without promoting unknown volume',()=>{
 for(const bearish of [false,true]){
  const base=Array.from({length:46},(_,i)=>candle(i,115,116,110,115));
  const first=onePairedFvgFixture();
  for(let i=0;i<first.length;i++)base[i]=first[i];
  for(let i=26;i<=29;i++)base[i]=candle(i,106,110,103,106);
  base[30]=candle(30,114,116,114,115);
  base[31]=candle(31,114,116,109,115,200);
  for(let i=32;i<46;i++)base[i]=candle(i,115,116,110,115);
  const bars=bearish?base.map(b=>({...b,open:220-b.open,
   high:220-b.low,low:220-b.high,close:220-b.close})):base;
  const settings={markoutBars:14};
  const empty={overlappingPairCombinations:0,maxConcurrentPairs:0};
  const overlapping={overlappingPairCombinations:1,maxConcurrentPairs:2};
  const verified=studyHourlyFvgMidpoint(bars,source,settings);
  assert.equal(verified.cohort.pairedMarkouts,2);
  assert.equal(verified.cohort.strictPairedMarkouts,2);
  assert.deepEqual(verified.cohort.pairedHoldingWindowOverlapByStrictCandidate,{
   PASS:overlapping,FAIL:empty,INSUFFICIENT_DATA:empty,
  });
  const unknown=studyHourlyFvgMidpoint(bars,{...source,volumeVerified:false},settings);
  assert.equal(unknown.cohort.strictPairedMarkouts,0);
  assert.deepEqual(unknown.cohort.pairedHoldingWindowOverlapByStrictCandidate,{
   PASS:empty,FAIL:empty,INSUFFICIENT_DATA:overlapping,
  });
  const failed=studyHourlyFvgMidpoint(bars,source,{...settings,volumeMultiple:10});
  assert.deepEqual(failed.cohort.pairedHoldingWindowOverlapByStrictCandidate,{
   PASS:empty,FAIL:overlapping,INSUFFICIENT_DATA:empty,
  });
  const beforeExit=studyHourlyFvgMidpointAsOf(bars,source,BASE+37*H,settings);
  assert.deepEqual(beforeExit.cohort.pairedHoldingWindowOverlapByStrictCandidate,{
   PASS:empty,FAIL:empty,INSUFFICIENT_DATA:empty,
  });
  const firstExit=studyHourlyFvgMidpointAsOf(bars,source,BASE+38*H,settings);
  assert.deepEqual(firstExit.cohort.pairedHoldingWindowOverlapByStrictCandidate,{
   PASS:{overlappingPairCombinations:0,maxConcurrentPairs:1},
   FAIL:empty,INSUFFICIENT_DATA:empty,
  });
 }
});


test('cross-status matched FVG overlaps reconcile without treating missing volume as PASS',()=>{
 const cases=[
  {first:200 as number|null,second:100 as number|null,cell:'passFail'},
  {first:200 as number|null,second:null as number|null,cell:'passUnknown'},
  {first:100 as number|null,second:null as number|null,cell:'failUnknown'},
 ] as const;
 const empty={passFail:0,passUnknown:0,failUnknown:0};
 for(const bearish of [false,true]){
  for(const {first,second,cell} of cases){
   const base=Array.from({length:46},(_,i)=>candle(i,115,116,110,115));
   const prefix=onePairedFvgFixture();
   for(let i=0;i<prefix.length;i++)base[i]=prefix[i];
   for(let i=26;i<=29;i++)base[i]=candle(i,106,110,103,106);
   base[30]=candle(30,114,116,114,115);
   base[31]=candle(31,114,116,109,115,second);
   base[23]={...base[23],volume:first};
   for(let i=32;i<46;i++)base[i]=candle(i,115,116,110,115);
   const bars=bearish?base.map(b=>({...b,open:220-b.open,
    high:220-b.low,low:220-b.high,close:220-b.close})):base;
   const settings={markoutBars:14};
   const full=studyHourlyFvgMidpoint(bars,source,settings);
   assert.equal(full.cohort.pairedMarkouts,2);
   assert.equal(full.cohort.pairedHoldingWindowOverlap.overlappingPairCombinations,1);
   assert.deepEqual(full.cohort.pairedHoldingWindowCrossStrictCandidate,{
    ...empty,[cell]:1,
   });
   const within=Object.values(full.cohort.pairedHoldingWindowOverlapByStrictCandidate)
    .reduce((sum,x)=>sum+x.overlappingPairCombinations,0);
   const cross=Object.values(full.cohort.pairedHoldingWindowCrossStrictCandidate)
    .reduce((sum,n)=>sum+n,0);
   assert.equal(within,0);
   assert.equal(within+cross,
    full.cohort.pairedHoldingWindowOverlap.overlappingPairCombinations);
   const before=studyHourlyFvgMidpointAsOf(bars,source,BASE+37*H,settings);
   const one=studyHourlyFvgMidpointAsOf(bars,source,BASE+38*H,settings);
   assert.deepEqual(before.cohort.pairedHoldingWindowCrossStrictCandidate,empty);
   assert.deepEqual(one.cohort.pairedHoldingWindowCrossStrictCandidate,empty);
   const matured=studyHourlyFvgMidpointAsOf(bars,source,BASE+46*H,settings);
   assert.deepEqual(matured.cohort.pairedHoldingWindowCrossStrictCandidate,
    full.cohort.pairedHoldingWindowCrossStrictCandidate);
   // At 8 bars, the first exit closes at the second hypothetical entry:
   // half-open windows touch at the boundary but do not overlap.
   const touching=studyHourlyFvgMidpoint(bars,source,{markoutBars:8});
   assert.equal(touching.cohort.pairedMarkouts,2);
   assert.deepEqual(touching.cohort.pairedHoldingWindowCrossStrictCandidate,empty);
  }
 }
});

test('maximum disjoint matured FVG windows is causal and never promotes unverified volume',()=>{
 for(const bearish of [false,true]){
  const base=Array.from({length:46},(_,i)=>candle(i,115,116,110,115));
  const first=onePairedFvgFixture();
  for(let i=0;i<first.length;i++)base[i]=first[i];
  for(let i=26;i<=29;i++)base[i]=candle(i,106,110,103,106);
  base[30]=candle(30,114,116,114,115);
  base[31]=candle(31,114,116,109,115,200);
  for(let i=32;i<46;i++)base[i]=candle(i,115,116,110,115);
  const bars=bearish?base.map(b=>({...b,open:220-b.open,
   high:220-b.low,low:220-b.high,close:220-b.close})):base;
  const settings={markoutBars:14};
  const full=studyHourlyFvgMidpoint(bars,source,settings);
  assert.equal(full.cohort.pairedMarkouts,2);
  assert.deepEqual(full.cohort.pairedMaximumDisjointWindows,{
   all:1,strictPass:1,strictFail:0,strictUnknown:0,
  },'overlapping windows contribute at most one disjoint matched outcome');
  const unknown=studyHourlyFvgMidpoint(bars,{...source,volumeVerified:false},settings);
  assert.deepEqual(unknown.cohort.pairedMaximumDisjointWindows,{
   all:1,strictPass:0,strictFail:0,strictUnknown:1,
  });
  const mixed=[...bars];
  mixed[31]={...mixed[31],volume:null};
  assert.deepEqual(studyHourlyFvgMidpoint(mixed,source,settings)
   .cohort.pairedMaximumDisjointWindows,{
    all:1,strictPass:1,strictFail:0,strictUnknown:1,
   },'independently optimized status maxima must not be summed');
  const before=studyHourlyFvgMidpointAsOf(bars,source,BASE+37*H,settings);
  assert.deepEqual(before.cohort.pairedMaximumDisjointWindows,{
   all:0,strictPass:0,strictFail:0,strictUnknown:0,
  });
  const firstExit=studyHourlyFvgMidpointAsOf(bars,source,BASE+38*H,settings);
  assert.deepEqual(firstExit.cohort.pairedMaximumDisjointWindows,{
   all:1,strictPass:1,strictFail:0,strictUnknown:0,
  });
  const disjoint=studyHourlyFvgMidpoint(bars,source,{markoutBars:8});
  assert.equal(disjoint.cohort.pairedMarkouts,2);
  assert.deepEqual(disjoint.cohort.pairedMaximumDisjointWindows,{
   all:2,strictPass:2,strictFail:0,strictUnknown:0,
  },'half-open windows meeting at exit/entry can both be retained');
 }
});

test('first-touch volume reasons distinguish missing, gapped and declared evidence causally',()=>{
 for(const bearish of [false,true]){
  const flip=(bars:Bar[])=>bearish?bars.map(b=>({...b,
   open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close})):bars;
  const checks=[
   {bars:fixture(),src:source,reason:'THRESHOLD_EXCEEDED',gate:'PASS'},
   {bars:fixture().map((b,i)=>i===33?{...b,volume:120}:b),
    src:source,reason:'THRESHOLD_NOT_MET',gate:'FAIL'},
   {bars:fixture(),src:{...source,volumeType:'unverified' as const,volumeVerified:false},
    reason:'SOURCE_UNVERIFIED',gate:'INSUFFICIENT_DATA'},
   {bars:fixture().map((b,i)=>i===31?{...b,volume:0}:b),
    src:source,reason:'MISSING_OR_NONPOSITIVE_VOLUME',gate:'INSUFFICIENT_DATA'},
   {bars:fixture().slice(30,37),src:source,
    reason:'PRIOR20_UNAVAILABLE',gate:'INSUFFICIENT_DATA'},
   {bars:fixture().filter(b=>b.time!==BASE+20*H),src:source,
    reason:'PRIOR20_GAP',gate:'INSUFFICIENT_DATA'},
  ] as const;
  for(const {bars,src,reason,gate} of checks){
   const report=studyHourlyFvgMidpoint(flip(bars),src);
   const x=report.observations.find(o=>o.formationClosedAt===BASE+33*H);
   assert.ok(x);
   assert.equal(x.firstTouchOutcome,'TOUCH');
   assert.equal(x.volumeEvidenceReason,reason);
   assert.equal(x.gates.verifiedVolume,gate);
   assert.ok(report.cohort.volumeEvidenceByReason[reason]>=1);
   assert.equal(Object.values(report.cohort.volumeEvidenceByReason)
    .reduce((sum,n)=>sum+n,0),report.cohort.formations);
  }
  const before=studyHourlyFvgMidpointAsOf(flip(fixture()),source,BASE+33*H);
  const formation=before.observations.find(o=>o.formationClosedAt===BASE+33*H);
  assert.ok(formation);
  assert.equal(formation.volumeEvidenceReason,'NOT_EVALUATED');
  assert.equal(formation.gates.verifiedVolume,'INSUFFICIENT_DATA');
  const atTouch=studyHourlyFvgMidpointAsOf(flip(fixture()),source,BASE+34*H);
  assert.equal(atTouch.observations.find(o=>o.formationClosedAt===BASE+33*H)
   ?.volumeEvidenceReason,'THRESHOLD_EXCEEDED');
 }
});


test('first-touch volume evidence has its own completed-bar clock, including unknown evidence',()=>{
 const flip=(series:Bar[],bearish:boolean)=>bearish?series.map(b=>({...b,
  open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close})):series;
 for(const bearish of [false,true]){
  const unverified={...source,volumeType:'unverified' as const,volumeVerified:false};
  const bars=flip(fixture(),bearish);
  const before=studyHourlyFvgMidpointAsOf(bars,unverified,BASE+33*H)
   .observations.find(o=>o.formationClosedAt===BASE+33*H);
  assert.ok(before);
  assert.equal(before.volumeEvidenceReason,'NOT_EVALUATED');
  assert.equal(before.volumeEvidenceObservedAt,null);
  const atTouch=studyHourlyFvgMidpointAsOf(bars,unverified,BASE+34*H)
   .observations.find(o=>o.formationClosedAt===BASE+33*H);
  assert.ok(atTouch);
  assert.equal(atTouch.volumeEvidenceReason,'SOURCE_UNVERIFIED');
  assert.equal(atTouch.volumeEvidenceObservedAt,BASE+34*H);
  assert.equal(atTouch.gates.verifiedVolume,'INSUFFICIENT_DATA');
  assert.equal(atTouch.strictCandidateObservedAt,null,
   'known missing volume evidence is not a strict PASS/FAIL decision');
  const after=target(bars,unverified);
  assert.equal(after.volumeEvidenceObservedAt,BASE+34*H,
   'future markout completion cannot backdate or move the volume clock');
  const missing=flip(fixture(),bearish);
  missing[31].volume=null;
  const missingTouch=target(missing);
  assert.equal(missingTouch.volumeEvidenceReason,'MISSING_OR_NONPOSITIVE_VOLUME');
  assert.equal(missingTouch.volumeEvidenceObservedAt,BASE+34*H);
  const failed=fixture();
  failed[33]=candle(33,105,106,101,102.5,200);
  const failedTouch=target(flip(failed,bearish));
  assert.equal(failedTouch.gates.wickRejection,'FAIL');
  assert.equal(failedTouch.volumeEvidenceObservedAt,BASE+34*H,
   'a known wick failure does not suppress the separate volume clock');
  const gap=fixture();
  gap[33]=candle(33,101,106,100,105.5,200);
  const gapThrough=target(flip(gap,bearish));
  assert.equal(gapThrough.firstTouchOutcome,'OPEN_GAP_THROUGH');
  assert.equal(gapThrough.volumeEvidenceReason,'NOT_EVALUATED');
  assert.equal(gapThrough.volumeEvidenceObservedAt,null);
  const untouched=fixture();
  for(let i=33;i<45;i++)untouched[i]=candle(i,105,106,104,105);
  const noTouch=target(flip(untouched,bearish));
  assert.equal(noTouch.firstTouchOutcome,'NO_TOUCH');
  assert.equal(noTouch.volumeEvidenceReason,'NOT_EVALUATED');
  assert.equal(noTouch.volumeEvidenceObservedAt,null);
 }
});


test('missing first-touch hour has a causal gap-evidence clock, unlike a right-censored tail',()=>{
  for(const bearish of [false,true]){
   const flip=(series:Bar[])=>bearish?series.map(b=>({...b,
    open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close})):series;
   const missing=flip(fixture().filter(b=>b.time!==BASE+33*H));
   const cutoffBeforeGapReceipt=BASE+34*H;
   const cutoffAtGapReceipt=BASE+35*H;
   const before=studyHourlyFvgMidpointAsOf(missing,source,cutoffBeforeGapReceipt)
    .observations.find(o=>o.formationClosedAt===BASE+33*H);
   assert.ok(before);
   assert.equal(before.firstTouchOutcome,'INCOMPLETE_WINDOW');
   assert.equal(before.firstTouchCensorReason,'RIGHT_CENSORED');
   assert.equal(before.firstTouchCensorObservedAt,null);
   const after=studyHourlyFvgMidpointAsOf(missing,source,cutoffAtGapReceipt)
    .observations.find(o=>o.formationClosedAt===BASE+33*H);
   assert.ok(after);
   assert.equal(after.firstTouchOutcome,'INCOMPLETE_WINDOW');
   assert.equal(after.firstTouchCensorReason,'MISSING_HOUR');
   assert.equal(after.firstTouchCensorObservedAt,cutoffAtGapReceipt);
   assert.equal(after.firstTouchOutcomeObservedAt,null,
    'observing an archive gap cannot establish whether the midpoint was touched');
   assert.equal(after.strictCandidateObservedAt,null);
   assert.equal(after.gates.strictCandidate,'INSUFFICIENT_DATA');
   assert.equal(target(missing).firstTouchCensorObservedAt,cutoffAtGapReceipt,
    'later market bars cannot move the first gap-evidence clock');
   const tail=target(flip(fixture().slice(0,33)));
   assert.equal(tail.firstTouchCensorReason,'RIGHT_CENSORED');
   assert.equal(tail.firstTouchCensorObservedAt,null);
   const valid=target(flip(fixture()));
   assert.equal(valid.firstTouchCensorReason,null);
   assert.equal(valid.firstTouchCensorObservedAt,null);
  }
});


test('markout censor evidence clock is causal for missing exit hours and unrepresentable returns',()=>{
 for(const bearish of [false,true]){
  const flip=(series:Bar[])=>bearish?series.map(b=>({...b,
   open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close})):series;
  const observed=(series:Bar[],at:number)=>{
   const result=studyHourlyFvgMidpointAsOf(series,source,at).observations
    .find(o=>o.formationClosedAt===BASE+33*H);
   assert.ok(result);
   return result;
  };
  const missing=flip(fixture().filter(b=>b.time!==BASE+35*H));
  const before=observed(missing,BASE+36*H);
  assert.equal(before.firstTouchOutcome,'TOUCH');
  assert.equal(before.markoutCensorReason,'RIGHT_CENSORED');
  assert.equal(before.markoutCensorObservedAt,null,
   'a future post-gap bar must not leak into an earlier replay');
  const atReceipt=observed(missing,BASE+37*H);
  assert.equal(atReceipt.markoutCensorReason,'MISSING_HOUR');
  assert.equal(atReceipt.markoutCensorObservedAt,BASE+37*H);
  assert.equal(atReceipt.markoutOutcomeObservedAt,null);
  assert.equal(atReceipt.gates.markout,'INSUFFICIENT_DATA');
  assert.equal(target(missing).markoutCensorObservedAt,BASE+37*H,
   'later bars must not move the first observed exit-gap clock');
  const tail=target(flip(fixture().slice(0,35)));
  assert.equal(tail.markoutCensorReason,'RIGHT_CENSORED');
  assert.equal(tail.markoutCensorObservedAt,null);
  const overflow=flip(fixture());
  overflow[36]={...overflow[36],high:Number.MAX_VALUE,close:Number.MAX_VALUE};
  const beforeExit=observed(overflow,BASE+36*H);
  assert.equal(beforeExit.markoutCensorReason,'RIGHT_CENSORED');
  assert.equal(beforeExit.markoutCensorObservedAt,null);
  const atExit=observed(overflow,BASE+37*H);
  assert.equal(atExit.markoutCensorReason,'UNREPRESENTABLE_RETURN');
  assert.equal(atExit.markoutCensorObservedAt,BASE+37*H);
  assert.equal(atExit.markoutOutcomeObservedAt,null);
  assert.equal(atExit.gates.markout,'INSUFFICIENT_DATA');
  const valid=target(flip(fixture()));
  assert.equal(valid.markoutCensorReason,null);
  assert.equal(valid.markoutCensorObservedAt,null);
 }
});

test('v44 inherited candle fields cannot masquerade as archive evidence',()=>{
 const baseline=studyHourlyFvgMidpoint(fixture(),source);
 const historical=fixture();
 const prototype=Object.create(Object.getPrototypeOf(historical[33]));
 Object.defineProperty(prototype,'volume',{value:200});
 Object.setPrototypeOf(historical[33],prototype);
 assert.equal(Reflect.deleteProperty(historical[33],'volume'),true);
 assert.throws(()=>studyHourlyFvgMidpoint(historical,source),/lacks own field evidence/,
  'inherited plausible volume must not qualify a first-touch volume gate');
 assert.throws(()=>studyHourlyFvgMidpointAsOf(historical,source,BASE+34*H),
  /lacks own field evidence/,'as-of copying must not launder inherited volume');
 const future=fixture();
 const futurePrototype=Object.create(Object.getPrototypeOf(future[39]));
 Object.defineProperty(futurePrototype,'time',{value:future[39].time});
 Object.setPrototypeOf(future[39],futurePrototype);
 assert.equal(Reflect.deleteProperty(future[39],'time'),true);
 assert.throws(()=>studyHourlyFvgMidpointAsOf(future,source,BASE+33*H),
  /timestamp lacks own field evidence/,
  'even a future timestamp must be an own archive field');
 assert.deepEqual(studyHourlyFvgMidpoint(fixture(),source),baseline);
 assert.deepEqual(studyHourlyFvgMidpointAsOf(fixture(),source,BASE+33*H),
  studyHourlyFvgMidpoint(fixture().slice(0,33),source));
});

test('v44 inherited source identity and volume certification cannot qualify evidence',()=>{
 const baseline=studyHourlyFvgMidpoint(fixture(),source);
 for(const field of ['datasetId','archiveSha256','instrument','provider',
  'priceSide','volumeType','volumeVerified'] as const){
  const inherited={...source};
  const prototype=Object.create(Object.getPrototypeOf(inherited));
  Object.defineProperty(prototype,field,{value:inherited[field]});
  Object.setPrototypeOf(inherited,prototype);
  assert.equal(Reflect.deleteProperty(inherited,field),true);
  assert.throws(()=>studyHourlyFvgMidpoint(fixture(),inherited),/Invalid source/,
   field+' must be explicitly declared on the supplied source');
  assert.throws(()=>studyHourlyFvgMidpointAsOf(fixture(),inherited,BASE+34*H),
   /Invalid source/);
 }
 const missingOwnVolume=fixture();
 missingOwnVolume[33]={...missingOwnVolume[33],volume:null};
 const observation=target(missingOwnVolume);
 assert.equal(observation.gates.verifiedVolume,'INSUFFICIENT_DATA',
  'explicit null is valid missing evidence, not an inherited value');
 assert.deepEqual(studyHourlyFvgMidpoint(fixture(),source),baseline);
});

test('v45 inherited settings cannot alter the frozen first-touch research protocol',()=>{
 const bars=fixture();
 const baseline=studyHourlyFvgMidpoint(bars,source);
 const settings=[
  ['maxTouchWaitBars',1],['markoutBars',1],
  ['minimumRejectionWickFraction',0.9],['volumeMultiple',10],
  ['hypotheticalRoundTripCostsBps',[999]],
 ] as const;
 for(const [field,value] of settings){
  const inherited=Object.create({[field]:value});
  assert.throws(()=>studyHourlyFvgMidpoint(bars,source,inherited),
   /Inherited FVG study settings/,field+' must not silently change the experiment');
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,BASE+40*H,inherited),
   /Inherited FVG study settings/,field+' must not change as-of replay');
 }
 const poisoned=Object.create(null);
 const prototype=Object.create(null);
 Object.defineProperty(prototype,'volumeMultiple',{get(){
  throw Error('Inherited volume getter must never execute');
 }});
 Object.setPrototypeOf(poisoned,prototype);
 assert.throws(()=>studyHourlyFvgMidpoint(bars,source,poisoned),
  /Inherited FVG study settings/);
 let reads=0;
 const explicit=Object.create(null);
 Object.defineProperty(explicit,'volumeMultiple',{enumerable:true,get(){
  reads++;
  return 1.5;
 }});
 assert.deepEqual(studyHourlyFvgMidpoint(bars,source,explicit),baseline,
  'an explicit own setting retains the frozen default protocol');
 assert.equal(reads,1,'explicit own setting is captured once');
 assert.deepEqual(studyHourlyFvgMidpoint(bars,source,Object.create(null)),baseline,
  'a null-prototype settings object uses the same declared defaults');
});

test('v46 unknown own research settings fail closed, including hidden and symbol keys',()=>{
 const bars=fixture(),cutoff=BASE+37*H;
 const baseline=studyHourlyFvgMidpoint(bars,source);
 const hidden=Object.create(null);
 Object.defineProperty(hidden,'markoutBar',{value:1,enumerable:false});
 const symbol=Symbol('undocumented-cost-model');
 const symbolic={volumeMultiple:1.5,[symbol]:20};
 const misspelled={maxTouchWaitBar:1};
 const invalid=[hidden,symbolic,misspelled] as unknown as
  Parameters<typeof studyHourlyFvgMidpoint>[2][];
 for(const settings of invalid){
  assert.throws(()=>studyHourlyFvgMidpoint(bars,source,settings),
   /Unexpected FVG study setting/,
   'an undeclared setting must never silently fall back to the frozen default');
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,cutoff,settings),
   /Unexpected FVG study setting/,
   'as-of replay must reject the same undeclared protocol settings');
 }
 let hostileReads=0;
 const hostile={volumeMultiple:1.5};
 Object.defineProperty(hostile,'undocumented',{enumerable:true,get(){
  hostileReads++;
  throw Error('unrecognized setting getter must not execute');
 }});
 assert.throws(()=>studyHourlyFvgMidpoint(bars,source,hostile),
  /Unexpected FVG study setting/);
 assert.equal(hostileReads,0,
  'the unknown setting value is never read while validating its key');
 assert.deepEqual(studyHourlyFvgMidpoint(bars,source,{
  maxTouchWaitBars:12,markoutBars:3,minimumRejectionWickFraction:0.5,
  volumeMultiple:1.5,hypotheticalRoundTripCostsBps:[0,5,15],
 }),baseline,'the complete explicit allowlisted protocol remains unchanged');
 assert.deepEqual(studyHourlyFvgMidpointAsOf(bars,source,cutoff,{
  volumeMultiple:1.5,
 }),studyHourlyFvgMidpointAsOf(bars,source,cutoff),
 'an ordinary partial explicit protocol remains valid in as-of replay');
});


test('v47 undeclared source identity fields fail closed without reading hostile getters',()=>{
 const bars=fixture(),cutoff=BASE+37*H;
 const baseline=studyHourlyFvgMidpoint(bars,source);
 const hidden={...source} as FvgSource & {executionSide?:string};
 Object.defineProperty(hidden,'executionSide',{value:'ask',enumerable:false});
 const symbolic={...source,[Symbol('broker-verified')]:true};
 const misspelled={...source,volumeVerifed:true};
 for(const invalid of [hidden,symbolic,misspelled]){
  assert.throws(()=>studyHourlyFvgMidpoint(bars,invalid),
   /Unexpected FVG source declaration/,
   'an unrecognized provenance field cannot be silently omitted from the report');
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,invalid,cutoff),
   /Unexpected FVG source declaration/,
   'as-of replay must enforce the identical frozen source schema');
 }
 let hostileReads=0;
 const hostile={...source};
 Object.defineProperty(hostile,'brokerCertified',{enumerable:true,get(){
  hostileReads++;
  throw Error('unrecognized provenance getter must not execute');
 }});
 assert.throws(()=>studyHourlyFvgMidpoint(bars,hostile),
  /Unexpected FVG source declaration/);
 assert.equal(hostileReads,0,'unrecognized source values are never evaluated');
 const valid=Object.assign(Object.create(null),source) as FvgSource;
 assert.deepEqual(studyHourlyFvgMidpoint(bars,valid),baseline,
  'a complete explicit seven-field source declaration remains unchanged');
 assert.deepEqual(studyHourlyFvgMidpointAsOf(bars,valid,cutoff),
  studyHourlyFvgMidpointAsOf(bars,source,cutoff),
  'as-of replay retains the same valid source evidence');
});


test('v48 completed candles reject undeclared BID/ASK or volume metadata without reading it',()=>{
 const baseline=studyHourlyFvgMidpoint(fixture(),source);
 const cutoff=BASE+37*H;
 const hidden=fixture();
 Object.defineProperty(hidden[33],'ask',{value:105.8,enumerable:false});
 const symbolic=fixture();
 Object.defineProperty(symbolic[33],Symbol('broker-volume-certified'),{value:true});
 const typo=fixture();
 Object.defineProperty(typo[33],'observedMinutes',{value:60});
 for(const candles of [hidden,symbolic,typo]){
  assert.throws(()=>studyHourlyFvgMidpoint(candles,source),
   /Unexpected FVG candle field/,
   'extra archive fields must not silently disappear from BID-only provenance');
  assert.throws(()=>studyHourlyFvgMidpointAsOf(candles,source,cutoff),
   /Unexpected FVG candle field/,
   'completed as-of candles must use the same strict archive schema');
 }
 let hostileReads=0;
 const hostile=fixture();
 Object.defineProperty(hostile[33],'privateBrokerToken',{get(){
  hostileReads++;
  throw Error('synthetic-private-token-must-not-be-read');
 }});
 assert.throws(()=>studyHourlyFvgMidpoint(hostile,source),
  /Unexpected FVG candle field/);
 assert.equal(hostileReads,0,'unknown candle getters must not be evaluated');
 const future=fixture();
 Object.defineProperty(future[39],'ask',{get(){
  throw Error('future ASK must not be read');
 }});
 assert.deepEqual(studyHourlyFvgMidpointAsOf(future,source,BASE+37*H),
  studyHourlyFvgMidpoint(fixture().slice(0,37),source),
  'a future extra key cannot leak into an earlier completed-bar replay');
 assert.throws(()=>studyHourlyFvgMidpointAsOf(future,source,BASE+40*H),
  /Unexpected FVG candle field/,
  'once the extra-key candle closes, its unsupported metadata is rejected');
 assert.deepEqual(studyHourlyFvgMidpoint(fixture(),source),baseline,
  'valid seven-field candles preserve the frozen research result');
});

test('v49 cost scenario arrays reject unmodeled broker-cost evidence without reading it',()=>{
 const bars=fixture(),cutoff=BASE+37*H;
 const baseline=studyHourlyFvgMidpoint(bars,source);
 const hidden=[0,5,15];
 Object.defineProperty(hidden,'financingBps',{value:12,enumerable:false});
 const symbolic=[0,5,15];
 Object.defineProperty(symbolic,Symbol('broker-ask-spread'),{value:3});
 const misspelled=[0,5,15] as number[] & {commissionBps?:number};
 misspelled.commissionBps=4;
 for(const costs of [hidden,symbolic,misspelled]){
  const config={hypotheticalRoundTripCostsBps:costs};
  assert.throws(()=>studyHourlyFvgMidpoint(bars,source,config),
   /Unexpected FVG cost scenario field/,
   'unsupported cost-model metadata must not silently disappear');
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,cutoff,config),
   /Unexpected FVG cost scenario field/,
   'as-of replay must enforce the identical bps-only scenario schema');
 }
 let unknownReads=0;
 const hostile=[0,5,15];
 Object.defineProperty(hostile,'brokerCertifiedCosts',{get(){
  unknownReads++;
  throw Error('unsupported broker-cost getter must never execute');
 }});
 assert.throws(()=>studyHourlyFvgMidpoint(bars,source,{
  hypotheticalRoundTripCostsBps:hostile,
 }),/Unexpected FVG cost scenario field/);
 assert.equal(unknownReads,0,'unknown cost metadata must not be evaluated');
 const iteratorProtected=[0,5,15];
 Object.defineProperty(iteratorProtected,Symbol.iterator,{value(){
  throw Error('untrusted scenario iterator must never execute');
 }});
 assert.deepEqual(studyHourlyFvgMidpoint(bars,source,{
  hypotheticalRoundTripCostsBps:iteratorProtected,
 }),baseline,'index-only valid bps scenarios retain the existing research output');
 assert.deepEqual(studyHourlyFvgMidpointAsOf(bars,source,cutoff,{
  hypotheticalRoundTripCostsBps:iteratorProtected,
 }),studyHourlyFvgMidpointAsOf(bars,source,cutoff),
 'as-of replay retains the same valid bps-only scenarios');
});

test('v50 archive arrays reject undeclared BID/ASK or source metadata without evaluating it',()=>{
 const baseline=studyHourlyFvgMidpoint(fixture(),source);
 const cutoff=BASE+37*H;
 const hidden=fixture();
 Object.defineProperty(hidden,'askQuotes',{value:'unverified',enumerable:false});
 const symbolic=fixture();
 Object.defineProperty(symbolic,Symbol('broker-attestation'),{value:true});
 const extra=fixture() as Bar[] & {brokerSpreadBps?:number};
 extra.brokerSpreadBps=3;
 for(const bars of [hidden,symbolic,extra]){
  assert.throws(()=>studyHourlyFvgMidpoint(bars,source),
   /Unexpected FVG archive array metadata/,
   'archive-level broker claims cannot disappear from a BID-only report');
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,cutoff),
   /Unexpected FVG archive array metadata/,
   'completed-prefix research must reject the same unsupported archive metadata');
 }
 let unknownReads=0;
 const hostile=fixture();
 Object.defineProperty(hostile,'certifiedAskQuotes',{get(){
  unknownReads++;
  throw Error('unreviewed archive metadata getter must not execute');
 }});
 assert.throws(()=>studyHourlyFvgMidpoint(hostile,source),
  /Unexpected FVG archive array metadata/);
 assert.throws(()=>studyHourlyFvgMidpointAsOf(hostile,source,cutoff),
  /Unexpected FVG archive array metadata/);
 assert.equal(unknownReads,0,'unknown archive metadata must never be read');
 const iteratorProtected=fixture();
 Object.defineProperty(iteratorProtected,Symbol.iterator,{value(){
  throw Error('untrusted archive iterator must never execute');
 }});
 assert.deepEqual(studyHourlyFvgMidpoint(iteratorProtected,source),baseline);
 assert.deepEqual(studyHourlyFvgMidpointAsOf(iteratorProtected,source,cutoff),
  studyHourlyFvgMidpointAsOf(fixture(),source,cutoff));
});

test('v51 illustrative cost stress scenarios are strictly ascending and distinct',()=>{
 const bars=fixture(),cutoff=BASE+37*H;
 for(const costs of [[0,5,5],[15,5,0],[0,0],[5,0],[0,5,0]]){
  const config={hypotheticalRoundTripCostsBps:costs};
  assert.throws(()=>studyHourlyFvgMidpoint(bars,source,config),
   /Invalid source identity, volume provenance or frozen FVG study settings/,
   'duplicate or reversed bps stresses must not inflate the scenario census');
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,cutoff,config),
   /Invalid source identity, volume provenance or frozen FVG study settings/,
   'completed-prefix research must enforce the same cost-stress ordering');
 }
 const costs=[0,0.3,5,15];
 const config={hypotheticalRoundTripCostsBps:costs};
 const full=studyHourlyFvgMidpoint(bars,source,config);
 const asOf=studyHourlyFvgMidpointAsOf(bars,source,BASE+40*H,config);
 assert.deepEqual(full.config.hypotheticalRoundTripCostsBps,costs);
 assert.deepEqual(full.cohort.pairedNetSignByCost.map(x=>x.costBps),costs);
 assert.equal(full.cohort.pairedNetSignByCost.length,costs.length);
 assert.deepEqual(asOf,full,'complete as-of replay preserves valid ordered stresses');
});

test('explicit nullish FVG settings cannot silently become frozen defaults',()=>{
 const settings=['maxTouchWaitBars','markoutBars',
  'minimumRejectionWickFraction','volumeMultiple',
  'hypotheticalRoundTripCostsBps'] as const;
 const bars=fixture(),cutoff=BASE+37*H;
 const baseline=studyHourlyFvgMidpoint(bars,source);
 const asOfBaseline=studyHourlyFvgMidpointAsOf(bars,source,cutoff);
 for(const setting of settings){
  for(const value of [undefined,null]){
   const malformed={[setting]:value} as unknown as FvgConfig;
   assert.throws(()=>studyHourlyFvgMidpoint(bars,source,malformed),
    /Explicit nullish FVG study setting/);
   assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,cutoff,malformed),
    /Explicit nullish FVG study setting/);
  }
 }
 let reads=0;
 const accessor=Object.defineProperty({},'maxTouchWaitBars',{get(){
  reads++;
  return undefined;
 }}) as FvgConfig;
 assert.throws(()=>studyHourlyFvgMidpoint(bars,source,accessor),
  /Explicit nullish FVG study setting/);
 assert.equal(reads,1,'declared nullish getter must not be read twice');
 assert.deepEqual(studyHourlyFvgMidpoint(bars,source),baseline);
 assert.deepEqual(studyHourlyFvgMidpointAsOf(bars,source,cutoff),asOfBaseline);
});

test('v54 observed first-disposition wait census is causal and excludes censored tails',()=>{
 const config={maxTouchWaitBars:3};
 const bars=[
  candle(0,100,101,99,100),
  candle(1,102,104,101,103),
  candle(2,106,107,105,106),
  candle(3,106,107,103.5,106),
  candle(4,106,107,101,106),
 ];
 const read=(series:Bar[])=>studyHourlyFvgMidpoint(series,source,config);
 const asOf=(series:Bar[],closedAt:number)=>
  studyHourlyFvgMidpointAsOf(series,source,closedAt,config);
 const empty={TOUCH:[0,0,0],OPEN_GAP_THROUGH:[0,0,0],NO_TOUCH:[0,0,0]};
 assert.equal(read(bars).observations.length,1,'only the intended bullish gap forms');
 assert.deepEqual(asOf(bars,BASE+3*H).cohort.firstDispositionWaitBarCounts,empty,
  'formation alone cannot report an observed first touch');
 assert.deepEqual(asOf(bars,BASE+4*H).cohort.firstDispositionWaitBarCounts,empty,
  'the first untouched completed hour is not a known no-touch deadline');
 assert.deepEqual(asOf(bars,BASE+5*H).cohort.firstDispositionWaitBarCounts,
  {TOUCH:[0,1,0],OPEN_GAP_THROUGH:[0,0,0],NO_TOUCH:[0,0,0]},
  'a second-hour midpoint touch is counted only when its bar closes');
 assert.deepEqual(read(bars).cohort.firstDispositionWaitBarCounts,
  asOf(bars,BASE+5*H).cohort.firstDispositionWaitBarCounts);
 const gapThrough=bars.slice(0,4);
 gapThrough[3]=candle(3,102,107,101,105);
 assert.deepEqual(asOf(gapThrough,BASE+4*H).cohort.firstDispositionWaitBarCounts,
  {TOUCH:[0,0,0],OPEN_GAP_THROUGH:[1,0,0],NO_TOUCH:[0,0,0]},
  'an opening gap-through is not a certified touch or hypothetical fill');
 const untouched=[...bars.slice(0,4),
  candle(4,106,107,103.5,106),candle(5,106,107,103.5,106)];
 assert.deepEqual(asOf(untouched,BASE+5*H).cohort.firstDispositionWaitBarCounts,empty,
  'two observed no-touch hours do not prove a three-hour negative');
 assert.deepEqual(asOf(untouched,BASE+6*H).cohort.firstDispositionWaitBarCounts,
  {TOUCH:[0,0,0],OPEN_GAP_THROUGH:[0,0,0],NO_TOUCH:[0,0,1]},
  'a known no-touch outcome is counted at its configured completed deadline');
 assert.deepEqual(read(untouched.slice(0,5)).cohort.firstDispositionWaitBarCounts,empty,
  'a right-censored tail cannot be reclassified as a late no-touch');
});


test('v55 directional first-disposition waits reconcile and remain causal for both sides',()=>{
 const config={maxTouchWaitBars:3};
 const bullish=[
  candle(0,100,101,99,100),candle(1,102,104,101,103),
  candle(2,106,107,105,106),candle(3,106,107,103.5,106),
  candle(4,106,107,101,106),
 ];
 const mirror=(bars:Bar[])=>bars.map(b=>({...b,
  open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close}));
 const empty=()=>({TOUCH:[0,0,0],OPEN_GAP_THROUGH:[0,0,0],NO_TOUCH:[0,0,0]});
 const cases=[
  {name:'touch',bars:bullish,at:BASE+5*H,
   expected:{TOUCH:[0,1,0],OPEN_GAP_THROUGH:[0,0,0],NO_TOUCH:[0,0,0]}},
  {name:'gap-through',bars:[...bullish.slice(0,3),candle(3,102,107,101,105)],
   at:BASE+4*H,expected:{TOUCH:[0,0,0],OPEN_GAP_THROUGH:[1,0,0],NO_TOUCH:[0,0,0]}},
  {name:'no-touch',bars:[...bullish.slice(0,4),
   candle(4,106,107,103.5,106),candle(5,106,107,103.5,106)],
   at:BASE+6*H,expected:{TOUCH:[0,0,0],OPEN_GAP_THROUGH:[0,0,0],NO_TOUCH:[0,0,1]}},
  {name:'censored',bars:bullish.slice(0,4),at:BASE+4*H,expected:empty()},
 ];
 for(const side of ['BULLISH','BEARISH'] as const){
  for(const sample of cases){
   const bars=side==='BULLISH'?sample.bars:mirror(sample.bars);
   const report=studyHourlyFvgMidpointAsOf(bars,source,sample.at,config);
   const other=side==='BULLISH'?'BEARISH':'BULLISH';
   assert.equal(report.observations.length,1,sample.name+' '+side);
   assert.equal(report.observations[0].direction,side);
   assert.deepEqual(report.cohort.firstDispositionWaitBarCountsByDirection[side],
    sample.expected,sample.name+' '+side);
   assert.deepEqual(report.cohort.firstDispositionWaitBarCountsByDirection[other],
    empty(),sample.name+' other side');
   assert.deepEqual(report.cohort.firstDispositionWaitBarCounts,sample.expected);
   assert.deepEqual(studyHourlyFvgMidpoint(bars,source,config).cohort
    .firstDispositionWaitBarCountsByDirection,
    report.cohort.firstDispositionWaitBarCountsByDirection);
   if(sample.name==='censored')
    assert.equal(report.cohort.firstTouchOutcome.INCOMPLETE_WINDOW,1);
  }
 }
 const before=studyHourlyFvgMidpointAsOf(bullish,source,BASE+4*H,config);
 assert.deepEqual(before.cohort.firstDispositionWaitBarCountsByDirection.BULLISH,empty(),
  'a future second-hour touch cannot leak into the first-hour prefix');
});

test('v56 observed waiting exposure counts only completed, uncensored hours',()=>{
 const config={maxTouchWaitBars:3};
 const bullish=[
  candle(0,100,101,99,100),candle(1,102,104,101,103),
  candle(2,106,107,105,106),candle(3,106,107,103.5,106),
  candle(4,106,107,101,106),
 ];
 const mirror=(bars:Bar[])=>bars.map(b=>({...b,
  open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close}));
 const cases=[
  {name:'second-hour touch',bars:bullish,at:BASE+5*H,exposure:[1,1,0],outcome:'TOUCH'},
  {name:'first-hour gap-through',bars:[...bullish.slice(0,3),candle(3,102,107,101,105)],
   at:BASE+4*H,exposure:[1,0,0],outcome:'OPEN_GAP_THROUGH'},
  {name:'completed no-touch',bars:[...bullish.slice(0,4),
   candle(4,106,107,103.5,106),candle(5,106,107,103.5,106)],
   at:BASE+6*H,exposure:[1,1,1],outcome:'NO_TOUCH'},
  {name:'right-censored',bars:bullish.slice(0,4),
   at:BASE+4*H,exposure:[1,0,0],outcome:'INCOMPLETE_WINDOW'},
  {name:'missing second hour',bars:[...bullish.slice(0,4),candle(5,106,107,103.5,106)],
   at:BASE+6*H,exposure:[1,0,0],outcome:'INCOMPLETE_WINDOW'},
  {name:'formation only',bars:bullish.slice(0,3),
   at:BASE+3*H,exposure:[0,0,0],outcome:'INCOMPLETE_WINDOW'},
 ];
 for(const side of ['BULLISH','BEARISH'] as const){
  for(const sample of cases){
   const bars=side==='BULLISH'?sample.bars:mirror(sample.bars);
   const other=side==='BULLISH'?'BEARISH':'BULLISH';
   const report=studyHourlyFvgMidpointAsOf(bars,source,sample.at,config);
   assert.equal(report.observations.length,1,sample.name+' '+side);
   assert.equal(report.observations[0].firstTouchOutcome,sample.outcome);
   assert.equal(report.observations[0].firstTouchObservedWaitBars,
    sample.exposure.reduce((n,x)=>n+x,0),sample.name);
   assert.deepEqual(report.cohort.firstTouchObservedExposureByWait,sample.exposure);
   assert.deepEqual(report.cohort.firstTouchObservedExposureByWaitByDirection[side],sample.exposure);
   assert.deepEqual(report.cohort.firstTouchObservedExposureByWaitByDirection[other],[0,0,0]);
   assert.deepEqual(studyHourlyFvgMidpoint(bars,source,config).cohort
    .firstTouchObservedExposureByWait,report.cohort.firstTouchObservedExposureByWait);
   if(sample.name==='missing second hour')
    assert.equal(report.observations[0].firstTouchCensorReason,'MISSING_HOUR');
  }
 }
 const early=studyHourlyFvgMidpointAsOf(bullish,source,BASE+4*H,config);
 assert.deepEqual(early.cohort.firstTouchObservedExposureByWait,[1,0,0]);
 assert.deepEqual(early.cohort.firstDispositionWaitBarCounts.TOUCH,[0,0,0]);
});


test('v57 censor attrition is indexed by completed wait and conserves each risk set',()=>{
 const config={maxTouchWaitBars:3};
 const formation=[
  candle(0,100,101,99,100),candle(1,102,104,101,103),
  candle(2,106,107,105,106),
 ];
 const noTouch=candle(3,106,107,103.5,106);
 const laterNoTouch=candle(4,106,107,103.5,106);
 const touch=candle(4,106,107,101,106);
 const mirror=(bars:Bar[])=>bars.map(b=>({...b,
  open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close}));
 const zero=[0,0,0];
 const cases=[
  {name:'formation-only tail',bars:formation,reason:'RIGHT_CENSORED',index:0,exposure:zero},
  {name:'one-hour tail',bars:[...formation,noTouch],reason:'RIGHT_CENSORED',
   index:1,exposure:[1,0,0]},
  {name:'two-hour tail',bars:[...formation,noTouch,laterNoTouch],
   reason:'RIGHT_CENSORED',index:2,exposure:[1,1,0]},
  {name:'missing second hour',bars:[...formation,noTouch,candle(5,106,107,103.5,106)],
   reason:'MISSING_HOUR',index:1,exposure:[1,0,0]},
  {name:'observed second-hour touch',bars:[...formation,noTouch,touch],
   reason:null,index:-1,exposure:[1,1,0]},
  {name:'completed no-touch',bars:[...formation,noTouch,laterNoTouch,
   candle(5,106,107,103.5,106)],reason:null,index:-1,exposure:[1,1,1]},
  {name:'opening gap-through',bars:[...formation,candle(3,102,107,101,105)],
   reason:null,index:-1,exposure:[1,0,0]},
 ] as const;
 for(const side of ['BULLISH','BEARISH'] as const){
  for(const sample of cases){
   const bars=side==='BULLISH'?sample.bars:mirror([...sample.bars]);
   const other=side==='BULLISH'?'BEARISH':'BULLISH';
   const report=studyHourlyFvgMidpoint(bars,source,config);
   const census=report.cohort;
   assert.equal(report.observations.length,1,sample.name+' '+side);
   assert.deepEqual(census.firstTouchObservedExposureByWait,sample.exposure);
   const expected={MISSING_HOUR:[0,0,0],RIGHT_CENSORED:[0,0,0]};
   if(sample.reason!==null)expected[sample.reason][sample.index]=1;
   assert.deepEqual(census.firstTouchCensoredAfterWaitByReason,expected,
    sample.name+' pooled');
   assert.deepEqual(census.firstTouchCensoredAfterWaitByReasonByDirection[side],expected,
    sample.name+' '+side);
   assert.deepEqual(census.firstTouchCensoredAfterWaitByReasonByDirection[other],{
    MISSING_HOUR:[0,0,0],RIGHT_CENSORED:[0,0,0],
   });
   assert.equal(census.incompleteWindowByReason.MISSING_HOUR+
    census.incompleteWindowByReason.RIGHT_CENSORED,sample.reason===null?0:1);
   assert.deepEqual(studyHourlyFvgMidpointAsOf(bars,source,
    bars[bars.length-1].time+H,config).cohort.firstTouchCensoredAfterWaitByReason,
    expected,'full completed as-of prefix must match offline cohort');
  }
 }
 const future=[...formation,noTouch,touch];
 const earlier=studyHourlyFvgMidpointAsOf(future,source,BASE+4*H,config);
 assert.deepEqual(earlier.cohort.firstTouchCensoredAfterWaitByReason,
  {MISSING_HOUR:[0,0,0],RIGHT_CENSORED:[0,1,0]},
  'future midpoint touch cannot erase an earlier right-censored as-of prefix');
 const matured=studyHourlyFvgMidpointAsOf(future,source,BASE+5*H,config);
 assert.deepEqual(matured.cohort.firstTouchCensoredAfterWaitByReason,
  {MISSING_HOUR:[0,0,0],RIGHT_CENSORED:[0,0,0]});
});


test('v58 markout censor attrition remains partitioned by strict evidence state',()=>{
 const missing=fixture().filter(b=>b.time!==BASE+35*H);
 const weak=missing.map(b=>({...b}));
 weak.find(b=>b.time===BASE+33*H)!.close=104.5;
 const tail=fixture().slice(0,35);
 const overflow=fixture();
 overflow[36]={...overflow[36],high:Number.MAX_VALUE,close:Number.MAX_VALUE};
 const cases=[
  {name:'verified-volume strict pass missing exit',bars:missing,src:source,
   gate:'PASS',reason:'MISSING_HOUR'},
  {name:'wick failure missing exit',bars:weak,src:source,
   gate:'FAIL',reason:'MISSING_HOUR'},
  {name:'unverified volume missing exit',bars:missing,
   src:{...source,volumeVerified:false},gate:'INSUFFICIENT_DATA',reason:'MISSING_HOUR'},
  {name:'strict pass right-censored exit',bars:tail,src:source,
   gate:'PASS',reason:'RIGHT_CENSORED'},
  {name:'strict pass unrepresentable exit',bars:overflow,src:source,
   gate:'PASS',reason:'UNREPRESENTABLE_RETURN'},
 ] as const;
 for(const sample of cases){
  const report=studyHourlyFvgMidpoint(sample.bars,sample.src);
  const formation=report.observations.find(o=>o.formationClosedAt===BASE+33*H);
  assert.ok(formation,sample.name);
  assert.equal(formation.gates.strictCandidate,sample.gate,sample.name);
  assert.equal(formation.markoutCensorReason,sample.reason,sample.name);
  assert.ok(report.cohort.markoutCensoredByReasonByStrictCandidate[sample.gate]
   [sample.reason]>=1,sample.name);
  for(const reason of ['MISSING_HOUR','RIGHT_CENSORED','UNREPRESENTABLE_RETURN'] as const){
   const classified=(['PASS','FAIL','INSUFFICIENT_DATA'] as const)
    .reduce((sum,gate)=>sum+
     report.cohort.markoutCensoredByReasonByStrictCandidate[gate][reason],0);
   assert.equal(classified,report.cohort.markoutCensoredByReason[reason],
    'pooled censor count must equal all three strict populations');
  }
  assert.deepEqual(studyHourlyFvgMidpointAsOf(sample.bars,sample.src,
   sample.bars[sample.bars.length-1].time+H),report,
   'full completed-prefix replay must retain the same censor evidence');
 }
 const beforeExit=studyHourlyFvgMidpointAsOf(overflow,source,BASE+36*H);
 const formation=beforeExit.observations.find(o=>o.formationClosedAt===BASE+33*H);
 assert.equal(formation?.markoutCensorReason,'RIGHT_CENSORED',
  'future unrepresentable exit cannot leak into an earlier prefix');
 assert.ok(beforeExit.cohort.markoutCensoredByReasonByStrictCandidate.PASS.RIGHT_CENSORED>=1);
});


test('v59 markout censor reasons reconcile by formation direction and strict evidence',()=>{
 const weak=fixture().filter(b=>b.time!==BASE+35*H);
 weak.find(b=>b.time===BASE+33*H)!.close=104.5;
 const missing=fixture().filter(b=>b.time!==BASE+35*H);
 const tail=fixture().slice(0,35);
 const cases=[
  {name:'verified strict pass with missing exit',bars:missing,src:source,
   gate:'PASS',reason:'MISSING_HOUR'},
  {name:'known wick failure with missing exit',bars:weak,src:source,
   gate:'FAIL',reason:'MISSING_HOUR'},
  {name:'unverified volume with missing exit',bars:missing,
   src:{...source,volumeVerified:false},gate:'INSUFFICIENT_DATA',reason:'MISSING_HOUR'},
  {name:'strict pass with censored tail',bars:tail,src:source,
   gate:'PASS',reason:'RIGHT_CENSORED'},
  {name:'strict pass with unrepresentable exit',bars:fixture(),src:source,
   gate:'PASS',reason:'UNREPRESENTABLE_RETURN'},
 ] as const;
 const mirror=(bars:Bar[])=>bars.map(b=>({...b,
  open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close}));
 for(const sample of cases){
  for(const direction of ['BULLISH','BEARISH'] as const){
   const bars=direction==='BULLISH'?sample.bars.map(b=>({...b})):mirror(sample.bars);
   if(sample.reason==='UNREPRESENTABLE_RETURN'){
    bars[36]={...bars[36],high:Number.MAX_VALUE,close:Number.MAX_VALUE};
   }
   const report=studyHourlyFvgMidpoint(bars,sample.src);
   const formation=report.observations.find(o=>o.formationClosedAt===BASE+33*H);
   assert.ok(formation,sample.name);
   assert.equal(formation.direction,direction,sample.name);
   assert.equal(formation.gates.strictCandidate,sample.gate,sample.name);
   assert.equal(formation.markoutCensorReason,sample.reason,sample.name);
   const cohort=report.cohort;
   assert.ok(cohort.markoutCensoredByReasonByDirectionAndStrictCandidate[direction]
    [sample.gate][sample.reason]>=1,sample.name);
   for(const reason of ['MISSING_HOUR','RIGHT_CENSORED','UNREPRESENTABLE_RETURN'] as const){
    for(const gate of ['PASS','FAIL','INSUFFICIENT_DATA'] as const){
     assert.equal((['BULLISH','BEARISH'] as const).reduce((sum,side)=>
      sum+cohort.markoutCensoredByReasonByDirectionAndStrictCandidate[side][gate][reason],0),
      cohort.markoutCensoredByReasonByStrictCandidate[gate][reason],
      'directional strict evidence must conserve each pooled censor population');
    }
   }
   assert.deepEqual(studyHourlyFvgMidpointAsOf(bars,sample.src,
    bars[bars.length-1].time+H),report,
    'complete as-of replay must preserve directional censor attribution');
   if(sample.reason==='UNREPRESENTABLE_RETURN'){
    const before=studyHourlyFvgMidpointAsOf(bars,sample.src,BASE+36*H);
    const prior=before.observations.find(o=>o.formationClosedAt===BASE+33*H);
    assert.equal(prior?.markoutCensorReason,'RIGHT_CENSORED');
    assert.ok(before.cohort.markoutCensoredByReasonByDirectionAndStrictCandidate
     [direction].PASS.RIGHT_CENSORED>=1,
     'future exit overflow must not appear before its completed bar close');
   }
  }
 }
});

test('v60 directional prior-20 volume census preserves unknown and causal timing',()=>{
 const mirror=(rows:Bar[])=>rows.map(b=>({...b,
  open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close}));
 const early=[
  candle(0,99,100,98,99),candle(1,100,102,99,101),
  candle(2,105,106,104,105),candle(3,105,106,101,105.5,200),
  candle(4,105.5,107,105,106),
 ];
 const missingVolume=fixture();missingVolume[20]={...missingVolume[20],volume:null};
 const weakVolume=fixture();weakVolume[33]={...weakVolume[33],volume:100};
 const cases=[
  {bars:fixture(),src:{...source,volumeVerified:false},
   reason:'SOURCE_UNVERIFIED',formation:33},
  {bars:early,src:source,reason:'PRIOR20_UNAVAILABLE',formation:3},
  {bars:fixture().filter(b=>b.time!==BASE+25*H),
   src:source,reason:'PRIOR20_GAP',formation:33},
  {bars:missingVolume,src:source,reason:'MISSING_OR_NONPOSITIVE_VOLUME',formation:33},
  {bars:weakVolume,src:source,reason:'THRESHOLD_NOT_MET',formation:33},
  {bars:fixture(),src:source,reason:'THRESHOLD_EXCEEDED',formation:33},
 ] as const;
 const reasons=['NOT_EVALUATED','SOURCE_UNVERIFIED','PRIOR20_UNAVAILABLE',
  'PRIOR20_GAP','MISSING_OR_NONPOSITIVE_VOLUME','THRESHOLD_NOT_MET',
  'THRESHOLD_EXCEEDED'] as const;
 for(const sample of cases){
  for(const side of ['BULLISH','BEARISH'] as const){
   const bars=side==='BULLISH'?sample.bars:mirror(sample.bars);
   const report=studyHourlyFvgMidpoint(bars,sample.src);
   const target=report.observations.find(o=>
    o.formationClosedAt===BASE+sample.formation*H);
   assert.ok(target);
   assert.equal(target.direction,side);
   assert.equal(target.volumeEvidenceReason,sample.reason);
   assert.ok(report.cohort.volumeEvidenceByReasonByDirection[side][sample.reason]>=1);
   for(const reason of reasons){
    const counted=(direction:'BULLISH'|'BEARISH')=>
     report.observations.filter(o=>o.direction===direction&&
      o.volumeEvidenceReason===reason).length;
    assert.equal(report.cohort.volumeEvidenceByReasonByDirection.BULLISH[reason],
     counted('BULLISH'));
    assert.equal(report.cohort.volumeEvidenceByReasonByDirection.BEARISH[reason],
     counted('BEARISH'));
    assert.equal(report.cohort.volumeEvidenceByReason[reason],
     counted('BULLISH')+counted('BEARISH'));
   }
   assert.deepEqual(studyHourlyFvgMidpointAsOf(bars,sample.src,
    bars[bars.length-1].time+H),report);
   const pending=studyHourlyFvgMidpointAsOf(bars,sample.src,
    BASE+sample.formation*H);
   const before=pending.observations.find(o=>
    o.formationClosedAt===BASE+sample.formation*H);
   assert.ok(before);
   assert.equal(before.volumeEvidenceReason,'NOT_EVALUATED');
   assert.equal(before.volumeEvidenceObservedAt,null);
   assert.ok(pending.cohort.volumeEvidenceByReasonByDirection[side]
    .NOT_EVALUATED>=1);
  }
 }
});


test('v62 directional matched-pair attrition retains strict FAIL/UNKNOWN and as-of censoring',()=>{
 const mirror=(rows:Bar[])=>rows.map(b=>({...b,
  open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close}));
 const weak=fixture();weak[33]={...weak[33],close:104.5};
 const cases=[
  {name:'paired strict pass',bars:fixture(),src:source,config:{},
   strict:'PASS',matched:true},
  {name:'paired strict fail on volume',bars:fixture(),src:source,
   config:{volumeMultiple:10},strict:'FAIL',matched:true},
  {name:'paired unknown source volume',bars:fixture(),
   src:{...source,volumeVerified:false},config:{},
   strict:'INSUFFICIENT_DATA',matched:true},
  {name:'unpaired failed wick',bars:weak,src:source,config:{},
   strict:'FAIL',matched:false},
  {name:'unpaired incomplete exit',bars:fixture().slice(0,35),
   src:source,config:{},strict:'PASS',matched:false},
  {name:'unpaired pre-touch prefix',bars:fixture(),src:source,
   config:{},strict:'INSUFFICIENT_DATA',matched:false,asOf:BASE+33*H},
 ] as const;
 const statuses=['PASS','FAIL','INSUFFICIENT_DATA'] as const;
 const sides=['BULLISH','BEARISH'] as const;
 for(const sample of cases){
  for(const side of sides){
   const bars=side==='BULLISH'?sample.bars:mirror(sample.bars);
   const at='asOf' in sample?sample.asOf:
    bars[bars.length-1].time+H;
   const report=studyHourlyFvgMidpointAsOf(bars,sample.src,at,sample.config);
   const selected=report.observations.find(o=>o.formationClosedAt===BASE+33*H);
   assert.ok(selected,sample.name+' '+side);
   assert.equal(selected.direction,side);
   assert.equal(selected.gates.strictCandidate,sample.strict,sample.name);
   assert.equal(selected.confirmedNextOpen!==null,sample.matched,sample.name);
   const cohort=report.cohort;
   for(const direction of sides){
    for(const status of statuses){
     const observations=report.observations.filter(o=>
      o.direction===direction&&o.gates.strictCandidate===status);
     const matched=observations.filter(o=>
      o.blindMidpointTouch!==null&&o.confirmedNextOpen!==null).length;
     assert.equal(cohort.pairedByDirectionAndStrictCandidate[direction][status],
      matched,sample.name+' paired '+direction+' '+status);
     assert.equal(cohort.unpairedByDirectionAndStrictCandidate[direction][status],
      observations.length-matched,sample.name+' unpaired '+direction+' '+status);
     assert.equal(sides.reduce((sum,d)=>
      sum+cohort.pairedByDirectionAndStrictCandidate[d][status],0),
      cohort.pairedByStrictCandidate[status]);
     assert.equal(sides.reduce((sum,d)=>
      sum+cohort.unpairedByDirectionAndStrictCandidate[d][status],0),
      cohort.unpairedByStrictCandidate[status]);
    }
   }
   if(!('asOf' in sample))
    assert.deepEqual(report,studyHourlyFvgMidpoint(bars,sample.src,sample.config));
  }
 }
 // One archive can contain both directions; source gaps cannot be filled
 // to make a misleading contiguous paired sample.
 const shiftedBear=mirror(fixture()).map((bar,i)=>({...bar,time:BASE+(50+i)*H}));
 const mixed=studyHourlyFvgMidpoint([...fixture(),...shiftedBear],source);
 assert.ok(mixed.cohort.pairedByDirectionAndStrictCandidate.BULLISH.PASS>=1);
 assert.ok(mixed.cohort.pairedByDirectionAndStrictCandidate.BEARISH.PASS>=1);
 assert.deepEqual(studyHourlyFvgMidpointAsOf([...fixture(),...shiftedBear],
  source,BASE+90*H),mixed);
});

test('v64 strict first-touch evidence is classified by causal waiting hour',()=>{
 const mirror=(rows:Bar[])=>rows.map(b=>({...b,
  open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close}));
 const delayed=fixture();
 delayed[33]=candle(33,105.5,107,105,106,100);
 delayed[34]=candle(34,105.5,107,101,106,200);
 const cases=[
  {bars:fixture(),src:source,config:{},wait:1,status:'PASS'},
  {bars:fixture(),src:source,config:{volumeMultiple:10},wait:1,status:'FAIL'},
  {bars:fixture(),src:{...source,volumeVerified:false},config:{},
   wait:1,status:'INSUFFICIENT_DATA'},
  {bars:delayed,src:source,config:{},wait:2,status:'PASS'},
  {bars:delayed,src:source,config:{volumeMultiple:10},wait:2,status:'FAIL'},
  {bars:delayed,src:{...source,volumeVerified:false},config:{},
   wait:2,status:'INSUFFICIENT_DATA'},
 ] as const;
 const statuses=['PASS','FAIL','INSUFFICIENT_DATA'] as const;
 for(const sample of cases){
  for(const side of ['BULLISH','BEARISH'] as const){
   const bars=side==='BULLISH'?sample.bars:mirror(sample.bars);
   const report=studyHourlyFvgMidpoint(bars,sample.src,sample.config);
   const selected=report.observations.find(o=>o.formationClosedAt===BASE+33*H);
   assert.ok(selected);
   assert.equal(selected.direction,side);
   assert.equal(selected.firstTouchOutcome,'TOUCH');
   assert.equal(selected.gates.strictCandidate,sample.status);
   assert.equal((selected.firstTouchOutcomeObservedAt!-selected.formationClosedAt)/H,
    sample.wait);
   const expected={PASS:Array(12).fill(0),FAIL:Array(12).fill(0),
    INSUFFICIENT_DATA:Array(12).fill(0)};
   for(const o of report.observations){
    if(o.firstTouchOutcome!=='TOUCH')continue;
    assert.ok(o.firstTouchOutcomeObservedAt!==null);
    expected[o.gates.strictCandidate][
     (o.firstTouchOutcomeObservedAt-o.formationClosedAt)/H-1]++;
   }
   assert.deepEqual(report.cohort.firstTouchStrictCandidateByWait,expected);
   for(let wait=0;wait<12;wait++)
    assert.equal(statuses.reduce((sum,status)=>
     sum+report.cohort.firstTouchStrictCandidateByWait[status][wait],0),
     report.cohort.firstDispositionWaitBarCounts.TOUCH[wait]);
   const before=studyHourlyFvgMidpointAsOf(bars,sample.src,
    BASE+(33+sample.wait-1)*H,sample.config);
   const pending=before.observations.find(o=>o.formationClosedAt===BASE+33*H);
   assert.ok(pending);
   assert.equal(pending.firstTouchOutcome,'INCOMPLETE_WINDOW');
   assert.equal(pending.gates.strictCandidate,'INSUFFICIENT_DATA');
   const at=studyHourlyFvgMidpointAsOf(bars,sample.src,
    BASE+(33+sample.wait)*H,sample.config);
   const observed=at.observations.find(o=>o.formationClosedAt===BASE+33*H);
   assert.ok(observed);
   assert.equal(observed.firstTouchOutcome,'TOUCH');
   assert.equal(observed.gates.strictCandidate,sample.status);
   assert.deepEqual(at,studyHourlyFvgMidpoint(bars.slice(0,33+sample.wait),
    sample.src,sample.config));
  }
 }
 const base=[candle(0,100,101,99,100),candle(1,102,104,101,103),
  candle(2,106,107,105,106)];
 for(const bars of [
  [...base,candle(3,102,107,101,105)],
  [...base,candle(3,106,107,104,106),
   candle(4,106,107,104,106),candle(5,106,107,104,106)],
  [...base,candle(3,106,107,104,106)],
 ]){
  const cohort=studyHourlyFvgMidpoint(bars,source,{maxTouchWaitBars:3}).cohort;
  assert.equal(cohort.firstDispositionWaitBarCounts.TOUCH.reduce((a,b)=>a+b,0),0);
  for(const status of statuses)
   assert.deepEqual(cohort.firstTouchStrictCandidateByWait[status],[0,0,0]);
 }
});


test('v65 directional strict first-touch waits reconcile without promoting unknown evidence',()=>{
 const mirror=(rows:Bar[])=>rows.map(b=>({...b,
  open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close}));
 const delayed=fixture();
 delayed[33]=candle(33,105.5,107,105,106,100);
 delayed[34]=candle(34,105.5,107,101,106,200);
 const cases=[
  {bars:fixture(),src:source,config:{},wait:1,status:'PASS'},
  {bars:fixture(),src:source,config:{volumeMultiple:10},wait:1,status:'FAIL'},
  {bars:fixture(),src:{...source,volumeVerified:false},config:{},
   wait:1,status:'INSUFFICIENT_DATA'},
  {bars:delayed,src:source,config:{},wait:2,status:'PASS'},
  {bars:delayed,src:source,config:{volumeMultiple:10},wait:2,status:'FAIL'},
  {bars:delayed,src:{...source,volumeVerified:false},config:{},
   wait:2,status:'INSUFFICIENT_DATA'},
 ] as const;
 const sides=['BULLISH','BEARISH'] as const;
 const statuses=['PASS','FAIL','INSUFFICIENT_DATA'] as const;
 const check=(report:ReturnType<typeof studyHourlyFvgMidpoint>)=>{
  for(const side of sides){
   for(const status of statuses){
    const expected=Array(12).fill(0);
    for(const o of report.observations){
     if(o.direction!==side||o.firstTouchOutcome!=='TOUCH'||
      o.gates.strictCandidate!==status)continue;
     assert.ok(o.firstTouchOutcomeObservedAt!==null);
     const wait=(o.firstTouchOutcomeObservedAt-o.formationClosedAt)/H-1;
     expected[wait]++;
    }
    assert.deepEqual(report.cohort.firstTouchStrictCandidateByWaitByDirection
     [side][status],expected);
    for(let wait=0;wait<12;wait++){
     assert.equal(sides.reduce((sum,d)=>sum+
      report.cohort.firstTouchStrictCandidateByWaitByDirection[d][status][wait],0),
      report.cohort.firstTouchStrictCandidateByWait[status][wait]);
     assert.equal(statuses.reduce((sum,st)=>sum+
      report.cohort.firstTouchStrictCandidateByWaitByDirection[side][st][wait],0),
      report.cohort.firstDispositionWaitBarCountsByDirection[side].TOUCH[wait]);
    }
   }
  }
 };
 for(const sample of cases){
  for(const side of sides){
   const bars=side==='BULLISH'?sample.bars:mirror(sample.bars);
   const report=studyHourlyFvgMidpoint(bars,sample.src,sample.config);
   const selected=report.observations.find(o=>o.formationClosedAt===BASE+33*H);
   assert.ok(selected);
   assert.equal(selected.direction,side);
   assert.equal(selected.gates.strictCandidate,sample.status);
   assert.equal((selected.firstTouchOutcomeObservedAt!-selected.formationClosedAt)/H,
    sample.wait);
   check(report);
   assert.deepEqual(studyHourlyFvgMidpointAsOf(bars,sample.src,
    bars[bars.length-1].time+H,sample.config),report);
   const before=studyHourlyFvgMidpointAsOf(bars,sample.src,
    BASE+(33+sample.wait-1)*H,sample.config);
   const pending=before.observations.find(o=>o.formationClosedAt===BASE+33*H);
   assert.ok(pending);
   assert.equal(pending.firstTouchOutcome,'INCOMPLETE_WINDOW');
   check(before);
  }
 }
 // Both directions in one source; a missing interval must never be filled.
 const shiftedBear=mirror(fixture()).map((bar,i)=>({...bar,time:BASE+(50+i)*H}));
 const mixedBars=[...fixture(),...shiftedBear];
 const mixed=studyHourlyFvgMidpoint(mixedBars,source);
 check(mixed);
 assert.ok(mixed.cohort.firstTouchStrictCandidateByWaitByDirection.BULLISH.PASS[0]>=1);
 assert.ok(mixed.cohort.firstTouchStrictCandidateByWaitByDirection.BEARISH.PASS[0]>=1);
 assert.deepEqual(studyHourlyFvgMidpointAsOf(mixedBars,source,
  mixedBars[mixedBars.length-1].time+H),mixed);
 // A gap-through, completed no-touch, and censored tail have no strict touch.
 const base=[candle(0,100,101,99,100),candle(1,102,104,101,103),
  candle(2,106,107,105,106)];
 for(const bars of [
  [...base,candle(3,102,107,101,105)],
  [...base,candle(3,106,107,104,106),candle(4,106,107,104,106),
   candle(5,106,107,104,106)],
  [...base,candle(3,106,107,104,106)],
 ]){
  const cohort=studyHourlyFvgMidpoint(bars,source,{maxTouchWaitBars:3}).cohort;
  for(const side of sides)for(const status of statuses)
   assert.deepEqual(cohort.firstTouchStrictCandidateByWaitByDirection[side][status],
    [0,0,0]);
 }
});

test('v67 matched net-sign outcomes conserve direction and strict evidence after exit close',()=>{
 const mirror=(rows:Bar[])=>rows.map(b=>({...b,
  open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close}));
 const shiftedBear=mirror(fixture()).map((bar,i)=>({...bar,time:BASE+(50+i)*H}));
 const mixed=[...fixture(),...shiftedBear];
 const sides=['BULLISH','BEARISH'] as const;
 const statuses=['all','strict','strictFail','strictUnknown'] as const;
 const cells=['bothPositive','blindOnlyPositive','confirmedOnlyPositive','neitherPositive'] as const;
 const sum=(counts:Record<(typeof cells)[number],number>)=>
  cells.reduce((total,cell)=>total+counts[cell],0);
 for(const sample of [
  {src:source,config:{},status:'PASS'},
  {src:source,config:{volumeMultiple:10},status:'FAIL'},
  {src:{...source,volumeVerified:false},config:{},status:'INSUFFICIENT_DATA'},
 ] as const){
  const report=studyHourlyFvgMidpoint(mixed,sample.src,sample.config);
  for(const [formationAt,side] of [
   [BASE+33*H,'BULLISH'],[BASE+83*H,'BEARISH'],
  ] as const){
   const o=report.observations.find(o=>o.formationClosedAt===formationAt);
   assert.ok(o);
   assert.equal(o.direction,side);
   assert.equal(o.gates.strictCandidate,sample.status);
   assert.ok(o.blindMidpointTouch&&o.confirmedNextOpen);
  }
  for(const [index,scenario] of report.cohort.pairedNetSignByCost.entries()){
   for(const status of statuses){
    for(const cell of cells){
     assert.equal(scenario[status][cell],
      sides.reduce((total,side)=>total+scenario.byDirection[side][status][cell],0));
    }
   }
   for(const side of sides){
    const matched=report.observations.filter(o=>o.direction===side&&
     o.blindMidpointTouch!==null&&o.confirmedNextOpen!==null);
    assert.equal(sum(scenario.byDirection[side].all),matched.length);
    for(const status of ['strict','strictFail','strictUnknown'] as const){
     const gate=status==='strict'?'PASS':status==='strictFail'?'FAIL':'INSUFFICIENT_DATA';
     assert.equal(sum(scenario.byDirection[side][status]),
      matched.filter(o=>o.gates.strictCandidate===gate).length);
    }
    // Reconstruct cell counts from the actual completed BID markouts in
    // this moderate synthetic fixture, independently of cohort counters.
    for(const cell of cells){
     let expected=0;
     for(const o of matched){
      const blind=o.blindMidpointTouch!.netBpsByCost[index].netBps>0;
      const confirmed=o.confirmedNextOpen!.netBpsByCost[index].netBps>0;
      const observed=blind?(confirmed?'bothPositive':'blindOnlyPositive'):
       (confirmed?'confirmedOnlyPositive':'neitherPositive');
      if(observed===cell)expected++;
     }
     assert.equal(scenario.byDirection[side].all[cell],expected);
    }
   }
  }
  const before=studyHourlyFvgMidpointAsOf(mixed,sample.src,BASE+36*H,sample.config);
  assert.equal(before.cohort.pairedMarkouts,0,
   'future exit cannot populate directional paired net-sign cells');
  for(const scenario of before.cohort.pairedNetSignByCost)
   for(const side of sides)assert.equal(sum(scenario.byDirection[side].all),0);
  const bullMatured=studyHourlyFvgMidpointAsOf(mixed,sample.src,BASE+38*H,sample.config);
  assert.ok(bullMatured.cohort.pairedNetSignByCost.every(s=>
   sum(s.byDirection.BULLISH.all)>=1&&sum(s.byDirection.BEARISH.all)===0));
  assert.deepEqual(studyHourlyFvgMidpointAsOf(mixed,sample.src,
   mixed[mixed.length-1].time+H,sample.config),report);
 }
});

test('v68 directional gross ordering independently reconciles strict evidence and closed exits',()=>{
 const mirror=(rows:Bar[])=>rows.map(b=>({...b,
  open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close}));
 const shiftedBear=mirror(fixture()).map((bar,i)=>({...bar,time:BASE+(50+i)*H}));
 const mixed=[...fixture(),...shiftedBear];
 const sides=['BULLISH','BEARISH'] as const;
 const statuses=['all','strict','strictFail','strictUnknown'] as const;
 const cells=['confirmedHigher','blindHigher','equal'] as const;
 const sum=(counts:Record<(typeof cells)[number],number>)=>
  cells.reduce((total,cell)=>total+counts[cell],0);
 for(const sample of [
  {src:source,config:{},gate:'PASS'},
  {src:source,config:{volumeMultiple:10},gate:'FAIL'},
  {src:{...source,volumeVerified:false},config:{},gate:'INSUFFICIENT_DATA'},
 ] as const){
  const report=studyHourlyFvgMidpoint(mixed,sample.src,sample.config);
  const ordering=report.cohort.pairedGrossOrdering;
  const matured=report.observations.filter(o=>
   o.blindMidpointTouch!==null&&o.confirmedNextOpen!==null);
  assert.ok(matured.some(o=>o.direction==='BULLISH'));
  assert.ok(matured.some(o=>o.direction==='BEARISH'));
  assert.equal(sum(ordering.all),matured.length);
  for(const status of statuses)for(const cell of cells){
   assert.equal(ordering[status][cell],sides.reduce((total,side)=>
    total+ordering.byDirection[side][status][cell],0));
  }
  for(const side of sides){
   const sideMatched=matured.filter(o=>o.direction===side);
   for(const status of statuses){
    const gate=status==='strict'?'PASS':
     status==='strictFail'?'FAIL':'INSUFFICIENT_DATA';
    const selected=status==='all'?sideMatched:
     sideMatched.filter(o=>o.gates.strictCandidate===gate);
    assert.equal(sum(ordering.byDirection[side][status]),selected.length);
    for(const cell of cells){
     // Reconstruct from completed entry prices, not rounded gross-bps fields.
     const expected=selected.filter(o=>{
      const blind=o.blindMidpointTouch!.entryPrice;
      const confirmed=o.confirmedNextOpen!.entryPrice;
      const observed=confirmed===blind?'equal':
       o.direction==='BULLISH'?
        confirmed<blind?'confirmedHigher':'blindHigher':
        confirmed>blind?'confirmedHigher':'blindHigher';
      return observed===cell;
     }).length;
     assert.equal(ordering.byDirection[side][status][cell],expected);
    }
   }
   assert.ok(sideMatched.some(o=>o.gates.strictCandidate===sample.gate));
  }
  const before=studyHourlyFvgMidpointAsOf(mixed,sample.src,BASE+36*H,sample.config);
  for(const side of sides)assert.equal(sum(before.cohort.pairedGrossOrdering.byDirection[side].all),0,
   'future fixed exit must not populate directional gross ordering');
  const firstMatured=studyHourlyFvgMidpointAsOf(mixed,sample.src,BASE+38*H,sample.config);
  assert.ok(sum(firstMatured.cohort.pairedGrossOrdering.byDirection.BULLISH.all)>=1);
  assert.equal(sum(firstMatured.cohort.pairedGrossOrdering.byDirection.BEARISH.all),0);
  assert.deepEqual(studyHourlyFvgMidpointAsOf(mixed,sample.src,
   mixed[mixed.length-1].time+H,sample.config),report);
 }
});


test('v69 matched first-touch wait attrition reconciles strict status and as-of exit maturity',()=>{
 const failed=fixture();
 failed[33]=candle(33,105,106,101,102.5,200);
 const delayed=fixture();
 delayed[33]=candle(33,105,106,103,105);
 delayed[34]=candle(34,105,106,101,105.5,200);
 delayed[35]=candle(35,105.5,107,105,106);
 delayed[36]=candle(36,106,108,105,107);
 delayed[37]=candle(37,107,111,106,110);
 const samples=[
  {bars:fixture(),src:source},
  {bars:fixture().slice(0,35),src:source}, // touch with censored exit
  {bars:failed,src:source}, // observed touch, failed wick
  {bars:fixture(),src:{...source,volumeVerified:false}},
  {bars:delayed,src:source}, // first touch in second completed hour
 ];
 const statuses=['PASS','FAIL','INSUFFICIENT_DATA'] as const;
 for(const {bars,src} of samples){
  const full=studyHourlyFvgMidpoint(bars,src);
  for(const status of statuses)for(let wait=0;wait<12;wait++){
   const touches=full.observations.filter(o=>o.firstTouchOutcome==='TOUCH'&&
    o.gates.strictCandidate===status&&o.firstTouchObservedWaitBars===wait+1);
   const paired=touches.filter(o=>o.blindMidpointTouch!==null&&
    o.confirmedNextOpen!==null).length;
   assert.equal(full.cohort.firstTouchPairedByWaitAndStrictCandidate[status][wait],paired);
   assert.equal(full.cohort.firstTouchUnpairedByWaitAndStrictCandidate[status][wait],
    touches.length-paired);
   assert.equal(full.cohort.firstTouchStrictCandidateByWait[status][wait],touches.length);
  }
  const atEnd=bars[bars.length-1].time+H;
  assert.deepEqual(studyHourlyFvgMidpointAsOf(bars,src,atEnd),full);
 }
 const beforeExit=studyHourlyFvgMidpointAsOf(fixture(),source,BASE+34*H);
 const afterExit=studyHourlyFvgMidpointAsOf(fixture(),source,BASE+37*H);
 assert.ok(beforeExit.cohort.firstTouchUnpairedByWaitAndStrictCandidate.PASS[0]>=1,
  'first touch may be observed while the fixed exit is still censored');
 assert.equal(beforeExit.cohort.firstTouchPairedByWaitAndStrictCandidate.PASS[0],0,
  'a future fixed exit cannot be counted as a matched return');
 assert.ok(afterExit.cohort.firstTouchPairedByWaitAndStrictCandidate.PASS[0]>=1,
  'matched evidence appears only once the shared exit candle closes');
});

test('as-of future timestamp getter cannot rewrite historical source or frozen settings',()=>{
 const bars=fixture(),mutableSource:FvgSource={...source};
 const mutableConfig:FvgConfig={
  volumeMultiple:1.5,hypotheticalRoundTripCostsBps:[0,5,15],
 };
 const cutoff=BASE+34*H,firstFuture=bars[34],originalFutureTime=firstFuture.time;
 let futureTimestampReads=0;
 Object.defineProperty(firstFuture,'time',{get(){
  futureTimestampReads++;
  mutableSource.volumeVerified=false;
  mutableSource.provider='spoofed-after-cutoff';
  mutableConfig.volumeMultiple=10;
  mutableConfig.hypotheticalRoundTripCostsBps=[0,900];
  return originalFutureTime;
 }});
 for(const field of ['open','high','low','close','volume','observed_minutes'])
  Object.defineProperty(firstFuture,field,{get(){
   throw Error('future '+field+' must not be inspected');
  }});
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,mutableSource,cutoff,mutableConfig),
  /FVG source declaration field changed during declaration snapshot/,
  'a retroactively rewritten original declaration must fail closed, not merely export its old copy');
 assert.ok(futureTimestampReads>0);
 assert.equal(mutableSource.volumeVerified,false);
 assert.equal(mutableConfig.volumeMultiple,10);
});

test('v71 post-snapshot archive and cost schemas reject getter-injected broker metadata',()=>{
 const rows=fixture();
 const first=rows[0];
 Object.defineProperty(rows,0,{configurable:true,enumerable:true,get(){
  Object.defineProperty(rows,'brokerAskQuote',{value:101,configurable:true});
  return first;
 }});
 assert.throws(()=>studyHourlyFvgMidpoint(rows,source),/archive array metadata/,
  'a candle getter must not attach unreported array-level ASK evidence');

 const rowMutation=fixture();
 const firstRow=rowMutation[0],originalOpen=firstRow.open;
 Object.defineProperty(firstRow,'open',{configurable:true,enumerable:true,get(){
  Object.defineProperty(firstRow,'ask',{value:101,configurable:true});
  return originalOpen;
 }});
 assert.throws(()=>studyHourlyFvgMidpoint(rowMutation,source),/candle schema changed/,
  'a candle field getter must not add unreported broker-side fields');

 const costs=[0,5,15];
 Object.defineProperty(costs,0,{configurable:true,enumerable:true,get(){
  Object.defineProperty(costs,'brokerCommission',{value:2,configurable:true});
  return 0;
 }});
 assert.throws(()=>studyHourlyFvgMidpoint(fixture(),source,{
  hypotheticalRoundTripCostsBps:costs,
 }),/cost scenario field/,
 'a cost getter must not add broker commissions outside the bps-only protocol');
});

test('v71 post-snapshot as-of rechecks completed schemas without future OHLC reads',()=>{
 for(const mutate of ['archive','completed'] as const){
  const rows=fixture();
  const future=rows[35],futureTime=future.time;
  Object.defineProperty(future,'time',{configurable:true,enumerable:true,get(){
   if(mutate==='archive')
    Object.defineProperty(rows,'brokerSpread',{value:3,configurable:true});
   else
    Object.defineProperty(rows[0],'ask',{value:101,configurable:true});
   return futureTime;
  }});
  for(const field of ['open','high','low','close','volume','observed_minutes'])
   Object.defineProperty(future,field,{configurable:true,get(){
    throw Error('future '+field+' must never be read');
   }});
  assert.throws(()=>studyHourlyFvgMidpointAsOf(rows,source,BASE+34*H),
   mutate==='archive'?/archive array metadata/:/completed candle schema changed/,
   'future timestamp side effects cannot silently alter already-revealed evidence schema');
 }
});

test('v72 full-history rejects retroactive declaration edits from completed-bar accessors',()=>{
 const rows=fixture(),mutableSource:FvgSource={...source};
 const mutableConfig:FvgConfig={
  volumeMultiple:1.5,hypotheticalRoundTripCostsBps:[0,5,15],
 };
 const first=rows[0],originalTime=first.time;
 let completedGetterReads=0;
 Object.defineProperty(first,'time',{configurable:true,enumerable:true,get(){
  completedGetterReads++;
  mutableSource.volumeVerified=false;
  mutableSource.provider='rewritten-by-completed-bar-getter';
  mutableConfig.volumeMultiple=10;
  mutableConfig.hypotheticalRoundTripCostsBps=[0,900];
  return originalTime;
 }});
 assert.throws(()=>studyHourlyFvgMidpoint(rows,mutableSource,mutableConfig),
  /FVG source declaration field changed during declaration snapshot/,
  'post-preflight declaration edits must be rejected rather than silently accepted');
 assert.ok(completedGetterReads>0);
 assert.equal(mutableSource.volumeVerified,false);
 assert.equal(mutableConfig.volumeMultiple,10);
});

test('v72 source/config getter cannot resize the bounded historical candle population',()=>{
 for(const action of ['append','truncate'] as const){
  const rows=fixture();
  const config:FvgConfig={};
  let reads=0;
  Object.defineProperty(config,'volumeMultiple',{enumerable:true,get(){
   reads++;
   if(action==='append')rows.push(candle(40));
   else rows.pop();
   return 1.5;
  }});
  assert.throws(()=>studyHourlyFvgMidpoint(rows,source,config),
   /array length changed during declaration snapshot/,
   'historical source population must be fixed before settings are inspected');
  assert.equal(reads,1);
 }
});

test('v73 rejects source getter injecting broker metadata after preflight',()=>{
 for(const asOf of [false,true]){
  const src:FvgSource={...source};
  const provider=src.provider;
  let reads=0;
  Object.defineProperty(src,'provider',{enumerable:true,configurable:true,get(){
   reads++;
   Object.defineProperty(src,'brokerAskQuote',{value:101,configurable:true});
   return provider;
  }});
  assert.throws(()=>asOf?
   studyHourlyFvgMidpointAsOf(fixture(),src,BASE+34*H):
   studyHourlyFvgMidpoint(fixture(),src),
   /source declaration schema changed during snapshot/);
  assert.equal(reads,1);
 }
});

test('v73 rejects setting schema injection from settings or source getters',()=>{
 for(const asOf of [false,true])for(const actor of ['config','source'] as const){
  const src:FvgSource={...source};
  const config:FvgConfig={volumeMultiple:1.5};
  if(actor==='config'){
   Object.defineProperty(config,'volumeMultiple',{enumerable:true,configurable:true,get(){
    Object.defineProperty(config,'brokerCommissionBps',{value:2,configurable:true});
    return 1.5;
   }});
  }else{
   const provider=src.provider;
   Object.defineProperty(src,'provider',{enumerable:true,configurable:true,get(){
    Object.defineProperty(config,'brokerCommissionBps',{value:2,configurable:true});
    return provider;
   }});
  }
  assert.throws(()=>asOf?
   studyHourlyFvgMidpointAsOf(fixture(),src,BASE+34*H,config):
   studyHourlyFvgMidpoint(fixture(),src,config),
   /study setting schema changed during snapshot/);
 }
});


test('v74 directional first-touch matched attrition preserves status, wait and exit censoring',()=>{
 const mirror=(rows:Bar[])=>rows.map(b=>({...b,
  open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close}));
 const failed=fixture();
 failed[33]=candle(33,105,106,101,102.5,200);
 const delayed=fixture();
 delayed[33]=candle(33,105,106,103,105);
 delayed[34]=candle(34,105,106,101,105.5,200);
 delayed[35]=candle(35,105.5,107,105,106);
 delayed[36]=candle(36,106,108,105,107);
 delayed[37]=candle(37,107,111,106,110);
 const shiftedBear=mirror(fixture()).map((bar,i)=>({...bar,time:BASE+(50+i)*H}));
 const samples=[
  {bars:fixture(),src:source},
  {bars:fixture().slice(0,35),src:source}, // first touch, exit not yet observed
  {bars:failed,src:source}, // known failed wick, no confirmed comparator
  {bars:fixture(),src:{...source,volumeVerified:false}}, // unknown source volume
  {bars:delayed,src:source}, // second completed waiting hour
  {bars:mirror(delayed),src:source},
  {bars:[...fixture(),...shiftedBear],src:source}, // both sides, no filled source gaps
 ];
 const sides=['BULLISH','BEARISH'] as const;
 const statuses=['PASS','FAIL','INSUFFICIENT_DATA'] as const;
 const check=(report:ReturnType<typeof studyHourlyFvgMidpoint>)=>{
  for(const side of sides)for(const status of statuses){
   const expectedPaired=Array(12).fill(0);
   const expectedUnpaired=Array(12).fill(0);
   for(const o of report.observations){
    if(o.direction!==side||o.firstTouchOutcome!=='TOUCH'||
       o.gates.strictCandidate!==status)continue;
    const wait=o.firstTouchObservedWaitBars-1;
    assert.ok(wait>=0&&wait<12);
    const paired=o.blindMidpointTouch!==null&&o.confirmedNextOpen!==null;
    (paired?expectedPaired:expectedUnpaired)[wait]++;
   }
   assert.deepEqual(report.cohort.firstTouchPairedByWaitAndStrictCandidateByDirection
    [side][status],expectedPaired);
   assert.deepEqual(report.cohort.firstTouchUnpairedByWaitAndStrictCandidateByDirection
    [side][status],expectedUnpaired);
   for(let wait=0;wait<12;wait++){
    assert.equal(expectedPaired[wait]+expectedUnpaired[wait],
     report.cohort.firstTouchStrictCandidateByWaitByDirection[side][status][wait]);
   }
  }
  for(const status of statuses)for(let wait=0;wait<12;wait++){
   const sum=(field:'firstTouchPairedByWaitAndStrictCandidateByDirection'|
    'firstTouchUnpairedByWaitAndStrictCandidateByDirection')=>
    sides.reduce((n,side)=>n+report.cohort[field][side][status][wait],0);
   assert.equal(sum('firstTouchPairedByWaitAndStrictCandidateByDirection'),
    report.cohort.firstTouchPairedByWaitAndStrictCandidate[status][wait]);
   assert.equal(sum('firstTouchUnpairedByWaitAndStrictCandidateByDirection'),
    report.cohort.firstTouchUnpairedByWaitAndStrictCandidate[status][wait]);
  }
 };
 for(const {bars,src} of samples){
  const report=studyHourlyFvgMidpoint(bars,src);
  check(report);
  check(studyHourlyFvgMidpointAsOf(bars,src,bars[bars.length-1].time+H));
  assert.deepEqual(studyHourlyFvgMidpointAsOf(bars,src,bars[bars.length-1].time+H),report);
 }
 const before=studyHourlyFvgMidpointAsOf(fixture(),source,BASE+34*H);
 const after=studyHourlyFvgMidpointAsOf(fixture(),source,BASE+37*H);
 check(before);check(after);
 assert.ok(before.cohort.firstTouchUnpairedByWaitAndStrictCandidateByDirection.BULLISH.PASS[0]>0);
 assert.equal(before.cohort.firstTouchPairedByWaitAndStrictCandidateByDirection.BULLISH.PASS[0],0);
 assert.ok(after.cohort.firstTouchPairedByWaitAndStrictCandidateByDirection.BULLISH.PASS[0]>0);
 // An opening gap-through is not a matched or unmatched observed first touch.
 const base=[candle(0,100,101,99,100),candle(1,102,104,101,103),
  candle(2,106,107,105,106),candle(3,102,107,101,105)];
 const gap=studyHourlyFvgMidpoint(base,source);
 check(gap);
 assert.equal(gap.cohort.firstTouchOutcome.OPEN_GAP_THROUGH,1);
 for(const side of sides)for(const status of statuses)
  assert.equal(gap.cohort.firstTouchPairedByWaitAndStrictCandidateByDirection[side][status]
   .reduce((n,x)=>n+x,0),0);
});


test('v75 rejects same-length archive row substitutions before and after candle capture',()=>{
 // A declaration getter could replace a completed candle with a different,
 // still-valid BID row without changing array length or schema.
 const before=fixture();
 const src:FvgSource={...source};
 Object.defineProperty(src,'provider',{enumerable:true,configurable:true,get(){
  before[33]={...before[33],volume:0};
  return source.provider;
 }});
 assert.throws(()=>studyHourlyFvgMidpoint(before,src),
  /row identity changed during snapshot/);

 // A later completed-bar accessor could replace an already snapshotted row.
 const after=fixture(),first=after[0],secondTime=after[1].time;
 Object.defineProperty(after[1],'time',{enumerable:true,configurable:true,get(){
  after[0]={...first,close:101};
  return secondTime;
 }});
 assert.throws(()=>studyHourlyFvgMidpoint(after,source),
  /row identity changed during snapshot/);
 assert.deepEqual(studyHourlyFvgMidpoint(fixture(),source).source,source);
});

test('v75 as-of rejects future-timestamp replacement of revealed rows without reading future prices',()=>{
 const rows=fixture(),cutoff=BASE+34*H;
 const future=rows[35],futureTime=future.time;
 let reads=0;
 Object.defineProperty(future,'time',{enumerable:true,configurable:true,get(){
  reads++;
  rows[0]={...rows[0],volume:999};
  return futureTime;
 }});
 for(const field of ['open','high','low','close','volume','observed_minutes'])
  Object.defineProperty(future,field,{get(){
   throw Error('future '+field+' must not be inspected');
  }});
 assert.throws(()=>studyHourlyFvgMidpointAsOf(rows,source,cutoff),
  /row identity changed during snapshot/);
 assert.equal(reads,1,'future timestamp is read once; future prices stay unread');

 const declarationRows=fixture(),declared:FvgSource={...source};
 Object.defineProperty(declared,'provider',{enumerable:true,configurable:true,get(){
  declarationRows[0]={...declarationRows[0],volume:999};
  return source.provider;
 }});
 assert.throws(()=>studyHourlyFvgMidpointAsOf(declarationRows,declared,cutoff),
  /row identity changed during snapshot/);
 assert.deepEqual(studyHourlyFvgMidpointAsOf(fixture(),source,cutoff),
  studyHourlyFvgMidpoint(fixture().slice(0,34),source));
});

test('v76 rejects in-place completed candle mutations after a historical field snapshot',()=>{
 const rows=fixture(),secondTime=rows[1].time;
 Object.defineProperty(rows[1],'time',{enumerable:true,configurable:true,get(){
  rows[0].close=101; // Same object, same schema and array slot identity.
  return secondTime;
 }});
 assert.throws(()=>studyHourlyFvgMidpoint(rows,source),
  /completed candle field changed during snapshot/);

 const within=fixture(),firstHigh=within[0].high;
 Object.defineProperty(within[0],'high',{enumerable:true,configurable:true,get(){
  within[0].low=99; // Valid BID row after mutation; not a valid frozen snapshot.
  return firstHigh;
 }});
 assert.throws(()=>studyHourlyFvgMidpoint(within,source),
  /completed candle field changed during snapshot/);
 assert.deepEqual(studyHourlyFvgMidpoint(fixture(),source).source,source);
});

test('v76 as-of detects in-place revealed row edits from future timestamps without future price reads',()=>{
 const rows=fixture(),cutoff=BASE+34*H,future=rows[35],futureTime=future.time;
 let timeReads=0;
 Object.defineProperty(future,'time',{enumerable:true,configurable:true,get(){
  timeReads++;
  rows[0].volume=999; // A completed row changed in place.
  return futureTime;
 }});
 for(const field of ['open','high','low','close','volume','observed_minutes'])
  Object.defineProperty(future,field,{get(){
   throw Error('future '+field+' must remain unread');
  }});
 assert.throws(()=>studyHourlyFvgMidpointAsOf(rows,source,cutoff),
  /completed candle field changed during snapshot/);
 assert.equal(timeReads,1);
 assert.deepEqual(studyHourlyFvgMidpointAsOf(fixture(),source,cutoff),
  studyHourlyFvgMidpoint(fixture().slice(0,34),source));
});


test('v77 source and setting getters cannot rewrite previously declared evidence in place',()=>{
 for(const asOf of [false,true]){
  const evaluate=(src:FvgSource,config:FvgConfig)=>asOf?
   studyHourlyFvgMidpointAsOf(fixture(),src,BASE+34*H,config):
   studyHourlyFvgMidpoint(fixture(),src,config);
  const src:FvgSource={...source},config:FvgConfig={volumeMultiple:1.5};
  const provider=src.provider;
  Object.defineProperty(src,'provider',{enumerable:true,configurable:true,get(){
   src.volumeVerified=false; // Same own keys, but changed certification.
   return provider;
  }});
  assert.throws(()=>evaluate(src,config),
   /source declaration field changed during declaration snapshot/);

  const settings:FvgConfig={maxTouchWaitBars:12,volumeMultiple:1.5};
  Object.defineProperty(settings,'volumeMultiple',{
   enumerable:true,configurable:true,get(){
    settings.maxTouchWaitBars=1; // Earlier setting was already read.
    return 1.5;
   },
  });
  assert.throws(()=>evaluate({...source},settings),
   /study setting field changed during declaration snapshot/);

  const crossSource:FvgSource={...source};
  const crossConfig:FvgConfig={volumeMultiple:1.5};
  Object.defineProperty(crossSource,'provider',{
   enumerable:true,configurable:true,get(){
    crossConfig.volumeMultiple=2; // Source getter rewrites frozen settings.
    return provider;
   },
  });
  assert.throws(()=>evaluate(crossSource,crossConfig),
   /study setting field changed during declaration snapshot/);
 }
});

test('v77 cost getters cannot rewrite an earlier cost stress cell in place',()=>{
 for(const asOf of [false,true]){
  const costs=[0,5,15];
  Object.defineProperty(costs,1,{enumerable:true,configurable:true,get(){
   costs[0]=7; // Same length, own indices and ascending copied values.
   return 5;
  }});
  const config:FvgConfig={hypotheticalRoundTripCostsBps:costs};
  assert.throws(()=>asOf?
   studyHourlyFvgMidpointAsOf(fixture(),source,BASE+34*H,config):
   studyHourlyFvgMidpoint(fixture(),source,config),
   /cost scenario field changed during declaration snapshot/);
 }
});

test('v77 stable accessor-backed declarations retain exact historical and as-of parity',()=>{
 const src:FvgSource={...source};
 Object.defineProperty(src,'provider',{enumerable:true,configurable:true,
  get(){return source.provider;}});
 const costs=[0,5,15];
 Object.defineProperty(costs,1,{enumerable:true,configurable:true,
  get(){return 5;}});
 const config:FvgConfig={maxTouchWaitBars:12,
  hypotheticalRoundTripCostsBps:costs};
 Object.defineProperty(config,'maxTouchWaitBars',{enumerable:true,configurable:true,
  get(){return 12;}});
 assert.deepEqual(studyHourlyFvgMidpoint(fixture(),src,config),
  studyHourlyFvgMidpoint(fixture(),source,{
   maxTouchWaitBars:12,hypotheticalRoundTripCostsBps:[0,5,15],
  }));
 assert.deepEqual(studyHourlyFvgMidpointAsOf(fixture(),src,BASE+34*H,config),
  studyHourlyFvgMidpoint(fixture().slice(0,34),source,{
   maxTouchWaitBars:12,hypotheticalRoundTripCostsBps:[0,5,15],
  }));
});

test('v78 as-of rejects retroactive future timestamp rewrites without future OHLC reads',()=>{
 const cutoff=BASE+33*H;
 const baseline=studyHourlyFvgMidpoint(fixture().slice(0,33),source);
 for(const kind of ['self','earlier'] as const){
  const bars=fixture();
  const original=bars[34].time;
  Object.defineProperty(bars[34],'time',{enumerable:true,configurable:true,get(){
   if(kind==='self')Object.defineProperty(bars[34],'time',{
    value:original+H,enumerable:true,configurable:true,writable:true,
   });
   else bars[33].time=BASE+39*H;
   return original;
  }});
  for(let index=33;index<bars.length;index++){
   for(const field of ['open','high','low','close','volume','observed_minutes'])
    Object.defineProperty(bars[index],field,{get(){
     throw Error('future '+field+' must remain unread');
    }});
  }
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,cutoff),
   /FVG as-of timestamp field changed during declaration snapshot/);
 }
 const stable=fixture();
 Object.defineProperty(stable[34],'time',{get(){return BASE+34*H;}});
 assert.deepEqual(studyHourlyFvgMidpointAsOf(stable,source,cutoff),baseline);
});

test('v79 matched net-cost signs reconcile by first-touch wait and strict evidence without future exits',()=>{
 const mirror=(rows:Bar[])=>rows.map(b=>({...b,
  open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close}));
 const delayed=fixture();
 delayed[33]=candle(33,105,106,103,105);
 delayed[34]=candle(34,105,106,101,105.5,200);
 delayed[35]=candle(35,105.5,107,105,106);
 delayed[36]=candle(36,106,108,105,107);
 delayed[37]=candle(37,107,111,106,110);
 const failed=fixture();
 failed[33]=candle(33,105,106,101,102.5,200);
 const samples=[
  {bars:fixture(),src:source},
  {bars:fixture().slice(0,35),src:source},
  {bars:failed,src:source},
  {bars:fixture(),src:{...source,volumeVerified:false}},
  {bars:delayed,src:source},
  {bars:mirror(delayed),src:source},
 ];
 const statuses=['PASS','FAIL','INSUFFICIENT_DATA'] as const;
 const check=(report:ReturnType<typeof studyHourlyFvgMidpoint>)=>{
  const n=report.config.maxTouchWaitBars;
  for(const [scenarioIndex,scenario] of report.cohort.pairedNetSignByCost.entries()){
   const emptyWait=()=>Array.from({length:n},()=>({
    bothPositive:0,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0,
   }));
   const expected={PASS:emptyWait(),FAIL:emptyWait(),INSUFFICIENT_DATA:emptyWait()};
   for(const o of report.observations){
    if(o.blindMidpointTouch===null||o.confirmedNextOpen===null)continue;
    assert.equal(o.firstTouchOutcome,'TOUCH');
    const wait=o.firstTouchObservedWaitBars-1;
    assert.ok(wait>=0&&wait<n);
    const blind=o.blindMidpointTouch.netBpsByCost[scenarioIndex].netBps>0;
    const confirmed=o.confirmedNextOpen.netBpsByCost[scenarioIndex].netBps>0;
    const cell=blind?(confirmed?'bothPositive':'blindOnlyPositive'):
     (confirmed?'confirmedOnlyPositive':'neitherPositive');
    expected[o.gates.strictCandidate][wait][cell]++;
   }
   assert.deepEqual(scenario.byFirstTouchWaitAndStrictCandidate,expected);
   for(const status of statuses)for(let wait=0;wait<n;wait++){
    const cells:Record<'bothPositive'|'blindOnlyPositive'|
     'confirmedOnlyPositive'|'neitherPositive',number>=
     scenario.byFirstTouchWaitAndStrictCandidate[status][wait];
    assert.equal(Object.values(cells).reduce((sum,count)=>sum+count,0),
     report.cohort.firstTouchPairedByWaitAndStrictCandidate[status][wait]);
   }
  }
 };
 for(const {bars,src} of samples){
  const config={hypotheticalRoundTripCostsBps:[0,5,15,120]};
  const full=studyHourlyFvgMidpoint(bars,src,config);
  check(full);
  const asOf=studyHourlyFvgMidpointAsOf(bars,src,
   bars[bars.length-1].time+H,config);
  check(asOf);
  assert.deepEqual(asOf,full);
 }
 const before=studyHourlyFvgMidpointAsOf(delayed,source,BASE+37*H);
 const after=studyHourlyFvgMidpointAsOf(delayed,source,BASE+38*H);
 check(before);check(after);
 for(const scenario of before.cohort.pairedNetSignByCost)
  assert.equal(Object.values(scenario.byFirstTouchWaitAndStrictCandidate)
   .flat().flatMap(cells=>Object.values(cells))
   .reduce((sum,n)=>sum+n,0),0);
 assert.equal(after.cohort.pairedNetSignByCost[0]
  .byFirstTouchWaitAndStrictCandidate.PASS[1].bothPositive,1);
 const bullish=studyHourlyFvgMidpoint(fixture(),source);
 const bearish=studyHourlyFvgMidpoint(mirror(fixture()),source);
 assert.equal(bullish.cohort.pairedNetSignByCost[0]
  .byFirstTouchWaitAndStrictCandidate.PASS[0].bothPositive,1);
 assert.equal(bearish.cohort.pairedNetSignByCost[0]
  .byFirstTouchWaitAndStrictCandidate.PASS[0].bothPositive,1);
});


test('v80 cost-sign census independently reconciles direction, touch wait and strict evidence',()=>{
 const mirror=(rows:Bar[])=>rows.map(b=>({...b,
  open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close}));
 const delayed=fixture();
 delayed[33]=candle(33,105,106,103,105);
 delayed[34]=candle(34,105,106,101,105.5,200);
 delayed[35]=candle(35,105.5,107,105,106);
 delayed[36]=candle(36,106,108,105,107);
 delayed[37]=candle(37,107,111,106,110);
 const failed=fixture();
 failed[33]=candle(33,105,106,101,102.5,200);
 const first=fixture();
 const mixed=[...first,...mirror(first).map(b=>({...b,time:b.time+first.length*H}))];
 const samples=[fixture(),mirror(fixture()),delayed,mirror(delayed),failed,mixed];
 const statuses=['PASS','FAIL','INSUFFICIENT_DATA'] as const;
 const sides=['BULLISH','BEARISH'] as const;
 const cells=['bothPositive','blindOnlyPositive','confirmedOnlyPositive','neitherPositive'] as const;
 const empty=()=>({bothPositive:0,blindOnlyPositive:0,
  confirmedOnlyPositive:0,neitherPositive:0});
 const emptyStatus=(n:number)=>({
  PASS:Array.from({length:n},empty),FAIL:Array.from({length:n},empty),
  INSUFFICIENT_DATA:Array.from({length:n},empty),
 });
 const config={hypotheticalRoundTripCostsBps:[0,5,15,120]};
 for(const bars of samples)for(const verified of [true,false]){
  const declared={...source,volumeVerified:verified};
  const cutoffs=[null,BASE+37*H,bars[bars.length-1].time+H];
  for(const cutoff of cutoffs){
   const report=cutoff===null?studyHourlyFvgMidpoint(bars,declared,config):
    studyHourlyFvgMidpointAsOf(bars,declared,cutoff,config);
   const n=report.config.maxTouchWaitBars;
   for(const [index,scenario] of report.cohort.pairedNetSignByCost.entries()){
    const expected={BULLISH:emptyStatus(n),BEARISH:emptyStatus(n)};
    for(const o of report.observations){
     if(!o.blindMidpointTouch||!o.confirmedNextOpen)continue;
     assert.equal(o.firstTouchOutcome,'TOUCH');
     const wait=o.firstTouchObservedWaitBars-1;
     assert.ok(wait>=0&&wait<n);
     const blind=o.blindMidpointTouch.netBpsByCost[index].netBps>0;
     const confirmed=o.confirmedNextOpen.netBpsByCost[index].netBps>0;
     const cell=blind?(confirmed?'bothPositive':'blindOnlyPositive'):
      (confirmed?'confirmedOnlyPositive':'neitherPositive');
     expected[o.direction][o.gates.strictCandidate][wait][cell]++;
    }
    assert.deepEqual(scenario.byDirectionAndFirstTouchWaitAndStrictCandidate,expected);
    for(const status of statuses)for(let wait=0;wait<n;wait++){
     for(const cell of cells){
      assert.equal(scenario.byFirstTouchWaitAndStrictCandidate[status][wait][cell],
       expected.BULLISH[status][wait][cell]+expected.BEARISH[status][wait][cell]);
     }
     for(const side of sides){
      assert.equal(cells.reduce((sum,cell)=>sum+expected[side][status][wait][cell],0),
       report.cohort.firstTouchPairedByWaitAndStrictCandidateByDirection[side][status][wait]);
     }
    }
   }
  }
 }
 // No matured fixed exit at the early cutoff: no positive/negative imputation.
 const early=studyHourlyFvgMidpointAsOf(delayed,source,BASE+37*H,config);
 for(const scenario of early.cohort.pairedNetSignByCost)
  assert.equal(sides.flatMap(side=>statuses.flatMap(status=>
   scenario.byDirectionAndFirstTouchWaitAndStrictCandidate[side][status]))
   .flatMap(c=>cells.map(cell=>c[cell])).reduce((sum,n)=>sum+n,0),0);
});

// Gaps disqualify observed formation triplets; missing hours are never
// invented as negative FVGs or losing hypothetical trades.
test('v81 formation triplet gap attrition reconciles for complete and causal windows',()=>{
 const intact=fixture(),missing=intact.filter(b=>b.time!==BASE+17*H);
 const independent=(bars:Bar[])=>{
  let complete=0;
  for(let i=2;i<bars.length;i++)if(
   bars[i-1].time-bars[i-2].time===H&&bars[i].time-bars[i-1].time===H
  )complete++;
  return {observed:Math.max(0,bars.length-2),complete};
 };
 for(const bars of [[],[candle(0)],[candle(0),candle(1)],
  [candle(0),candle(2),candle(4)],intact,missing]){
  const report=studyHourlyFvgMidpoint(bars,source),expected=independent(bars);
  assert.equal(report.coverage.observedThreeBarWindows,expected.observed);
  assert.equal(report.coverage.completeThreeBarWindows,expected.complete);
  assert.equal(report.coverage.skippedThreeBarWindowsWithGaps,
   expected.observed-expected.complete);
  assert.ok(report.cohort.formations<=expected.complete);
 }
 assert.equal(studyHourlyFvgMidpoint(intact,source).coverage.skippedThreeBarWindowsWithGaps,0);
 assert.equal(studyHourlyFvgMidpoint(missing,source).coverage.skippedThreeBarWindowsWithGaps,2);
 const cutoffBefore=BASE+16*H,cutoffAfter=BASE+25*H;
 assert.equal(studyHourlyFvgMidpointAsOf(missing,source,cutoffBefore)
  .coverage.skippedThreeBarWindowsWithGaps,0);
 const protectedFuture=missing.map(b=>({...b}));
 for(const bar of protectedFuture)if(bar.time+H>cutoffAfter)
  for(const field of ['open','high','low','close','volume','observed_minutes'])
   Object.defineProperty(bar,field,{get(){throw Error('future '+field+' read');}});
 const asOf=studyHourlyFvgMidpointAsOf(protectedFuture,source,cutoffAfter);
 assert.deepEqual(asOf,studyHourlyFvgMidpoint(missing.filter(b=>b.time+H<=cutoffAfter),source));
 assert.equal(asOf.coverage.skippedThreeBarWindowsWithGaps,2);
 assert.equal(asOf.coverage.completeThreeBarWindows,20);
});

// Gap-edge populations are observed coverage only, not imputed market hours.
test('v82 one/two gap-edge triplet census is causal and reconciles',()=>{
 const intact=fixture();
 const doubleGap=intact.filter(b=>b.time!==BASE+17*H&&b.time!==BASE+19*H);
 const samples:Bar[][]=[[],[candle(0)],[candle(0),candle(2)],
  [candle(0),candle(2),candle(4)],[candle(0),candle(2),candle(3)],
  [candle(0),candle(1),candle(3),candle(5),candle(6)],intact,doubleGap];
 const independently=(bars:Bar[])=>{
  const cells=[0,0,0];
  for(let i=2;i<bars.length;i++){
   const edges=(bars[i-1].time-bars[i-2].time!==H?1:0)+
    (bars[i].time-bars[i-1].time!==H?1:0);
   cells[edges]++;
  }
  return cells;
 };
 for(const bars of samples){
  const c=studyHourlyFvgMidpoint(bars,source).coverage;
  const [complete,one,two]=independently(bars);
  assert.equal(c.completeThreeBarWindows,complete);
  assert.equal(c.skippedThreeBarWindowsWithOneGapEdge,one);
  assert.equal(c.skippedThreeBarWindowsWithTwoGapEdges,two);
  assert.equal(c.skippedThreeBarWindowsWithGaps,one+two);
  assert.equal(c.observedThreeBarWindows,complete+one+two);
 }
 assert.equal(studyHourlyFvgMidpoint(doubleGap,source).coverage
  .skippedThreeBarWindowsWithTwoGapEdges,1);
 const cutoff=BASE+25*H;
 const protectedFuture=doubleGap.map(b=>({...b}));
 for(const bar of protectedFuture)if(bar.time+H>cutoff)
  for(const field of ['open','high','low','close','volume','observed_minutes'])
   Object.defineProperty(bar,field,{get(){throw Error('future '+field+' read');}});
 const asOf=studyHourlyFvgMidpointAsOf(protectedFuture,source,cutoff);
 assert.deepEqual(asOf,studyHourlyFvgMidpoint(doubleGap.filter(b=>b.time+H<=cutoff),source));
 assert.equal(asOf.coverage.skippedThreeBarWindowsWithTwoGapEdges,1);
});


// Distinguish isolated missing hours from longer unclassified gaps without
// asserting a weekend, an exchange session or a market-data outage.
test('v83 gap severity census is causal and never reads future prices',()=>{
 const bars=[candle(0),candle(2),candle(3),candle(7),candle(8),candle(11)];
 const full=studyHourlyFvgMidpoint(bars,source).coverage;
 assert.equal(full.observedBars,6);
 assert.equal(full.unobservedHourSlots,6);
 assert.equal(full.gapIntervals,3);
 assert.equal(full.singleMissingHourGapIntervals,1);
 assert.equal(full.multiMissingHourGapIntervals,2);
 assert.equal(full.longestUnobservedHourRun,3);
 assert.equal(full.singleMissingHourGapIntervals+full.multiMissingHourGapIntervals,
  full.gapIntervals);
 const noGaps=studyHourlyFvgMidpoint([candle(0),candle(1),candle(2)],source).coverage;
 assert.equal(noGaps.gapIntervals,0);
 assert.equal(noGaps.longestUnobservedHourRun,0);
 const protectedFuture=bars.map(b=>({...b}));
 const cutoff=BASE+9*H;
 for(const bar of protectedFuture)if(bar.time+H>cutoff)
  for(const field of ['open','high','low','close','volume','observed_minutes'])
   Object.defineProperty(bar,field,{get(){throw Error('future '+field+' read');}});
 const early=studyHourlyFvgMidpointAsOf(protectedFuture,source,BASE+4*H);
 assert.equal(early.coverage.singleMissingHourGapIntervals,1);
 assert.equal(early.coverage.multiMissingHourGapIntervals,0);
 assert.equal(early.coverage.longestUnobservedHourRun,1);
 const asOf=studyHourlyFvgMidpointAsOf(protectedFuture,source,cutoff);
 assert.deepEqual(asOf,studyHourlyFvgMidpoint(bars.filter(b=>b.time+H<=cutoff),source));
 assert.equal(asOf.coverage.unobservedHourSlots,4);
 assert.equal(asOf.coverage.singleMissingHourGapIntervals,1);
 assert.equal(asOf.coverage.multiMissingHourGapIntervals,1);
 assert.equal(asOf.coverage.longestUnobservedHourRun,3);
});


// Per-candidate censor severity is not an archive-wide outage census.
test('v84 candidate-specific first-touch and exit gap severity is causal',()=>{
 const intact=fixture();
 const cases:[Bar[], 'firstTouch'|'markout', number][]=[
  [intact.filter(b=>b.time!==BASE+33*H),'firstTouch',1],
  [intact.filter(b=>b.time!==BASE+33*H&&b.time!==BASE+34*H),'firstTouch',2],
  [intact.filter(b=>b.time!==BASE+35*H),'markout',1],
  [intact.filter(b=>b.time!==BASE+34*H&&b.time!==BASE+35*H),'markout',2],
 ];
 for(const [bars,phase,missingSlots] of cases){
  const report=studyHourlyFvgMidpoint(bars,source);
  const observation=target(bars);
  const first=phase==='firstTouch';
  assert.equal(first?observation.firstTouchCensorReason:observation.markoutCensorReason,
   'MISSING_HOUR');
  assert.equal(first?observation.firstTouchCensorMissingHourSlots:
   observation.markoutCensorMissingHourSlots,missingSlots);
  assert.equal(first?observation.markoutCensorMissingHourSlots:
   observation.firstTouchCensorMissingHourSlots,null);
  const severity=first?report.cohort.firstTouchMissingHourSeverity:
   report.cohort.markoutMissingHourSeverity;
  const population=first?report.cohort.incompleteWindowByReason.MISSING_HOUR:
   report.cohort.markoutCensoredByReason.MISSING_HOUR;
  assert.equal(severity.single+severity.multiple,population);
  const missing=report.observations.map(o=>first?o.firstTouchCensorMissingHourSlots:
   o.markoutCensorMissingHourSlots).filter((n):n is number=>n!==null);
  assert.equal(severity.unobservedSlots,missing.reduce((sum,n)=>sum+n,0));
  assert.equal(severity.single,missing.filter(n=>n===1).length);
  assert.equal(severity.multiple,missing.filter(n=>n>1).length);
  assert.equal(observation.gates.markout,'INSUFFICIENT_DATA');
 }
 const intactObservation=target(intact);
 assert.equal(intactObservation.firstTouchCensorMissingHourSlots,null);
 assert.equal(intactObservation.markoutCensorMissingHourSlots,null);
 const tail=target(intact.slice(0,33));
 assert.equal(tail.firstTouchCensorReason,'RIGHT_CENSORED');
 assert.equal(tail.firstTouchCensorMissingHourSlots,null);
 const exitTail=target(intact.slice(0,35));
 assert.equal(exitTail.markoutCensorReason,'RIGHT_CENSORED');
 assert.equal(exitTail.markoutCensorMissingHourSlots,null);
 const firstMulti=cases[1][0],protectedFuture=firstMulti.map(b=>({...b}));
 const before=studyHourlyFvgMidpointAsOf(protectedFuture,source,BASE+35*H);
 const notYet=before.observations.find(o=>o.formationClosedAt===BASE+33*H);
 assert.ok(notYet);
 assert.equal(notYet.firstTouchCensorReason,'RIGHT_CENSORED');
 assert.equal(notYet.firstTouchCensorMissingHourSlots,null);
 const cutoff=BASE+36*H;
 for(const b of protectedFuture)if(b.time+H>cutoff)
  for(const field of ['open','high','low','close','volume','observed_minutes'])
   Object.defineProperty(b,field,{get(){throw Error('future '+field+' read');}});
 const asOf=studyHourlyFvgMidpointAsOf(protectedFuture,source,cutoff);
 assert.deepEqual(asOf,studyHourlyFvgMidpoint(firstMulti.filter(b=>b.time+H<=cutoff),source));
 const censored=asOf.observations.find(o=>o.formationClosedAt===BASE+33*H);
 assert.ok(censored);
 assert.equal(censored.firstTouchCensorMissingHourSlots,2);
 assert.equal(censored.firstTouchCensorObservedAt,cutoff);
});

test('v85 candle getters cannot rewrite preflighted source, settings or costs',()=>{
 const provenance={...source},provenanceBars=fixture();
 Object.defineProperty(provenanceBars[0],'open',{configurable:true,enumerable:true,
  get(){provenance.volumeVerified=false;return 100;}});
 assert.throws(()=>studyHourlyFvgMidpoint(provenanceBars,provenance),
  /FVG source declaration field changed during declaration snapshot/);
 const settings:FvgConfig={maxTouchWaitBars:12},settingBars=fixture();
 Object.defineProperty(settingBars[0],'close',{configurable:true,enumerable:true,
  get(){settings.maxTouchWaitBars=1;return 100;}});
 assert.throws(()=>studyHourlyFvgMidpoint(settingBars,source,settings),
  /FVG study setting field changed during declaration snapshot/);
 const costs=[0,5,15],costBars=fixture();
 Object.defineProperty(costBars[0],'volume',{configurable:true,enumerable:true,
  get(){costs[0]=1;return 100;}});
 assert.throws(()=>studyHourlyFvgMidpoint(costBars,source,{
  hypotheticalRoundTripCostsBps:costs,
 }),/FVG cost scenario field changed during declaration snapshot/);
 assert.equal(studyHourlyFvgMidpoint(fixture(),source).version,
  'hourly-fvg-first-midpoint-touch-v92');
});

test('v85 future timestamp accessors cannot rewrite as-of provenance or cost axis',()=>{
 const cutoff=BASE+37*H,provenance={...source},future=fixture();
 Object.defineProperty(future[39],'time',{configurable:true,enumerable:true,
  get(){provenance.volumeVerified=false;return BASE+39*H;}});
 Object.defineProperty(future[39],'volume',{configurable:true,enumerable:true,
  get(){throw Error('Future volume must never be inspected');}});
 assert.throws(()=>studyHourlyFvgMidpointAsOf(future,provenance,cutoff),
  /FVG source declaration field changed during declaration snapshot/);
 const settings:FvgConfig={maxTouchWaitBars:12},futureSettings=fixture();
 Object.defineProperty(futureSettings[39],'time',{configurable:true,enumerable:true,
  get(){settings.maxTouchWaitBars=1;return BASE+39*H;}});
 assert.throws(()=>studyHourlyFvgMidpointAsOf(futureSettings,source,cutoff,settings),
  /FVG study setting field changed during declaration snapshot/);
 const costs=[0,5,15],futureCosts=fixture();
 Object.defineProperty(futureCosts[39],'time',{configurable:true,enumerable:true,
  get(){costs[0]=1;return BASE+39*H;}});
 assert.throws(()=>studyHourlyFvgMidpointAsOf(futureCosts,source,cutoff,{
  hypotheticalRoundTripCostsBps:costs,
 }),/FVG cost scenario field changed during declaration snapshot/);
 assert.deepEqual(studyHourlyFvgMidpointAsOf(fixture(),source,cutoff).observations,
  studyHourlyFvgMidpoint(fixture().slice(0,37),source).observations);
});

test('v86 formed-gap friction census includes censored bullish and bearish windows',()=>{
 const narrow=[
  candle(0,99.99,100,99.98,99.99),
  candle(1,100.02,100.03,100.01,100.02),
  candle(2,100.07,100.08,100.05,100.07),
 ];
 const costs=[0,1,5,15];
 for(const bearish of [false,true]){
  const bars=bearish?narrow.map(b=>({...b,open:220-b.open,
   high:220-b.low,low:220-b.high,close:220-b.close})):narrow;
  const report=studyHourlyFvgMidpoint(bars,source,{
   hypotheticalRoundTripCostsBps:costs,
  });
  assert.equal(report.observations.length,1);
  assert.equal(report.observations[0].firstTouchOutcome,'INCOMPLETE_WINDOW');
  assert.equal(report.cohort.pairedMarkouts,0);
  assert.deepEqual(report.formationGapNoWiderThanCostByScenario,
   costs.map((costBps,scenarioIndex)=>({
    scenarioIndex,costBps,all:costBps>=5?1:0,
    byDirection:{BULLISH:!bearish&&costBps>=5?1:0,
     BEARISH:bearish&&costBps>=5?1:0},
   })));
  const future=bars.concat(candle(3));
  Object.defineProperty(future[3],'high',{get(){throw Error('future price read');}});
  assert.deepEqual(studyHourlyFvgMidpointAsOf(future,source,BASE+3*H,{
   hypotheticalRoundTripCostsBps:costs,
  }),report);
 }
 const wide=studyHourlyFvgMidpoint(fixture(),source,{
  hypotheticalRoundTripCostsBps:[0,5,15,1000],
 });
 for(const scenario of wide.formationGapNoWiderThanCostByScenario){
  const expected=wide.observations.filter(o=>
   (o.gapHigh-o.gapLow)/o.midpoint*10000<=scenario.costBps);
  assert.equal(scenario.all,expected.length);
  assert.equal(scenario.all,scenario.byDirection.BULLISH+
   scenario.byDirection.BEARISH);
 }
});


test('v87 as-of cost-array getter is rejected before reading future timestamps',()=>{
 const rows=fixture(),cutoff=BASE+34*H;
 const costs=[0,5,15];
 let costGetterReads=0,futureTimeReads=0;
 const config=Object.defineProperty({},'hypotheticalRoundTripCostsBps',{
  configurable:true,enumerable:true,get(){
   costGetterReads++;return costs;
  },
 }) as FvgConfig;
 Object.defineProperty(rows[39],'time',{configurable:true,enumerable:true,
  get(){futureTimeReads++;costs[1]=900;return BASE+39*H;}});
 assert.throws(()=>studyHourlyFvgMidpointAsOf(rows,source,cutoff,config),
  /FVG as-of cost scenarios require an own data property/);
 assert.equal(costGetterReads,0,'unanchored cost getter is not invoked');
 assert.equal(futureTimeReads,0,'future timestamp getter is not invoked');
 assert.deepEqual(costs,[0,5,15],'rejected study leaves source costs untouched');
 // Full-history snapshots can still capture the cost getter once; as-of
 // demands a stable data-property array that it can recheck after scanning.
 const full=studyHourlyFvgMidpoint(fixture(),source,config);
 assert.deepEqual(full.config.hypotheticalRoundTripCostsBps,[0,5,15]);
 assert.equal(costGetterReads,1);
 assert.deepEqual(studyHourlyFvgMidpointAsOf(fixture(),source,cutoff,{
  hypotheticalRoundTripCostsBps:costs,
 }),studyHourlyFvgMidpointAsOf(fixture(),source,cutoff));
});

test('v88 first-touch censor bounds keep no-touch, gap-through and unknown formation denominators',()=>{
 const formation=[
  candle(0,99,100,98,99),candle(1,101,102,100,101),
  candle(2,105,106,104,105),
 ];
 const variants=[
  {name:'tail',post:null,outcome:'INCOMPLETE_WINDOW',formed:1,lower:0,upper:1},
  {name:'touch',post:candle(3,104,105,101,104),outcome:'TOUCH',formed:1,lower:1,upper:1},
  {name:'gap-through',post:candle(3,101,103,100,102),outcome:'OPEN_GAP_THROUGH',formed:1,lower:0,upper:1},
  {name:'missing-hour',post:candle(4,104,105,101,104),outcome:'INCOMPLETE_WINDOW',formed:1,lower:0,upper:1},
  {name:'no-touch',post:candle(3,105,106,104,105),outcome:'NO_TOUCH',formed:2,lower:0,upper:0.5},
 ] as const;
 const flip=(bar:Bar):Bar=>({...bar,open:220-bar.open,
  high:220-bar.low,low:220-bar.high,close:220-bar.close});
 for(const bearish of [false,true]){
  const side=bearish?'BEARISH':'BULLISH';
  const other=bearish?'BULLISH':'BEARISH';
  for(const sample of variants){
   const raw=sample.post?[...formation,sample.post]:formation;
   const bars=bearish?raw.map(flip):raw;
   const report=studyHourlyFvgMidpoint(bars,source,{maxTouchWaitBars:1});
   assert.equal(report.observations[0].firstTouchOutcome,sample.outcome,
    sample.name+' '+side);
   const bound=report.cohort.firstTouchOpportunityBounds;
   assert.equal(bound.all.formations,sample.formed,sample.name+' '+side);
   assert.equal(bound.all.lowerObservedTouchFraction,sample.lower);
   assert.equal(bound.all.upperPossibleTouchFraction,sample.upper);
   assert.deepEqual(bound.byDirection[side],bound.all);
   assert.deepEqual(bound.byDirection[other],{
    formations:0,observedTouches:0,observedNoTouches:0,
    unresolvedGapThrough:0,unresolvedIncomplete:0,
    lowerObservedTouchFraction:null,upperPossibleTouchFraction:null,
   });
   const counts=report.cohort.firstTouchOutcome;
   assert.equal(bound.all.observedTouches,counts.TOUCH);
   assert.equal(bound.all.observedNoTouches,counts.NO_TOUCH);
   assert.equal(bound.all.unresolvedGapThrough,counts.OPEN_GAP_THROUGH);
   assert.equal(bound.all.unresolvedIncomplete,counts.INCOMPLETE_WINDOW);
  }
 }
 const empty=studyHourlyFvgMidpoint([],source).cohort.firstTouchOpportunityBounds;
 assert.equal(empty.all.formations,0);
 assert.equal(empty.all.lowerObservedTouchFraction,null);
 assert.equal(empty.all.upperPossibleTouchFraction,null);
 // Causal replay cannot use the next bar's prices to reduce an unknown
 // upper bound before that hour has completed.
 const future=[...formation,candle(3,104,105,101,104)];
 Object.defineProperty(future[3],'high',{get(){throw Error('future high read');}});
 const asOf=studyHourlyFvgMidpointAsOf(future,source,BASE+3*H,{maxTouchWaitBars:1});
 assert.equal(asOf.cohort.firstTouchOpportunityBounds.all.lowerObservedTouchFraction,0);
 assert.equal(asOf.cohort.firstTouchOpportunityBounds.all.upperPossibleTouchFraction,1);
 assert.deepEqual(asOf,studyHourlyFvgMidpoint(formation,source,{maxTouchWaitBars:1}));
 const bull=[...formation,candle(3,104,105,101,104)];
 const bear=[...formation,candle(3,101,103,100,102)]
  .map(b=>({...flip(b),time:b.time+10*H}));
 const mixed=studyHourlyFvgMidpoint([...bull,...bear],source,{maxTouchWaitBars:1});
 assert.equal(mixed.cohort.firstTouchOpportunityBounds.all.formations,2);
 assert.equal(mixed.cohort.firstTouchOpportunityBounds.all.lowerObservedTouchFraction,0.5);
 assert.equal(mixed.cohort.firstTouchOpportunityBounds.all.upperPossibleTouchFraction,1);
 assert.equal(mixed.cohort.firstTouchOpportunityBounds.byDirection.BULLISH.observedTouches,1);
 assert.equal(mixed.cohort.firstTouchOpportunityBounds.byDirection.BEARISH.unresolvedGapThrough,1);
});

test('v89 cost-width first-touch bounds preserve censored and known-negative formations',()=>{
 const wide=[
  candle(0,99,100,98,99),candle(1,101,102,100,101),
  candle(2,105,106,104,105),candle(3,104,105,101,104),
 ];
 const narrow=[
  candle(10,99,100,98,99),candle(11,101,102,100,101),
  candle(12,101.5,102.5,101,101.5),candle(13,101.5,103,101,102),
 ];
 const censored=[
  candle(20,99,100,98,99),candle(21,101,102,100,101),
  candle(22,105,106,104,105),
 ];
 const bars=[...wide,...narrow,...censored];
 const config:FvgConfig={maxTouchWaitBars:1,hypotheticalRoundTripCostsBps:[0,200,600]};
 const report=studyHourlyFvgMidpoint(bars,source,config);
 assert.equal(report.observations.length,3);
 assert.deepEqual(report.observations.map(o=>o.firstTouchOutcome),
  ['TOUCH','NO_TOUCH','INCOMPLETE_WINDOW']);
 const census=report.firstTouchOpportunityBoundsByCostScenario;
 assert.equal(census.length,3);
 assert.deepEqual(census.map(s=>s.noWiderThanCost.formations),[0,1,3]);
 assert.deepEqual(census.map(s=>s.widerThanCost.formations),[3,2,0]);
 assert.deepEqual(census.map(s=>s.noWiderThanCost.lowerObservedTouchFraction),
  [null,0,1/3]);
 assert.deepEqual(census.map(s=>s.noWiderThanCost.upperPossibleTouchFraction),
  [null,0,2/3]);
 assert.deepEqual(census.map(s=>s.widerThanCost.lowerObservedTouchFraction),
  [1/3,1/2,null]);
 assert.deepEqual(census.map(s=>s.widerThanCost.upperPossibleTouchFraction),
  [2/3,1,null]);
 for(const s of census){
  assert.equal(s.noWiderThanCost.formations+s.widerThanCost.formations,
   report.cohort.formations);
  for(const key of ['observedTouches','observedNoTouches',
   'unresolvedGapThrough','unresolvedIncomplete'] as const)
   assert.equal(s.noWiderThanCost[key]+s.widerThanCost[key],
    report.cohort.firstTouchOpportunityBounds.all[key]);
 }
 const empty=studyHourlyFvgMidpoint([],source,config);
 for(const s of empty.firstTouchOpportunityBoundsByCostScenario){
  assert.equal(s.noWiderThanCost.lowerObservedTouchFraction,null);
  assert.equal(s.widerThanCost.upperPossibleTouchFraction,null);
 }
 // A future hourly candle cannot retrospectively turn the censored cohort
 // into an observed touch before that candle closes.
 const future=[...bars,candle(23,104,105,101,104)];
 Object.defineProperty(future[future.length-1],'low',{
  get(){throw Error('future low must not be inspected');},
 });
 const replay=studyHourlyFvgMidpointAsOf(future,source,BASE+23*H,config);
 assert.deepEqual(replay,report);
});

test('v90 cost-width touch censor bounds retain direction and missing evidence',()=>{
 const bullish=[
  candle(0,99,100,98,99),candle(1,101,102,100,101),
  candle(2,105,106,104,105),candle(3,104,105,101,104),
  candle(10,99,100,98,99),candle(11,101,102,100,101),
  candle(12,101.5,102.5,101,101.5),candle(13,101.5,103,101,102),
  candle(20,99,100,98,99),candle(21,101,102,100,101),
  candle(22,105,106,104,105),
 ];
 const bearish=bullish.map(b=>({...b,time:b.time+40*H,
  open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close}));
 const bars=[...bullish,...bearish];
 const config:FvgConfig={maxTouchWaitBars:1,hypotheticalRoundTripCostsBps:[0,200,600]};
 const report=studyHourlyFvgMidpoint(bars,source,config);
 assert.equal(report.observations.length,6);
 for(const side of ['BULLISH','BEARISH'] as const){
  const observations=report.observations.filter(o=>o.direction===side);
  assert.equal(observations.length,3);
  assert.deepEqual(observations.map(o=>o.firstTouchOutcome),
   ['TOUCH','NO_TOUCH','INCOMPLETE_WINDOW']);
 }
 for(const scenario of report.firstTouchOpportunityBoundsByCostScenario){
  for(const side of ['BULLISH','BEARISH'] as const){
   const sideObs=report.observations.filter(o=>o.direction===side);
   const groups=scenario.byDirection[side];
   for(const [name,pop] of [
    ['noWiderThanCost',groups.noWiderThanCost],
    ['widerThanCost',groups.widerThanCost],
   ] as const){
    const members=sideObs.filter(o=>{
     const narrow=(o.gapHigh-o.gapLow)*10000<=o.midpoint*scenario.costBps;
     return name==='noWiderThanCost'?narrow:!narrow;
    });
    assert.equal(pop.formations,members.length);
    for(const [field,outcome] of [
     ['observedTouches','TOUCH'],['observedNoTouches','NO_TOUCH'],
     ['unresolvedGapThrough','OPEN_GAP_THROUGH'],
     ['unresolvedIncomplete','INCOMPLETE_WINDOW'],
    ] as const)
     assert.equal(pop[field],members.filter(o=>o.firstTouchOutcome===outcome).length);
    assert.equal(pop.lowerObservedTouchFraction,
     members.length?pop.observedTouches/members.length:null);
    assert.equal(pop.upperPossibleTouchFraction,members.length?
     (pop.observedTouches+pop.unresolvedIncomplete+pop.unresolvedGapThrough)/members.length:null);
   }
   assert.equal(groups.noWiderThanCost.formations+groups.widerThanCost.formations,3);
  }
 }
 const future=[...bars,candle(63,100,101,99,100)];
 Object.defineProperty(future[future.length-1],'low',{get(){
  throw Error('future low must not be read');
 }});
 assert.deepEqual(studyHourlyFvgMidpointAsOf(future,source,BASE+63*H,config),report);
 const empty=studyHourlyFvgMidpoint([],source,config);
 for(const scenario of empty.firstTouchOpportunityBoundsByCostScenario)
  for(const side of ['BULLISH','BEARISH'] as const)
   assert.equal(scenario.byDirection[side].noWiderThanCost.lowerObservedTouchFraction,null);
});


test('v91 cost-width strict first-touch evidence keeps unknown volume separate from failures',()=>{
 // Isolate one known FVG per block; the generic fixture contains
 // additional legitimate formations which would bias this test's census.
 const template=Array.from({length:40},(_,i)=>
  i>=34?candle(i,105,106,104,105):candle(i,100,101,99,100));
 template[30]=candle(30,99,100,98,99);
 template[31]=candle(31,100,102,99,101);
 template[32]=candle(32,105,106,104,105);
 template[33]=candle(33,105,106,101,105.5,200);
 const pass=template;
 const fail=template.map((b,i)=>({...b,time:b.time+50*H,
  volume:i===33?100:b.volume}));
 const unknown=template.map((b,i)=>({...b,time:b.time+100*H,
  open:220-b.open,high:220-b.low,low:220-b.high,close:220-b.close,
  volume:i===33?null:b.volume}));
 const bars=[...pass,...fail,...unknown];
 const config:FvgConfig={hypotheticalRoundTripCostsBps:[0,1000]};
 const report=studyHourlyFvgMidpoint(bars,source,config);
 assert.equal(report.observations.length,3);
 assert.deepEqual(report.observations.map(o=>o.gates.strictCandidate),
  ['PASS','FAIL','INSUFFICIENT_DATA']);
 for(const [index,scenario] of report.firstTouchOpportunityBoundsByCostScenario.entries()){
  const census=scenario.strictObservedTouchEvidenceByCostWidth;
  const selected=index===0?census.widerThanCost:census.noWiderThanCost;
  const empty=index===0?census.noWiderThanCost:census.widerThanCost;
  assert.deepEqual(selected,{PASS:1,FAIL:1,INSUFFICIENT_DATA:1});
  assert.deepEqual(empty,{PASS:0,FAIL:0,INSUFFICIENT_DATA:0});
  const side=index===0?'widerThanCost':'noWiderThanCost';
  assert.deepEqual(census.byDirection.BULLISH[side],
   {PASS:1,FAIL:1,INSUFFICIENT_DATA:0});
  assert.deepEqual(census.byDirection.BEARISH[side],
   {PASS:0,FAIL:0,INSUFFICIENT_DATA:1});
 }
 // Before the third touch closes, future price/volume are inaccessible and
 // the unfinished waiting window is not a strict observed touch.
 const cutoff=BASE+133*H;
 const future=bars.map(b=>({...b}));
 const futureTouch=future.find(b=>b.time===BASE+133*H);
 assert.ok(futureTouch);
 Object.defineProperty(futureTouch,'low',{get(){throw Error('future price read');}});
 const asOf=studyHourlyFvgMidpointAsOf(future,source,cutoff,config);
 const prefix=bars.filter(b=>b.time+H<=cutoff);
 assert.deepEqual(asOf,studyHourlyFvgMidpoint(prefix,source,config));
 for(const scenario of asOf.firstTouchOpportunityBoundsByCostScenario){
  const census=scenario.strictObservedTouchEvidenceByCostWidth;
  const all=['PASS','FAIL','INSUFFICIENT_DATA'] as const;
  assert.equal(all.reduce((sum,status)=>sum+
   census.noWiderThanCost[status]+census.widerThanCost[status],0),2);
 }
});

test('v92 cost-width volume reasons preserve prior-20 gaps, missing data and unverified sources',()=>{
 const template=Array.from({length:40},(_,i)=>
  i>=34?candle(i,105,106,104,105):candle(i,100,101,99,100));
 template[30]=candle(30,99,100,98,99);
 template[31]=candle(31,100,102,99,101);
 template[32]=candle(32,105,106,104,105);
 template[33]=candle(33,105,106,101,105.5,200);
 const variants:{
  reason:string;bars:Bar[];declaredSource:FvgSource;
 }[]=[
  {reason:'THRESHOLD_EXCEEDED',bars:template,declaredSource:source},
  {reason:'THRESHOLD_NOT_MET',bars:template.map((b,i)=>
   i===33?{...b,volume:100}:b),declaredSource:source},
  {reason:'MISSING_OR_NONPOSITIVE_VOLUME',bars:template.map((b,i)=>
   i===33?{...b,volume:null}:b),declaredSource:source},
  {reason:'SOURCE_UNVERIFIED',bars:template,declaredSource:{
   ...source,volumeVerified:false,volumeType:'unverified'}},
  {reason:'PRIOR20_GAP',bars:template.filter(b=>b.time!==BASE+20*H),
   declaredSource:source},
  {reason:'PRIOR20_UNAVAILABLE',bars:template.slice(20),declaredSource:source},
 ];
 const reasons=['NOT_EVALUATED','SOURCE_UNVERIFIED','PRIOR20_UNAVAILABLE',
  'PRIOR20_GAP','MISSING_OR_NONPOSITIVE_VOLUME',
  'THRESHOLD_NOT_MET','THRESHOLD_EXCEEDED'] as const;
 for(const {reason,bars,declaredSource} of variants){
  const report=studyHourlyFvgMidpoint(bars,declaredSource,{
   hypotheticalRoundTripCostsBps:[0,1000],
  });
  assert.equal(report.observations.length,1,reason);
  assert.equal(report.observations[0].firstTouchOutcome,'TOUCH',reason);
  assert.equal(report.observations[0].volumeEvidenceReason,reason);
  for(const [index,scenario] of report.firstTouchOpportunityBoundsByCostScenario.entries()){
   const census=scenario.observedTouchVolumeReasonsByCostWidth;
   const selected=index===0?'widerThanCost':'noWiderThanCost';
   const other=index===0?'noWiderThanCost':'widerThanCost';
   for(const key of reasons){
    assert.equal(census[selected][key],key===reason?1:0);
    assert.equal(census[other][key],0);
    assert.equal(census.byDirection.BULLISH[selected][key],key===reason?1:0);
    assert.equal(census.byDirection.BEARISH[selected][key],0);
   }
   assert.equal(census[selected].NOT_EVALUATED,0);
  }
 }
 // A future unclosed touch cannot contribute a volume-reason observation.
 const protectedBars=template.map(b=>({...b}));
 Object.defineProperty(protectedBars[33],'volume',{
  get(){throw Error('future volume must not be read');},
 });
 const asOf=studyHourlyFvgMidpointAsOf(protectedBars,source,BASE+33*H,{
  hypotheticalRoundTripCostsBps:[0,1000],
 });
 assert.deepEqual(asOf,studyHourlyFvgMidpoint(template.slice(0,33),source,{
  hypotheticalRoundTripCostsBps:[0,1000],
 }));
 for(const scenario of asOf.firstTouchOpportunityBoundsByCostScenario)
  assert.equal(scenario.observedTouchVolumeReasonsByCostWidth.widerThanCost.NOT_EVALUATED,0);
});
