import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpoint,studyHourlyFvgMidpointAsOf,type FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
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
  incompleteWindowByReason:{MISSING_HOUR:0,RIGHT_CENSORED:0},
  markoutCensoredByReason:{MISSING_HOUR:0,RIGHT_CENSORED:0,UNREPRESENTABLE_RETURN:0},
  pairedGrossOrdering:{
   all:{confirmedHigher:0,blindHigher:1,equal:0},
   strict:{confirmedHigher:0,blindHigher:0,equal:0},
   strictFail:{confirmedHigher:0,blindHigher:0,equal:0},
   strictUnknown:{confirmedHigher:0,blindHigher:1,equal:0},
  },
  pairedNetSignByCost:[0,5,15].map((costBps,scenarioIndex)=>({
   scenarioIndex,costBps,
   all:{bothPositive:1,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0},
   strict:{bothPositive:0,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0},
   strictFail:{bothPositive:0,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0},
   strictUnknown:{bothPositive:1,blindOnlyPositive:0,confirmedOnlyPositive:0,neitherPositive:0},
  })),
  midpointTouch:{PASS:1,FAIL:0,INSUFFICIENT_DATA:0},
  strictCandidate:{PASS:0,FAIL:0,INSUFFICIENT_DATA:1},
  markout:{PASS:1,FAIL:0,INSUFFICIENT_DATA:0},
  pairedMarkouts:1,strictPairedMarkouts:0,nonStrictPairedMarkouts:1,
  pairedByStrictCandidate:{PASS:0,FAIL:0,INSUFFICIENT_DATA:1},
  unpairedByStrictCandidate:{PASS:0,FAIL:0,INSUFFICIENT_DATA:0},
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
test('research report source metadata excludes arbitrary caller properties',()=>{
 // TypeScript structural typing does not remove runtime fields. A caller
 // may pass a richer vendor object; its extra data must never be exported.
 const richerSource={...source,debugAccessToken:'synthetic-private-marker',
  rawVendorPayload:{account:'synthetic-account-marker'}};
 const report=studyHourlyFvgMidpoint(fixture(),richerSource);
 assert.deepEqual(report.source,source);
 assert.deepEqual(Object.keys(report.source).sort(),Object.keys(source).sort());
 assert.equal(JSON.stringify(report).includes('synthetic-private-marker'),false);
 assert.equal(JSON.stringify(report).includes('synthetic-account-marker'),false);
 assert.equal(report.version,'hourly-fvg-first-midpoint-touch-v33');
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
 assert.equal(report.version,'hourly-fvg-first-midpoint-touch-v33');
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
 });
 const before=studyHourlyFvgMidpointAsOf(bars,source,BASE+20*H);
 assert.deepEqual(before.coverage,{
  firstBarOpenAt:BASE,lastBarClosedAt:BASE+20*H,
  observedBars:20,unobservedHourSlots:0,gapIntervals:0,
 });
 const after=studyHourlyFvgMidpointAsOf(bars,source,BASE+24*H);
 assert.deepEqual(after.coverage,{
  firstBarOpenAt:BASE,lastBarClosedAt:BASE+24*H,
  observedBars:22,unobservedHourSlots:2,gapIntervals:1,
 });
 const empty=studyHourlyFvgMidpointAsOf(bars,source,H);
 assert.deepEqual(empty.coverage,{
  firstBarOpenAt:null,lastBarClosedAt:null,
  observedBars:0,unobservedHourSlots:0,gapIntervals:0,
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
