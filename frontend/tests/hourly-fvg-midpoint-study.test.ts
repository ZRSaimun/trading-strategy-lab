import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpoint,type FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
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
 assert.equal(report.version,'hourly-fvg-first-midpoint-touch-v16');
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
 assert.equal(x.blindMidpointTouch,null);
 assert.equal(x.confirmedNextOpen,null);
});
test('completed hourly timestamps are safe and numeric rule changes have a new version',()=>{
 const report=studyHourlyFvgMidpoint(fixture(),source);
 assert.equal(report.version,'hourly-fvg-first-midpoint-touch-v16');
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
