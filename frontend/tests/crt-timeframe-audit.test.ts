import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditCrtCrossTimeframe,certifiedCrtFourHourBars} from '../lib/crt-timeframe-audit.ts';
import {screenCrtHypotheses} from '../lib/crt-quant-filters.ts';
import type {Bar} from '../lib/research.ts';

const BASE=Date.UTC(2026,9,20)/1000, Q=900, H4=14400;
const candle=(time:number,open=100,high=101,low=99,close=100,mins=15):Bar=>({
 time,open,high,low,close,volume:null,observed_minutes:mins,
});
function fixture(){
 const q=Array.from({length:32},(_,i)=>candle(BASE+i*Q));
 q[0].open=100.5;q[4].high=103;q[7].low=97;q[15].close=100.25;
 q[16].open=100.25;q[19].high=104;q[24].low=95;q[31].close=100.75;
 const h=[
  candle(BASE,100.5,103,97,100.25,240),
  candle(BASE+H4,100.25,104,95,100.75,240),
 ];
 return {h,q};
}
test('validates two complete adjacent 4H bars against exactly 16 observed 15m bars each',()=>{
 const {h,q}=fixture();
 assert.deepEqual(auditCrtCrossTimeframe(h,q),
  {checkedFourHourBars:2,uncheckableFourHourBars:0,
   verifiedFourHourStarts:[BASE,BASE+H4],reconciledNumericVolumeStarts:[]});
});
test('fails closed when source-identical timeframe response has inconsistent OHLC',()=>{
 for(const field of ['open','high','low','close'] as const){
  const {h,q}=fixture();h[0][field]+=0.01;
  assert.throws(()=>auditCrtCrossTimeframe(h,q),/OHLC mismatch/);
 }
});
test('source-identical 4H and 15m OHLC must match exactly at tiny and large nominal scales',()=>{
 // The old max(1, nominal price) epsilon accepted a 5e-11 difference at
 // micro-prices and a full 0.01 difference near 1e9. Both are source
 // inconsistencies, regardless of unknown instrument tick size.
 for(const {scale,drift} of [
  {scale:1e-8,drift:5e-11},
  {scale:1e7,drift:0.01},
 ]){
  const {h,q}=fixture();
  for(const b of [...h,...q]){
   b.open*=scale;b.high*=scale;b.low*=scale;b.close*=scale;
  }
  assert.equal(auditCrtCrossTimeframe(h,q).checkedFourHourBars,2);
  h[0].high+=drift;
  assert.throws(()=>auditCrtCrossTimeframe(h,q),/OHLC mismatch/,
   'same-archive mismatch must never be masked by a nominal-price epsilon');
 }
});

test('fully reported 4H volume must equal the sixteen observed 15m volumes',()=>{
 const {h,q}=fixture();
 q.forEach((b,i)=>{b.volume=i%2===0?2.25:10.5;});
 h.forEach((b,i)=>{
  b.volume=q.slice(i*16,(i+1)*16).reduce((sum,v)=>sum+(v.volume??0),0);
 });
 assert.equal(auditCrtCrossTimeframe(h,q).checkedFourHourBars,2);
 // Price aggregates still agree: inconsistent numeric volume must not be
 // silently accepted as the same source's complete 4H observation.
 h[0].volume!+=1;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/);
});
test('integer 15m volume counts must match exactly even at large scales',()=>{
 // The old 64-ULP relative tolerance accepted a one-count discrepancy
 // near 1e14 despite every constituent being an exact integer count.
 const {h,q}=fixture();
 q.forEach(b=>{b.volume=6_250_000_000_000;});
 h.forEach(b=>{b.volume=100_000_000_000_000;});
 assert.equal(auditCrtCrossTimeframe(h,q).checkedFourHourBars,2);
 h[0].volume=100_000_000_000_001;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/);
 h[0].volume=100_000_000_000_000.5;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'fractional aggregate cannot certify sixteen exact integer counts');
});
test('integer count sums exceeding safe numeric precision cannot be certified',()=>{
 const {h,q}=fixture();
 q.forEach(b=>{b.volume=600_000_000_000_000;});
 h.forEach(b=>{b.volume=9_600_000_000_000_000;});
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'a numerically equal but unsafe integer total is not exact count evidence');
});
test('large fractional volume aggregates cannot hide a full reported-unit drift',()=>{
 // All sixteen volumes have genuine fractional parts, so the integer-only
 // branch does not apply. The former 64-ULP tolerance was >1 at this scale.
 const {h,q}=fixture();
 q.forEach(b=>{b.volume=6_250_000_000_000.25;});
 h.forEach(b=>{b.volume=100_000_000_000_004;});
 assert.equal(auditCrtCrossTimeframe(h,q).checkedFourHourBars,2);
 h[0].volume!+=1;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'a full unit discrepancy is not acceptable floating-point summation noise');
});
test('exact quarter-unit 15m volumes reject sub-unit 4H aggregate drift',()=>{
 // All sixteen reported values are exact quarter-units. The previous
 // fractional 0.25-unit tolerance accepted a real 0.125 discrepancy at
 // ~1e14 even though scaled integer reconciliation is exact and safe.
 const {h,q}=fixture();
 q.forEach(b=>{b.volume=6_250_000_000_000.25;});
 h.forEach(b=>{b.volume=100_000_000_000_004;});
 const coherent=auditCrtCrossTimeframe(h,q);
 assert.deepEqual(coherent.reconciledNumericVolumeStarts,[BASE,BASE+H4]);
 h[0].volume=100_000_000_000_004.125;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'a non-quarter aggregate cannot be reconciled to exact quarter-unit constituents');
 h[0].volume=100_000_000_000_004.25;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'a full quarter-unit drift must also fail');
});
test('large scaled dyadic sums reject one precisely represented fractional unit',()=>{
 // Each 15m source value has a representable 1/1024 unit. Their exact
 // 16-bar sum is 1/64 above 1e14, but scaling that sum by 1024 exceeds
 // Number.MAX_SAFE_INTEGER. Falling back to 64-ULP tolerance previously
 // accepted a real one-ULP (1/64-unit) mismatch in the 4H aggregate.
 const {h,q}=fixture();
 const each=6_250_000_000_000+1/1024;
 const aggregate=100_000_000_000_000+1/64;
 assert.equal(Number.isSafeInteger(each*1024),true);
 assert.equal(Number.isSafeInteger(aggregate*1024),false);
 q.forEach(b=>{b.volume=each;});
 h.forEach(b=>{b.volume=aggregate;});
 assert.deepEqual(auditCrtCrossTimeframe(h,q).reconciledNumericVolumeStarts,
  [BASE,BASE+H4],'coherent high-scale fractional volumes remain auditable');
 h[0].volume=aggregate+1/64;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'a source-representable fractional drift must not hide behind 64-ULP tolerance');
});

test('high-scale dyadic volume finer than 1/65536 rejects exact source drift',()=>{
 // A 1/131072-unit increment is representable at this nominal scale.
 // The previous 2^16 search missed it and fell back to a tolerance larger
 // than one exact 4H increment, silently accepting a source mismatch.
 const {h,q}=fixture();
 const each=625_000_000+1/131072;
 const coherent=10_000_000_000+1/8192;
 const inconsistent=coherent+1/8192;
 assert.equal(Number.isInteger(each*2**16),false);
 assert.equal(Number.isInteger(each*2**17),true);
 q.forEach(b=>{b.volume=each;});
 h.forEach(b=>{b.volume=coherent;});
 assert.deepEqual(auditCrtCrossTimeframe(h,q).reconciledNumericVolumeStarts,
  [BASE,BASE+H4],'exact finer dyadic sums remain certifiable');
 h[0].volume=inconsistent;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'exact fractional drift must not pass a loose scale-relative tolerance');
});
test('fine dyadic 4H/15m volume drift below 64-ULP tolerance fails closed',()=>{
 // Sixteen exact 2^-40 fractional increments sum to 2^-36. At ~100
 // aggregate units, a one-2^-40-unit drift is below the fallback tolerance.
 // The old 2^32 ceiling skipped exact reconciliation and accepted it.
 const {h,q}=fixture();
 const each=6.25+2**-40;
 const coherent=100+2**-36;
 const inconsistent=coherent+2**-40;
 const tolerance=64*Number.EPSILON*inconsistent;
 assert.ok(Math.abs(inconsistent-coherent)<tolerance,
  'this regression must exercise the old fallback acceptance hole');
 assert.equal(Number.isInteger(each*2**32),false);
 assert.equal(Number.isInteger(each*2**40),true);
 q.forEach(b=>{b.volume=each;});
 h.forEach(b=>{b.volume=coherent;});
 assert.deepEqual(auditCrtCrossTimeframe(h,q).reconciledNumericVolumeStarts,
  [BASE,BASE+H4],'exact 2^-40 constituents should certify at the correct total');
 h[0].volume=inconsistent;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'a representable sub-tolerance discrepancy is not summation noise');
});

test('exact eighth-unit 15m volume and ordinary decimal roundoff retain distinct rules',()=>{
 const exact=fixture();
 exact.q.forEach(b=>{b.volume=0.125;});
 exact.h.forEach(b=>{b.volume=2;});
 assert.equal(auditCrtCrossTimeframe(exact.h,exact.q).checkedFourHourBars,2);
 exact.h[0].volume=2.125;
 assert.throws(()=>auditCrtCrossTimeframe(exact.h,exact.q),/volume mismatch/);
 const decimal=fixture();
 decimal.q.forEach(b=>{b.volume=0.1;});
 decimal.h.forEach(b=>{b.volume=1.6;});
 assert.equal(auditCrtCrossTimeframe(decimal.h,decimal.q).checkedFourHourBars,2,
  'non-dyadic decimal input must still allow bounded floating-point summation noise');
});
test('fractional volume sums above safe integer magnitude cannot be certified',()=>{
 // The old fractional branch accepted equal rounded totals above 2^53,
 // although sub-unit differences can no longer be reliably represented.
 const {h,q}=fixture();
 q.forEach(b=>{b.volume=600_000_000_000_000.25;});
 h.forEach(b=>{b.volume=9_600_000_000_000_004;});
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'matching rounded totals are not evidence of precise aggregation');
});
test('fractional constituents cannot hide a true sum beyond the safe-integer ceiling',()=>{
 // Number addition rounds MAX_SAFE_INTEGER + 0.1 back to MAX_SAFE_INTEGER.
 // The old safeMagnitude test only inspected that rounded total, and the
 // non-dyadic tolerance accepted a falsely coherent 4H aggregate.
 const {h,q}=fixture();
 q.forEach(b=>{b.volume=0;});
 h.forEach(b=>{b.volume=0;});
 const max=Number.MAX_SAFE_INTEGER;
 q[0].volume=max;q[1].volume=0.1;h[0].volume=max;
 assert.equal(max+0.1,max,'fixture must reproduce Number rounding');
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'a positive fractional addition above the exact safe bound is not coherent');

 // The whole parts can sum to the bound even when no individual input does.
 q[0].volume=max-1;q[1].volume=1.1;
 assert.equal((max-1)+1.1,max);
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'fractional overflow after whole-part accumulation must also be rejected');

 // Two small fractional constituents can cross the remaining one-unit gap.
 q[0].volume=max-1;q[1].volume=0.6;q[2].volume=0.6;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'multiple subunit contributions cannot disappear in rounded summation');

 // The exact maximum SAFE integer total remains a valid integer count.
 q[0].volume=max;q[1].volume=0;q[2].volume=0;
 assert.deepEqual(auditCrtCrossTimeframe(h,q).reconciledNumericVolumeStarts,
  [BASE,BASE+H4]);
});

test('a sub-ULP positive 15m volume cannot disappear into a large integer 4H total',()=>{
 // This is below MAX_SAFE_INTEGER: the former overflow-only guard
 // missed a small positive constituent erased by ordinary Number sum.
 const {h,q}=fixture();
 q.forEach(b=>{b.volume=0;});
 h.forEach(b=>{b.volume=0;});
 q[0].volume=1_000_000_000_000;
 q[1].volume=1e-8;
 h[0].volume=1_000_000_000_000;
 assert.equal(q[0].volume+q[1].volume,h[0].volume,
  'the positive fractional observation is rounded away at this scale');
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'a rounded integer 4H total cannot certify known positive extra volume');
 q[1].volume=0;
 assert.deepEqual(auditCrtCrossTimeframe(h,q).reconciledNumericVolumeStarts,
  [BASE,BASE+H4],'genuine integer volume remains certifiable');
 q[1].volume=0.125;
 h[0].volume=1_000_000_000_000.125;
 assert.deepEqual(auditCrtCrossTimeframe(h,q).reconciledNumericVolumeStarts,
  [BASE,BASE+H4],'exactly represented fractional aggregate remains certifiable');
});

test('an unsafe constituent volume is not laundered through fractional tolerance',()=>{
 const {h,q}=fixture();
 q.forEach(b=>{b.volume=0;});
 h.forEach(b=>{b.volume=0;});
 q[0].volume=9_007_199_254_740_994;
 h[0].volume=9_007_199_254_740_994;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'a rounded unsafe input cannot be certified even when totals match');
});
test('small fractional volume summation still permits floating-point roundoff',()=>{
 const {h,q}=fixture();
 q.forEach(b=>{b.volume=0.1;});
 h.forEach(b=>{b.volume=1.6;});
 assert.equal(auditCrtCrossTimeframe(h,q).checkedFourHourBars,2);
});
test('tiny fractional volume mismatch cannot pass a one-unit tolerance floor',()=>{
 // Sixteen 1e-16 observations genuinely sum to ~1.6e-15. The old
 // Math.max(1, ...) floor allowed a zero 4H volume to pass as equal.
 const {h,q}=fixture();
 q.forEach(b=>{b.volume=1e-16;});
 h.forEach(b=>{b.volume=1.6e-15;});
 assert.equal(auditCrtCrossTimeframe(h,q).checkedFourHourBars,2,
  'legitimate tiny fractional summation roundoff remains acceptable');
 h[0].volume=0;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'a reported zero aggregate must not hide observed tiny fractional volume');
});
test('null constituent or aggregate volume stays unknown, not fabricated zero',()=>{
 const x=fixture();
 x.q.forEach(b=>{b.volume=5;});
 // A null 4H volume is unknown; price-only OHLC audit remains possible.
 assert.equal(auditCrtCrossTimeframe(x.h,x.q).checkedFourHourBars,2);
 const y=fixture();
 y.q.forEach(b=>{b.volume=5;});
 y.h.forEach(b=>{b.volume=80;});
 y.q[3].volume=null;
 assert.equal(auditCrtCrossTimeframe(y.h,y.q).checkedFourHourBars,2);
 // This checked count certifies price aggregation only, not real volume
 // source identity or a volume confirmation gate.
});

test('fully observed 4H prices reject impossible numeric volume lower bound with one null 15m volume',()=>{
 const {h,q}=fixture();
 q.forEach(b=>{b.volume=5;});
 h.forEach(b=>{b.volume=80;});
 q[3].volume=null;
 q[4].volume=100;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),
  /4H\/15m partial volume contradiction/,
  'missing one constituent volume cannot hide a known 15m overcount');
 q[4].volume=5;
 const compatible=auditCrtCrossTimeframe(h,q);
 assert.deepEqual(compatible.reconciledNumericVolumeStarts,[BASE+H4],
  'a compatible lower bound remains unknown, never fully reconciled');
 assert.equal(certifiedCrtFourHourBars(h,q,compatible)[0].volume,null);
 h[0].volume=null;
 q[4].volume=100;
 const unknown=auditCrtCrossTimeframe(h,q);
 assert.equal(unknown.checkedFourHourBars,2,
  'unknown reported 4H volume cannot be contradicted by known 15m volume');
 assert.deepEqual(unknown.reconciledNumericVolumeStarts,[BASE+H4]);
});

test('null 15m volume cannot conceal a fractional lower-bound overflow',()=>{
 const {h,q}=fixture();
 h[0].volume=Number.MAX_SAFE_INTEGER;
 q[0].volume=Number.MAX_SAFE_INTEGER;
 q[1].volume=0.1;
 q[2].volume=null;
 assert.equal(q[0].volume+q[1].volume,h[0].volume,
  'ordinary Number addition rounds away the positive fractional evidence');
 assert.throws(()=>auditCrtCrossTimeframe(h,q),
  /4H\/15m partial volume contradiction/,
  'the known lower bound must be evaluated without a rounded-away fraction');
 q[1].volume=0;
 const compatible=auditCrtCrossTimeframe(h,q);
 assert.equal(compatible.checkedFourHourBars,2);
 assert.deepEqual(compatible.reconciledNumericVolumeStarts,[],
  'a null constituent cannot be promoted into reconciled volume');
});

test('CRT price certification redacts numeric 4H volume without complete 15m reconciliation',()=>{
 const {h,q}=fixture();
 h.forEach(b=>{b.volume=80;});
 q.forEach(b=>{b.volume=5;});
 q[3].volume=null; // 4H 00:00 OHLC matches, but volume cannot be checked.
 const report=auditCrtCrossTimeframe(h,q);
 assert.deepEqual(report.verifiedFourHourStarts,[BASE,BASE+H4]);
 assert.deepEqual(report.reconciledNumericVolumeStarts,[BASE+H4]);
 const certified=certifiedCrtFourHourBars(h,q,report);
 assert.equal(certified[0].volume,null,
  'uncheckable 4H volume must not enter certified evidence');
 assert.equal(certified[1].volume,80,
  'fully reconciled numeric 4H volume remains visible, not authenticated');
 assert.equal(h[0].volume,80,'original source response is not rewritten');
 assert.equal(Object.isFrozen(report.reconciledNumericVolumeStarts),true);
 assert.throws(()=>{(report.reconciledNumericVolumeStarts as number[]).push(BASE);},TypeError);
 const allUnknown=fixture();
 allUnknown.q.forEach(b=>{b.volume=5;});
 const unknownReport=auditCrtCrossTimeframe(allUnknown.h,allUnknown.q);
 assert.deepEqual(unknownReport.reconciledNumericVolumeStarts,[]);
 assert.equal(certifiedCrtFourHourBars(allUnknown.h,allUnknown.q,unknownReport)[0].volume,null);
});

test('missing interior 15m observations never certify an apparently complete 4H bar',()=>{
 const {h,q}=fixture();
 q.splice(5,1);
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/Missing or noncontiguous/);
});
test('complete interior 15m bucket cannot disappear from the 4H source response',()=>{
 const {h,q}=fixture();
 q.push(...Array.from({length:16},(_,i)=>candle(BASE+2*H4+i*Q)));
 h.push(candle(BASE+2*H4,100,101,99,100,240));
 assert.equal(auditCrtCrossTimeframe(h,q).checkedFourHourBars,3);
 const missing=h.splice(1,1)[0];
 assert.throws(()=>auditCrtCrossTimeframe(h,q),
  /Missing 4H candle for complete 15m source bucket/,
  'two individually coherent 4H edges cannot conceal an omitted full 4H bucket');
 h.splice(1,0,missing);
 assert.equal(auditCrtCrossTimeframe(h,q).checkedFourHourBars,3);
});
test('partial interior 15m evidence does not invent an omitted 4H candle',()=>{
 const {h,q}=fixture();
 q.push(...Array.from({length:16},(_,i)=>candle(BASE+2*H4+i*Q)));
 h.push(candle(BASE+2*H4,100,101,99,100,240));
 h.splice(1,1);
 q.splice(20,1); // One source minute bucket is absent in the omitted 4H.
 const report=auditCrtCrossTimeframe(h,q);
 assert.deepEqual(report.verifiedFourHourStarts,[BASE,BASE+2*H4]);
 assert.deepEqual(certifiedCrtFourHourBars(h,q,report).map(b=>b.time),
  [BASE,BASE+2*H4],
  'only the two individually observed bars qualify; they are not adjacent');
});
test('partially overlapping 4H boundaries reject observed impossible 15m extrema',()=>{
 for(const side of ['high','low'] as const){
  const {h,q}=fixture();
  if(side==='high')q[5].high=h[0].high+0.01;
  else q[5].low=h[0].low-0.01;
  assert.throws(()=>auditCrtCrossTimeframe([h[0]],q.slice(1,12)),
   /Partial 4H\/15m OHLC contradiction/,
   'an observed 15m extreme cannot exceed the containing 4H envelope');
 }
});
test('partially observed first open and last close must match their 4H endpoints',()=>{
 {
  const {h,q}=fixture();
  q[0].open+=0.01;
  assert.throws(()=>auditCrtCrossTimeframe([h[0]],q.slice(0,12)),
   /Partial 4H\/15m OHLC contradiction/);
 }
 {
  const {h,q}=fixture();
  q[15].close+=0.01;
  assert.throws(()=>auditCrtCrossTimeframe([h[0]],q.slice(4,16)),
   /Partial 4H\/15m OHLC contradiction/);
 }
});
test('partial 4H boundaries reject observed volume exceeding their reported total',()=>{
 const integer=fixture();
 integer.h[0].volume=10;
 integer.q[4].volume=7;
 integer.q[5].volume=4;
 assert.throws(()=>auditCrtCrossTimeframe([integer.h[0]],integer.q.slice(4,12)),
  /Partial 4H\/15m volume contradiction/,
  'known nonnegative constituents cannot exceed a containing 4H total');

 const fractional=fixture();
 fractional.h[0].volume=0.2;
 fractional.q[4].volume=0.125;
 fractional.q[5].volume=0.125;
 assert.throws(()=>auditCrtCrossTimeframe([fractional.h[0]],fractional.q.slice(4,12)),
  /Partial 4H\/15m volume contradiction/,
  'exact fractional lower bounds must not hide behind summation tolerance');

 const unknown=fixture();
 unknown.h[0].volume=10;
 unknown.q[4].volume=11;
 unknown.q[5].volume=null;
 assert.throws(()=>auditCrtCrossTimeframe([unknown.h[0]],unknown.q.slice(4,12)),
  /Partial 4H\/15m volume contradiction/,
  'one unknown constituent cannot erase a contradictory known lower bound');
});

test('a known 15m constituent equal to the 4H volume cannot hide another positive volume',()=>{
 // A capped 0.25-unit tolerance used to accept this contradictory archive:
 // one 15m volume ALREADY equals the full reported 4H total, yet a second
 // 15m bar contributes another 0.1. Both inputs are nonnegative.
 const {h,q}=fixture();
 const aggregate=100_000_000_000_000+0.125;
 h.forEach(b=>{b.volume=0;});
 q.forEach(b=>{b.volume=0;});
 h[0].volume=aggregate;
 q[0].volume=aggregate;
 q[1].volume=0.1;
 const rounded=q[0].volume+q[1].volume;
 assert.ok(rounded>aggregate&&rounded-aggregate<0.25,
  'the known lower-bound contradiction must sit inside the former tolerance');
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'complete numeric coverage cannot certify an impossible total');
 q[2].volume=null;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/partial volume contradiction/,
  'an unknown third volume cannot erase the two known positive contributors');
 assert.throws(()=>auditCrtCrossTimeframe([h[0]],q.slice(0,12)),
  /Partial .* volume contradiction/,
  'a partial boundary must also reject the definite known lower bound');
 q[1].volume=0;
 q[2].volume=0;
 assert.deepEqual(auditCrtCrossTimeframe(h,q).reconciledNumericVolumeStarts,
  [BASE,BASE+H4],
  'a sole equal-valued constituent with all other volumes zero remains valid');
});

test('a fractional 4H total cannot omit a sub-ULP positive 15m contributor',()=>{
 // The 4H total exactly equals two source contributions, but a third
 // strictly positive volume is rounded away by ordinary Number addition.
 // The older integer-total and single-equal-contributor guards miss this.
 const {h,q}=fixture();
 h.forEach(b=>{b.volume=0;});
 q.forEach(b=>{b.volume=0;});
 const base=1_000_000_000_000+0.125;
 h[0].volume=base;
 q[0].volume=1_000_000_000_000;
 q[1].volume=0.125;
 q[2].volume=1e-8;
 assert.equal(q[0].volume+q[1].volume+q[2].volume,base,
  'fixture must exercise a positive source contribution erased by rounding');
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
  'complete coverage must reject the exactly omitted positive contributor');
 q[3].volume=null;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/partial volume contradiction/,
  'a null 15m volume cannot erase the known lower-bound contradiction');
 assert.throws(()=>auditCrtCrossTimeframe([h[0]],q.slice(0,12)),
  /Partial .* volume contradiction/,
  'partial 4H boundaries must reject the same observed overrun');
 q[2].volume=0;
 q[3].volume=0;
 assert.deepEqual(auditCrtCrossTimeframe(h,q).reconciledNumericVolumeStarts,
  [BASE,BASE+H4],
  'removing the extra contribution restores exact numeric reconciliation');
 const decimals=fixture();
 decimals.q.forEach(b=>{b.volume=0.1;});
 decimals.h.forEach(b=>{b.volume=1.6;});
 assert.equal(auditCrtCrossTimeframe(decimals.h,decimals.q).checkedFourHourBars,2,
  'ordinary decimal roundoff remains permitted');
});

test('partial volume evidence never fabricates complete 4H reconciliation',()=>{
 const x=fixture();
 x.h[0].volume=10;
 x.q[4].volume=3;
 x.q[5].volume=null;
 const partial=auditCrtCrossTimeframe([x.h[0]],x.q.slice(4,12));
 assert.equal(partial.checkedFourHourBars,0);
 assert.equal(partial.uncheckableFourHourBars,1);
 assert.deepEqual(partial.reconciledNumericVolumeStarts,[],
  'a compatible partial lower bound is not a certified volume total');

 const unknownAggregate=fixture();
 unknownAggregate.q[4].volume=100;
 const result=auditCrtCrossTimeframe([unknownAggregate.h[0]],
  unknownAggregate.q.slice(4,12));
 assert.equal(result.uncheckableFourHourBars,1,
  'null 4H volume must remain unknown rather than assumed zero');
});

test('consistent incomplete 4H boundary stays uncheckable rather than fabricated',()=>{
 const {h,q}=fixture();
 const report=auditCrtCrossTimeframe([h[0]],q.slice(4,12));
 assert.equal(report.checkedFourHourBars,0);
 assert.equal(report.uncheckableFourHourBars,1);
 assert.deepEqual(report.verifiedFourHourStarts,[]);
});

test('partial overlapping boundary windows are explicitly uncheckable, not falsely verified',()=>{
 const {h,q}=fixture();
 assert.deepEqual(auditCrtCrossTimeframe(h,q.slice(1,31)),
  {checkedFourHourBars:0,uncheckableFourHourBars:2,
   verifiedFourHourStarts:[],reconciledNumericVolumeStarts:[]});
 assert.deepEqual(auditCrtCrossTimeframe(h,q.slice(16)),
  {checkedFourHourBars:1,uncheckableFourHourBars:1,
   verifiedFourHourStarts:[BASE+H4],reconciledNumericVolumeStarts:[]});
});
test('mutations to candles after the checked 4H window do not affect past audit',()=>{
 const {h,q}=fixture();
 const before=auditCrtCrossTimeframe(h,q);
 q.push(candle(BASE+32*Q,200,210,190,200));
 assert.deepEqual(auditCrtCrossTimeframe(h,q),before);
});
test('rejects malformed 15m/4H input instead of silently accepting',()=>{
 const x=fixture();x.q[0].observed_minutes=14;
 assert.throws(()=>auditCrtCrossTimeframe(x.h,x.q),/Incomplete or invalid/);
 const y=fixture();y.h[0].time+=Q;
 assert.throws(()=>auditCrtCrossTimeframe(y.h,y.q),/Incomplete or invalid/);
 const z=fixture();z.q[1].time=z.q[0].time;
 assert.throws(()=>auditCrtCrossTimeframe(z.h,z.q),/Out-of-order/);
});
test('rejects aligned 4H and 15m buckets whose close timestamp is unsafe',()=>{
 // Near MAX_SAFE_INTEGER the opening time is exactly representable, but
 // adding one full bar duration is not. Do not certify a rounded close.
 const last4hStart=Math.floor(Number.MAX_SAFE_INTEGER/H4)*H4;
 const last15mStart=Math.floor(Number.MAX_SAFE_INTEGER/Q)*Q;
 assert.equal(Number.isSafeInteger(last4hStart),true);
 assert.equal(Number.isSafeInteger(last15mStart),true);
 assert.equal(Number.isSafeInteger(last4hStart+H4),false);
 assert.equal(Number.isSafeInteger(last15mStart+Q),false);
 const x=fixture();x.h[0].time=last4hStart;
 assert.throws(()=>auditCrtCrossTimeframe(x.h,x.q),/Incomplete or invalid/);
 const y=fixture();y.q[0].time=last15mStart;
 assert.throws(()=>auditCrtCrossTimeframe(y.h,y.q),/Incomplete or invalid/);
 const ordinary=fixture();
 assert.equal(auditCrtCrossTimeframe(ordinary.h,ordinary.q).checkedFourHourBars,2);
});

test('CRT rejects safe-integer candle closes outside the ISO calendar range',()=>{
 // Date.toISOString() supports at most 8.64e12 epoch seconds. These UTC
 // aligned starts and closes are safe integers, but the completed closes
 // are unrenderable and must never enter a displayed research candidate.
 const maxIsoSeconds=8_640_000_000_000;
 assert.equal(maxIsoSeconds%H4,0);
 assert.equal(maxIsoSeconds%Q,0);
 assert.equal(Number.isSafeInteger(maxIsoSeconds+H4),true);
 assert.equal(Number.isSafeInteger(maxIsoSeconds+Q),true);
 assert.equal(Number.isNaN(new Date((maxIsoSeconds+Q)*1000).getTime()),true);
 const x=fixture();x.h[0].time=maxIsoSeconds;
 assert.throws(()=>auditCrtCrossTimeframe(x.h,x.q),/Incomplete or invalid/,
  '4H close outside the ISO range must fail before any CRT certification');
 const y=fixture();y.q[0].time=maxIsoSeconds;
 assert.throws(()=>auditCrtCrossTimeframe(y.h,y.q),/Incomplete or invalid/,
  '15m close outside the ISO range must fail before certification');
 // A completed bar ending at the final representable ISO instant is still
 // accepted when its 16 matching source 15m observations are available.
 const z=fixture(),delta=maxIsoSeconds-H4-BASE;
 const last4h=z.h.slice(0,1),last15m=z.q.slice(0,16);
 last4h.forEach(b=>{b.time+=delta;});
 last15m.forEach(b=>{b.time+=delta;});
 assert.equal(Number.isFinite(new Date((last4h[0].time+H4)*1000).getTime()),true);
 assert.equal(auditCrtCrossTimeframe(last4h,last15m).checkedFourHourBars,1);
});

test('a missing 15m response cannot be presented as verified 4H coherence',()=>{
 const {h}=fixture();
 assert.deepEqual(auditCrtCrossTimeframe(h,[]),
  {checkedFourHourBars:0,uncheckableFourHourBars:2,
   verifiedFourHourStarts:[],reconciledNumericVolumeStarts:[]});
});

test('uncheckable archive-edge 4H candle cannot manufacture a CRT sweep candidate',()=>{
 // 15m API history begins at 04:00. The 00:00 reference is not independently
 // certified, even though the 04:00 sweep and 08:00 follow-up are certified.
 const h=[
  candle(BASE,105,110,100,105,240),
  candle(BASE+H4,104,109,98.5,104,240),
  candle(BASE+2*H4,104,106,101,104,240),
 ];
 const q=Array.from({length:32},(_,i)=>{
  const t=BASE+H4+i*Q;
  return i<16?candle(t,104,108,101,104):candle(t,104,106,101,104);
 });
 q[3].high=109;q[7].low=98.5;
 const source={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'NSXUSD-CFD',provider:'owner-authorized-archive',
  priceSide:'bid' as const,volumeType:'unverified' as const,volumeVerified:false,
 };
 const unfiltered=screenCrtHypotheses({fourHour:h,fifteenMinute:q,source});
 assert.equal(unfiltered.candidates.length,1,'regression fixture has a real-looking but uncertified sweep');
 const audit=auditCrtCrossTimeframe(h,q);
 assert.deepEqual(audit.verifiedFourHourStarts,[BASE+H4,BASE+2*H4]);
 assert.equal(audit.uncheckableFourHourBars,1);
 const certified=certifiedCrtFourHourBars(h,q,audit);
 assert.deepEqual(certified.map(x=>x.time),[BASE+H4,BASE+2*H4]);
 assert.equal(screenCrtHypotheses({fourHour:certified,fifteenMinute:q,source}).candidates.length,0,
  'uncheckable 4H reference must never appear in candidate counts');
});
test('a tampered or stale certification report cannot be used to select 4H bars',()=>{
 const {h,q}=fixture();
 const valid=auditCrtCrossTimeframe(h,q);
 assert.throws(()=>certifiedCrtFourHourBars(h,q,{
  ...valid,verifiedFourHourStarts:[BASE+2*H4,BASE+H4],
 }),/Stale or inconsistent 4H\/15m certification report/);
 assert.throws(()=>certifiedCrtFourHourBars(h,q,{
  ...valid,checkedFourHourBars:1,
 }),/Stale or inconsistent 4H\/15m certification report/);
});

test('certified 4H bars remain detached and frozen after the original inputs change',()=>{
 const {h,q}=fixture();
 const report=auditCrtCrossTimeframe(h,q);
 const certified=certifiedCrtFourHourBars(h,q,report);
 const originalOpen=certified[0].open;
 assert.notStrictEqual(certified[0],h[0],
  'certification must not expose a mutable alias to the source candle');
 assert.equal(Object.isFrozen(certified[0]),true);
 assert.equal(Object.isFrozen(certified),true,
  'the certified candle collection itself must be immutable');
 assert.throws(()=>{(certified as Bar[]).push(candle(BASE+2*H4));},TypeError,
  'a consumer cannot append a fabricated 4H reference after certification');
 assert.throws(()=>{(certified as Bar[]).splice(0,1);},TypeError,
  'a consumer cannot silently remove an audited sweep');
 assert.deepEqual(certified.map(b=>b.time),[BASE,BASE+H4]);
 assert.equal(h.length,2,'the source input remains untouched');
 // Both source timeframes still reconcile, but the previously issued report
 // is stale. The already returned certified snapshot must not change.
 h[0].open+=0.01;
 q[0].open+=0.01;
 assert.equal(auditCrtCrossTimeframe(h,q).checkedFourHourBars,2);
 assert.equal(certified[0].open,originalOpen);
 assert.throws(()=>{certified[0].open=originalOpen+0.01;},TypeError,
  'downstream code cannot silently rewrite certified evidence');
 assert.throws(()=>certifiedCrtFourHourBars(h,q,report),
  /Stale or inconsistent 4H\/15m certification report/);
});

test('a stale 4H/15m audit cannot certify edited historical OHLC',()=>{
 const x=fixture();
 const report=auditCrtCrossTimeframe(x.h,x.q);
 x.h[0].close+=0.01; // Still a valid 4H candle, but no longer agrees with 15m.
 assert.throws(()=>certifiedCrtFourHourBars(x.h,x.q,report),/Stale or inconsistent 4H\/15m certification report/);
 const y=fixture();
 const old=auditCrtCrossTimeframe(y.h,y.q);
 y.q[0].open+=0.01; // Valid 15m candle; invalidates the previously checked open.
 assert.throws(()=>certifiedCrtFourHourBars(y.h,y.q,old),/Stale or inconsistent 4H\/15m certification report/);
});

test('a forged audit cannot substitute an existing uncheckable 4H reference',()=>{
 const {h,q}=fixture();
 const partial=q.slice(16); // 00:00 4H is uncheckable; 04:00 is verified.
 const report=auditCrtCrossTimeframe(h,partial);
 assert.deepEqual(report.verifiedFourHourStarts,[BASE+H4]);
 const forged={...report,verifiedFourHourStarts:[BASE]};
 assert.throws(()=>certifiedCrtFourHourBars(h,partial,forged),
  /Stale or inconsistent 4H\/15m certification report/);
});

test('certification rejects coordinated post-audit edits even when both timeframes still reconcile',()=>{
 const x=fixture();
 const report=auditCrtCrossTimeframe(x.h,x.q);
 assert.deepEqual(certifiedCrtFourHourBars(x.h,x.q,report),x.h,
  'unchanged audited candles remain eligible');
 // Both aggregates are changed together: a fresh cross-timeframe audit still
 // succeeds, but the old report must not certify these replacement prices.
 x.h[0].open+=0.01;
 x.q[0].open+=0.01;
 assert.equal(auditCrtCrossTimeframe(x.h,x.q).checkedFourHourBars,2);
 assert.throws(()=>certifiedCrtFourHourBars(x.h,x.q,report),
  /Stale or inconsistent 4H\/15m certification report/);

 const y=fixture();
 y.q.forEach(b=>{b.volume=5;});
 y.h.forEach(b=>{b.volume=80;});
 const volumeReport=auditCrtCrossTimeframe(y.h,y.q);
 y.q[0].volume=6;
 y.h[0].volume=81;
 assert.equal(auditCrtCrossTimeframe(y.h,y.q).checkedFourHourBars,2);
 assert.throws(()=>certifiedCrtFourHourBars(y.h,y.q,volumeReport),
  /Stale or inconsistent 4H\/15m certification report/);
});

test('a copied audit report without its issued snapshot cannot certify candle inputs',()=>{
 const x=fixture();
 const report=auditCrtCrossTimeframe(x.h,x.q);
 assert.throws(()=>certifiedCrtFourHourBars(x.h,x.q,{...report}),
  /Stale or inconsistent 4H\/15m certification report/);
});

test('CRT certification binds the issued report to its exact source-array instances',()=>{
 const {h,q}=fixture();
 const issued=auditCrtCrossTimeframe(h,q);
 const copied4h=h.map(b=>({...b}));
 const copied15m=q.map(b=>({...b}));
 assert.deepEqual(copied4h,h,'replacement 4H values are byte-for-byte equivalent as numbers');
 assert.deepEqual(copied15m,q,'replacement 15m values are equivalent');
 assert.throws(()=>certifiedCrtFourHourBars(copied4h,q,issued),
  /Stale or inconsistent 4H\/15m certification report/,
  'a different 4H response cannot reuse the old source-array certificate');
 assert.throws(()=>certifiedCrtFourHourBars(h,copied15m,issued),
  /Stale or inconsistent 4H\/15m certification report/,
  'a different 15m response cannot reuse the old source-array certificate');
 assert.throws(()=>certifiedCrtFourHourBars(copied4h,copied15m,issued),
  /Stale or inconsistent 4H\/15m certification report/);
 const newReport=auditCrtCrossTimeframe(copied4h,copied15m);
 assert.deepEqual(certifiedCrtFourHourBars(copied4h,copied15m,newReport),
  copied4h,'replacement arrays remain usable after their own fresh audit');
 assert.deepEqual(certifiedCrtFourHourBars(h,q,issued),h,
  'the unchanged original report remains valid for its original arrays');
});

test('CRT certificates reject equal-valued replacement candle objects in the same source arrays',()=>{
 const {h,q}=fixture();
 const issued=auditCrtCrossTimeframe(h,q);
 const original4h=h[0],original15m=q[0];
 const replacement4h={...original4h};
 h[0]=replacement4h;
 assert.deepEqual(replacement4h,original4h,'numerical snapshot alone cannot detect a replacement object');
 assert.equal(auditCrtCrossTimeframe(h,q).checkedFourHourBars,2,
  'the replacement still reconciles, but it is a different source observation');
 assert.throws(()=>certifiedCrtFourHourBars(h,q,issued),
  /Stale or inconsistent 4H\/15m certification report/,
  'an existing array with a substituted 4H candle must require re-audit');
 h[0]=original4h;
 q[0]={...original15m};
 assert.throws(()=>certifiedCrtFourHourBars(h,q,issued),
  /Stale or inconsistent 4H\/15m certification report/,
  'a substituted 15m constituent must also invalidate the original certificate');
 h[0]={...original4h};
 assert.throws(()=>certifiedCrtFourHourBars(h,q,issued),
  /Stale or inconsistent 4H\/15m certification report/,
  'coordinated equal-valued replacements cannot reuse old evidence');
 const fresh=auditCrtCrossTimeframe(h,q);
 assert.deepEqual(certifiedCrtFourHourBars(h,q,fresh).map(b=>b.time),[BASE,BASE+H4],
  'freshly audited replacement objects remain eligible');
 h[0]=original4h;q[0]=original15m;
 assert.deepEqual(certifiedCrtFourHourBars(h,q,issued).map(b=>b.time),[BASE,BASE+H4],
  'the unchanged original candle instances remain eligible with their original certificate');
});

test('issued cross-timeframe audit report and verified timestamp list are immutable',()=>{
 const {h,q}=fixture();
 const report=auditCrtCrossTimeframe(h,q);
 assert.equal(Object.isFrozen(report),true);
 assert.equal(Object.isFrozen(report.verifiedFourHourStarts),true);
 assert.equal(Object.isFrozen(report.reconciledNumericVolumeStarts),true);
 assert.throws(()=>{(report as {checkedFourHourBars:number}).checkedFourHourBars=0;},TypeError);
 assert.throws(()=>{(report.verifiedFourHourStarts as number[])[0]=BASE+2*H4;},TypeError);
 assert.throws(()=>{(report.verifiedFourHourStarts as number[]).push(BASE+2*H4);},TypeError);
 assert.deepEqual(report.verifiedFourHourStarts,[BASE,BASE+H4]);
 assert.equal(certifiedCrtFourHourBars(h,q,report).length,2,
  'unchanged frozen reports remain valid for source re-audit');
});

test('certified CRT candles expose only the declared seven-field source schema',()=>{
 const {h,q}=fixture();
 let extraReads=0;
 Object.defineProperty(h[0],'claimedFeedAuthentication',{
  enumerable:true,configurable:true,
  get(){extraReads++;throw Error('unaudited source metadata getter was evaluated');},
 });
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/undeclared source metadata/);
 assert.equal(extraReads,0,'undeclared metadata must not be read or copied');
 Reflect.deleteProperty(h[0],'claimedFeedAuthentication');
 (h[1] as Bar&{claimedBrokerExecution?:boolean}).claimedBrokerExecution=true;
 assert.throws(()=>auditCrtCrossTimeframe(h,q),/undeclared source metadata/);
 Reflect.deleteProperty(h[1],'claimedBrokerExecution');
 const report=auditCrtCrossTimeframe(h,q);
 const certified=certifiedCrtFourHourBars(h,q,report);
 assert.deepEqual(Reflect.ownKeys(certified[0]),[
  'time','open','high','low','close','volume','observed_minutes',
 ]);
 assert.deepEqual(certified.map(b=>b.time),[BASE,BASE+H4]);
 assert.equal(Object.isFrozen(certified[0]),true);
 assert.equal(Object.isFrozen(certified),true);
});

test('CRT audit and stale certification reject accessor or inherited candle fields without reading getters',()=>{
 const x=fixture();
 let getterReads=0;
 Object.defineProperty(x.h[0],'open',{
  configurable:true,enumerable:true,
  get(){getterReads++;return 100.5;},
 });
 assert.throws(()=>auditCrtCrossTimeframe(x.h,x.q),/own data fields/);
 assert.equal(getterReads,0,'a validated price getter must never execute');

 const y=fixture();
 const inherited=Object.create({close:y.q[0].close}) as Bar;
 Object.assign(inherited,y.q[0]);
 delete (inherited as Partial<Bar>).close;
 y.q[0]=inherited;
 assert.throws(()=>auditCrtCrossTimeframe(y.h,y.q),/ordinary JSON object prototype/,
  'prototype-inherited prices are not immutable JSON candle evidence');

 const z=fixture();
 const report=auditCrtCrossTimeframe(z.h,z.q);
 Object.defineProperty(z.q[0],'open',{
  configurable:true,enumerable:true,
  get(){getterReads++;return 100.5;},
 });
 assert.throws(()=>certifiedCrtFourHourBars(z.h,z.q,report),/own data fields/,
  'snapshot comparison must reject newly installed getters before reading');
 assert.equal(getterReads,0);
});

test('CRT cross-timeframe audit rejects accessor, inherited and post-audit array slots',()=>{
 const x=fixture();
 let slotReads=0;
 Object.defineProperty(x.h,'0',{
  configurable:true,enumerable:true,
  get(){slotReads++;return candle(BASE,100.5,103,97,100.25,240);},
 });
 assert.throws(()=>auditCrtCrossTimeframe(x.h,x.q),/own data entries/);
 assert.equal(slotReads,0,'the rejected 4H slot getter must not execute');

 const y=fixture();
 const inherited=y.q[0];
 delete y.q[0];
 const prototype=Object.create(Array.prototype);
 Object.defineProperty(prototype,'0',{value:inherited,configurable:true});
 Object.setPrototypeOf(y.q,prototype);
 assert.throws(()=>auditCrtCrossTimeframe(y.h,y.q),/own data entries/,
  'an inherited 15m array element is not a source JSON record');

 const z=fixture();
 const report=auditCrtCrossTimeframe(z.h,z.q);
 Object.defineProperty(z.q,'0',{
  configurable:true,enumerable:true,
  get(){slotReads++;return candle(BASE);},
 });
 assert.throws(()=>certifiedCrtFourHourBars(z.h,z.q,report),/own data entries/,
  'a source array slot replaced after certification must be rejected');
 assert.equal(slotReads,0,'the stale-report guard must not execute slot getters');

 const valid=fixture();
 const stable=auditCrtCrossTimeframe(valid.h,valid.q);
 assert.deepEqual(certifiedCrtFourHourBars(valid.h,valid.q,stable).map(b=>b.time),
  [BASE,BASE+H4],'ordinary dense JSON arrays remain supported');
});

test('CRT audit refuses overridden array iteration and methods before executing them',()=>{
 for(const method of ['map','slice','filter'] as const){
  const {h,q}=fixture();
  let calls=0;
  const target=method==='slice'?q:h;
  Object.defineProperty(target,method,{
   configurable:true,value:()=>{calls++;throw Error('untrusted array method executed');},
  });
  assert.throws(()=>auditCrtCrossTimeframe(h,q),/ordinary JSON array methods/);
  assert.equal(calls,0,method+' must not execute during source certification');
 }
 const x=fixture();
 let iteratorCalls=0;
 Object.defineProperty(x.h,Symbol.iterator,{
  configurable:true,
  value:function*(){iteratorCalls++;throw Error('untrusted iterator executed');},
 });
 assert.throws(()=>auditCrtCrossTimeframe(x.h,x.q),/ordinary JSON array methods/);
 assert.equal(iteratorCalls,0,'an overridden 4H iterator must never be invoked');

 const y=fixture();
 const issued=auditCrtCrossTimeframe(y.h,y.q);
 Object.defineProperty(y.h,'filter',{
  configurable:true,value:()=>{throw Error('untrusted certification filter executed');},
 });
 assert.throws(()=>certifiedCrtFourHourBars(y.h,y.q,issued),
  /ordinary JSON array methods/,'post-audit method replacement invalidates certification');

 const z=fixture();
 Object.setPrototypeOf(z.q,Object.create(Array.prototype));
 assert.throws(()=>auditCrtCrossTimeframe(z.h,z.q),/ordinary JSON array methods/,
  'nonstandard inherited array methods are not trustworthy JSON evidence');

 const plain=fixture();
 const valid=auditCrtCrossTimeframe(plain.h,plain.q);
 assert.deepEqual(certifiedCrtFourHourBars(plain.h,plain.q,valid).map(b=>b.time),
  [BASE,BASE+H4],'ordinary source JSON arrays remain supported');
});

test('CRT source arrays reject constructor/species hijacking before any getter executes',()=>{
 for(const side of ['h','q'] as const){
  const source=fixture();
  let getterReads=0;
  Object.defineProperty(source[side],'constructor',{
   configurable:true,
   get(){getterReads++;throw Error('untrusted array constructor getter executed');},
  });
  assert.throws(()=>auditCrtCrossTimeframe(source.h,source.q),
   /ordinary JSON array methods/);
  assert.equal(getterReads,0,'source-array constructor getter must not execute');
 }
 const x=fixture();
 let speciesReads=0;
 const customConstructor={};
 Object.defineProperty(customConstructor,Symbol.species,{
  get(){speciesReads++;throw Error('untrusted array species getter executed');},
 });
 Object.defineProperty(x.q,'constructor',{value:customConstructor,configurable:true});
 assert.throws(()=>auditCrtCrossTimeframe(x.h,x.q),
  /ordinary JSON array methods/,'even a data-valued constructor can redirect slice/map');
 assert.equal(speciesReads,0,'species getter must not execute');

 const y=fixture();
 const issued=auditCrtCrossTimeframe(y.h,y.q);
 Object.defineProperty(y.h,'constructor',{
  configurable:true,
  get(){speciesReads++;throw Error('post-audit array constructor getter executed');},
 });
 assert.throws(()=>certifiedCrtFourHourBars(y.h,y.q,issued),
  /ordinary JSON array methods/,'stale certification rejects a later constructor override');
 assert.equal(speciesReads,0);

 const ordinary=fixture();
 const report=auditCrtCrossTimeframe(ordinary.h,ordinary.q);
 assert.deepEqual(certifiedCrtFourHourBars(ordinary.h,ordinary.q,report).map(b=>b.time),
  [BASE,BASE+H4],'plain JSON source arrays still certify');
});

test('CRT rejects global Array species changes before allocating verified arrays',()=>{
 // The inherited slice/map/filter methods can be pristine while their
 // ArraySpeciesCreate constructor is replaced globally after module load.
 // A malicious species getter must never run during either audit or reuse.
 const {h,q}=fixture();
 const issued=auditCrtCrossTimeframe(h,q);
 const original=Object.getOwnPropertyDescriptor(Array,Symbol.species);
 assert.ok(original?.configurable);
 let speciesReads=0;
 let auditError:unknown,certError:unknown;
 try{
  Object.defineProperty(Array,Symbol.species,{
   configurable:true,enumerable:false,
   get(){speciesReads++;return Array;},
  });
  try{auditCrtCrossTimeframe(h,q);}catch(error){auditError=error;}
  try{certifiedCrtFourHourBars(h,q,issued);}catch(error){certError=error;}
 }finally{
  Object.defineProperty(Array,Symbol.species,original);
 }
 assert.match(String(auditError),/ordinary JSON array methods/);
 assert.match(String(certError),/ordinary JSON array methods/);
 assert.equal(speciesReads,0,'untrusted global species getter was never invoked');
 assert.deepEqual(certifiedCrtFourHourBars(h,q,issued).map(b=>b.time),
  [BASE,BASE+H4],'restored native species retains valid source certification');
});

test('CRT rejects mutated Array prototype methods, iterator and species constructor before execution',()=>{
 // Source arrays can retain ordinary own slots and no own overrides while
 // a different library mutates the shared Array prototype after module load.
 // Restore each global descriptor before asserting to avoid leaking changes.
 for(const key of ['map','reduce','push',Symbol.iterator,'constructor'] as const){
  const {h,q}=fixture();
  const original=Object.getOwnPropertyDescriptor(Array.prototype,key);
  assert.ok(original);
  let reads=0, failure:unknown;
  try{
   Object.defineProperty(Array.prototype,key,{
    configurable:true,get(){reads++;throw Error('untrusted global Array getter executed');},
   });
   try{auditCrtCrossTimeframe(h,q);}
   catch(error){failure=error;}
  }finally{
   Object.defineProperty(Array.prototype,key,original);
  }
  assert.match(String(failure),/ordinary JSON array methods/,
   'mutated shared Array intrinsics must invalidate source certification');
  assert.equal(reads,0,'audit must not execute a mutated prototype getter');
 }
 const normal=fixture();
 assert.equal(auditCrtCrossTimeframe(normal.h,normal.q).checkedFourHourBars,2,
  'restored standard arrays must still pass the source-coherence audit');
});


test('CRT rejects post-audit inherited push changes before reusing a certificate',()=>{
 // A modified inherited push could forge verified-start or numeric-volume
 // report lists even when all source candles are unchanged. Reject it
 // before executing the new getter and require a clean runtime to re-audit.
 const {h,q}=fixture();
 const report=auditCrtCrossTimeframe(h,q);
 const original=Object.getOwnPropertyDescriptor(Array.prototype,'push');
 assert.ok(original);
 let reads=0,failure:unknown;
 try{
  Object.defineProperty(Array.prototype,'push',{
   configurable:true,get(){reads++;throw Error('untrusted push getter executed');},
  });
  try{certifiedCrtFourHourBars(h,q,report);}
  catch(error){failure=error;}
 }finally{
  Object.defineProperty(Array.prototype,'push',original);
 }
 assert.match(String(failure),/ordinary JSON array methods/);
 assert.equal(reads,0,'the altered push getter must never execute');
 assert.deepEqual(certifiedCrtFourHourBars(h,q,report).map(b=>b.time),
  [BASE,BASE+H4],'restoring the standard push preserves valid evidence');
});

test('CRT refuses undeclared source metadata on historical array containers',()=>{
 // A JSON candle array cannot silently carry an additional ASK population
 // or a claimed provider verification status outside the frozen BID schema.
 for(const side of ['h','q'] as const){
  const x=fixture();
  let reads=0;
  Object.defineProperty(x[side],'askCandles',{
   configurable:true,
   get(){reads++;throw Error('undeclared ASK metadata getter executed');},
  });
  assert.throws(()=>auditCrtCrossTimeframe(x.h,x.q),
   /undeclared source metadata/);
  assert.equal(reads,0,'metadata getters must not execute during audit');
 }
 const y=fixture();
 const report=auditCrtCrossTimeframe(y.h,y.q);
 const undeclaredSymbol=Symbol('claimedBrokerAuthentication');
 Object.defineProperty(y.q,undeclaredSymbol,{value:true,configurable:true});
 assert.throws(()=>certifiedCrtFourHourBars(y.h,y.q,report),
  /undeclared source metadata/,
  'a source container altered after certification must require fresh review');
 delete (y.q as unknown as Record<symbol,unknown>)[undeclaredSymbol];
 assert.deepEqual(certifiedCrtFourHourBars(y.h,y.q,report).map(b=>b.time),
  [BASE,BASE+H4],'unchanged ordinary arrays remain eligible');
});

test('CRT source snapshots resist inherited array toJSON hooks masking coordinated edits',()=>{
 const previous=Object.getOwnPropertyDescriptor(Array.prototype,'toJSON');
 try{
  // JSON.stringify of a nested array would become a constant regardless
  // of its contents, allowing a stale certificate to survive source edits.
  Object.defineProperty(Array.prototype,'toJSON',{
   configurable:true,writable:true,value(){return 'masked';},
  });
  const {h,q}=fixture();
  const issued=auditCrtCrossTimeframe(h,q);
  assert.equal(certifiedCrtFourHourBars(h,q,issued).length,2);
  h[0].open+=0.01;
  q[0].open+=0.01;
  assert.equal(auditCrtCrossTimeframe(h,q).checkedFourHourBars,2,
   'coordinated edits still reconcile across timeframes');
  assert.throws(()=>certifiedCrtFourHourBars(h,q,issued),
   /Stale or inconsistent 4H\/15m certification report/,
   'inherited JSON hooks must not hide changes to issued evidence');
 }finally{
  if(previous)Object.defineProperty(Array.prototype,'toJSON',previous);
  else Reflect.deleteProperty(Array.prototype,'toJSON');
 }
});

test('CRT snapshot never invokes inherited object toJSON getters',()=>{
 const previous=Object.getOwnPropertyDescriptor(Object.prototype,'toJSON');
 let reads=0;
 try{
  Object.defineProperty(Object.prototype,'toJSON',{
   configurable:true,get(){reads++;throw Error('untrusted toJSON getter invoked');},
  });
  const {h,q}=fixture();
  const issued=auditCrtCrossTimeframe(h,q);
  assert.equal(certifiedCrtFourHourBars(h,q,issued).length,2);
  assert.equal(reads,0,'primitive snapshot encoding must not consult toJSON');
 }finally{
  if(previous)Object.defineProperty(Object.prototype,'toJSON',previous);
  else Reflect.deleteProperty(Object.prototype,'toJSON');
 }
});


test('CRT refuses undeclared metadata on individual 4H and 15m candle records',()=>{
 // Unlike array-level metadata, these fields ride on an otherwise valid
 // candle. Reject without executing getters or implying ASK/source evidence
 // was independently authenticated by a price-only BID consistency check.
 for(const side of ['h','q'] as const){
  const source=fixture();
  let reads=0;
  Object.defineProperty(source[side][0],'brokerVerifiedAsk',{
   configurable:true,enumerable:false,
   get(){reads++;throw Error('unreviewed candle metadata getter executed');},
  });
  assert.throws(()=>auditCrtCrossTimeframe(source.h,source.q),
   /candle contains undeclared source metadata/);
  assert.equal(reads,0,'extra candle metadata getter must not execute');
 }
 const source=fixture();
 const report=auditCrtCrossTimeframe(source.h,source.q);
 const claimedVolumeSource=Symbol('exchangeVolumeVerified');
 Object.defineProperty(source.q[1],claimedVolumeSource,{
  configurable:true,value:true,
 });
 assert.throws(()=>certifiedCrtFourHourBars(source.h,source.q,report),
  /candle contains undeclared source metadata/,
  'a post-audit symbol on a constituent candle invalidates the old report');
 Reflect.deleteProperty(source.q[1],claimedVolumeSource);
 assert.deepEqual(certifiedCrtFourHourBars(source.h,source.q,report).map(b=>b.time),
  [BASE,BASE+H4],'restored unchanged JSON candle records remain certifiable');

 const normal=fixture();
 const valid=auditCrtCrossTimeframe(normal.h,normal.q);
 assert.equal(certifiedCrtFourHourBars(normal.h,normal.q,valid).length,2);
});

test('CRT rejects custom candle prototypes without reading inherited source claims',()=>{
 for(const side of ['h','q'] as const){
  const source=fixture();
  let inheritedReads=0;
  const prototype=Object.create(Object.prototype);
  Object.defineProperty(prototype,'brokerVerifiedAsk',{
   get(){inheritedReads++;throw Error('unverified inherited ASK claim executed');},
  });
  Object.setPrototypeOf(source[side][0],prototype);
  assert.throws(()=>auditCrtCrossTimeframe(source.h,source.q),
   /ordinary JSON object prototype/,
   'seven valid own fields must not certify inherited provider metadata');
  assert.equal(inheritedReads,0,'prototype metadata getter must never run');
 }
 const nullPrototype=fixture();
 Object.setPrototypeOf(nullPrototype.q[0],null);
 assert.throws(()=>auditCrtCrossTimeframe(nullPrototype.h,nullPrototype.q),
  /ordinary JSON object prototype/,
  'null-prototype records are not ordinary JSON-decoded candles');

 const altered=fixture();
 const report=auditCrtCrossTimeframe(altered.h,altered.q);
 const original=Object.getPrototypeOf(altered.q[1]);
 Object.setPrototypeOf(altered.q[1],Object.create(original));
 assert.throws(()=>certifiedCrtFourHourBars(altered.h,altered.q,report),
  /ordinary JSON object prototype/,
  'post-audit prototype substitution invalidates issued evidence');
 Object.setPrototypeOf(altered.q[1],original);
 assert.deepEqual(certifiedCrtFourHourBars(altered.h,altered.q,report).map(b=>b.time),
  [BASE,BASE+H4],'restored unchanged plain candles remain certifiable');
});

test('CRT requires JSON-visible own data for all seven historical candle fields',()=>{
 // Non-enumerable properties can return plausible numbers in memory but
 // disappear on JSON serialization; they are not source-observed evidence.
 const fields=['time','open','high','low','close','volume','observed_minutes'] as const;
 for(const side of ['h','q'] as const){
  for(const field of fields){
   const {h,q}=fixture();
   const record=side==='h'?h[0]:q[0];
   Object.defineProperty(record,field,{
    value:record[field],enumerable:false,writable:true,configurable:true,
   });
   assert.equal(Object.hasOwn(JSON.parse(JSON.stringify(record)),field),false,
    'hidden '+field+' is not part of the JSON source record');
   assert.throws(()=>auditCrtCrossTimeframe(h,q),/own data fields/,
    'hidden '+field+' on '+side+' must not certify');
  }
 }
 const altered=fixture();
 const issued=auditCrtCrossTimeframe(altered.h,altered.q);
 Object.defineProperty(altered.q[0],'volume',{
  value:null,enumerable:false,writable:true,configurable:true,
 });
 assert.throws(()=>certifiedCrtFourHourBars(altered.h,altered.q,issued),
  /own data fields/,'a post-audit hidden field invalidates old certification');
 const normal=fixture();
 assert.equal(auditCrtCrossTimeframe(normal.h,normal.q).checkedFourHourBars,2,
  'ordinary JSON-decoded candle records remain supported');
});

test('CRT source windows require enumerable own indexed candle entries',()=>{
 // JSON.parse creates enumerable own indexed slots. A non-enumerable own
 // slot is an exotic in-memory source container even when its value matches.
 for(const side of ['h','q'] as const){
  const x=fixture();
  const row=x[side][0];
  Object.defineProperty(x[side],'0',{
   value:row,writable:true,configurable:true,enumerable:false,
  });
  assert.throws(()=>auditCrtCrossTimeframe(x.h,x.q),
   /enumerable own data entries/,`hidden ${side} slot must not certify`);
 }
 const x=fixture();
 const issued=auditCrtCrossTimeframe(x.h,x.q);
 Object.defineProperty(x.q,'0',{
  value:x.q[0],writable:true,configurable:true,enumerable:false,
 });
 assert.throws(()=>certifiedCrtFourHourBars(x.h,x.q,issued),
  /enumerable own data entries/,
  'a post-audit hidden 15m slot must invalidate prior certification');
 const ordinary=fixture();
 const jsonH=JSON.parse(JSON.stringify(ordinary.h)) as Bar[];
 const jsonQ=JSON.parse(JSON.stringify(ordinary.q)) as Bar[];
 assert.equal(auditCrtCrossTimeframe(jsonH,jsonQ).checkedFourHourBars,2,
  'ordinary JSON-decoded source windows remain valid');
});

test('partial 4H volume catches fractional overflow hidden by Number rounding',()=>{
 // The exact received lower bound is MAX_SAFE_INTEGER + 0.1, but ordinary
 // Number addition rounds the 0.1 away. A partial 4H cannot certify this
 // apparently equal aggregate as a consistent lower bound.
 const hidden=fixture();
 hidden.h[0].volume=Number.MAX_SAFE_INTEGER;
 hidden.q[4].volume=Number.MAX_SAFE_INTEGER;
 hidden.q[5].volume=0.1;
 assert.equal(hidden.q[4].volume+hidden.q[5].volume,
  hidden.h[0].volume,'fixture must reproduce rounded-away evidence');
 assert.throws(()=>auditCrtCrossTimeframe([hidden.h[0]],
  hidden.q.slice(4,12)),/Partial 4H\/15m volume contradiction/,
  'observed positive fraction cannot be hidden by an unsafe rounded sum');

 const exact=fixture();
 exact.h[0].volume=Number.MAX_SAFE_INTEGER;
 exact.q[4].volume=Number.MAX_SAFE_INTEGER;
 exact.q[5].volume=0;
 const partial=auditCrtCrossTimeframe([exact.h[0]],exact.q.slice(4,12));
 assert.equal(partial.uncheckableFourHourBars,1);
 assert.deepEqual(partial.reconciledNumericVolumeStarts,[],
  'even an exact partial lower bound never certifies full 4H volume');

 const ordinary=fixture();
 ordinary.h[0].volume=10.5;
 ordinary.q[4].volume=10;
 ordinary.q[5].volume=0.1;
 assert.equal(auditCrtCrossTimeframe([ordinary.h[0]],
  ordinary.q.slice(4,12)).uncheckableFourHourBars,1,
  'non-dyadic fractions below a larger reported 4H total stay uncheckable');
});

test('CRT rejects two distinct positive 15m volumes lost beneath fractional 4H rounding',()=>{
 // At this magnitude, adding either small constituent (or both) does not
 // change the rounded JavaScript sum. Neither alone equals the exact omitted
 // binary64 amount, so the previous single-contributor guard missed it.
 const x=fixture();
 x.q.forEach(b=>{b.volume=0;});
 x.h.forEach(b=>{b.volume=0;});
 const reported=1_000_000_000_000.125;
 x.q[0].volume=1_000_000_000_000;
 x.q[1].volume=0.125;
 x.q[2].volume=0.00000001;
 x.q[3].volume=0.00000002;
 x.h[0].volume=reported;
 assert.equal(x.q.slice(0,16).reduce((sum,b)=>sum+(b.volume??0),0),
  reported,'ordinary Number addition must conceal the two positive inputs');
 assert.throws(()=>auditCrtCrossTimeframe(x.h,x.q),/volume mismatch/,
  'a complete 4H cannot omit two exact positive constituents');

 const partial=fixture();
 partial.q.forEach(b=>{b.volume=null;});
 partial.h[0].volume=reported;
 partial.q[4].volume=1_000_000_000_000;
 partial.q[5].volume=0.125;
 partial.q[6].volume=0.00000001;
 partial.q[7].volume=0.00000002;
 assert.throws(()=>auditCrtCrossTimeframe([partial.h[0]],partial.q.slice(4,12)),
  /Partial 4H\/15m volume contradiction/,
  'a partial 4H still rejects a proven two-contributor lower-bound excess');

 // Do not reject ordinary decimal-rounding noise or invent unknown volume.
 const valid=fixture();
 valid.q.forEach(b=>{b.volume=0.1;});
 valid.h.forEach(b=>{b.volume=1.6;});
 assert.deepEqual(auditCrtCrossTimeframe(valid.h,valid.q).reconciledNumericVolumeStarts,
  [BASE,BASE+H4],'ordinary decimal rounding retains its bounded tolerance');

 const unknown=fixture();
 unknown.q.forEach(b=>{b.volume=null;});
 unknown.h[0].volume=null;
 assert.equal(auditCrtCrossTimeframe(unknown.h,unknown.q).checkedFourHourBars,2,
  'unknown source volume remains unknown, not a fabricated zero');
});


test('CRT volume audit detects three or more distinct positive 15m volumes lost to rounding',()=>{
 // Neither an individual nor any pair equals the exact omitted difference.
 // The earlier one/two-contributor probes accepted the rounded 4H total.
 for(const tiny of [[1e-8,2e-8,4e-8],[1e-8,2e-8,4e-8,8e-8]]){
  const {h,q}=fixture();
  q.forEach(b=>{b.volume=0;});
  q[0].volume=1_000_000_000_000;
  q[1].volume=0.125;
  tiny.forEach((value,i)=>{q[i+2].volume=value;});
  h[0].volume=1_000_000_000_000.125;
  assert.equal(q.slice(0,16).reduce((sum,b)=>sum+(b.volume??0),0),
   h[0].volume,'ordinary Number addition loses the observed tiny volumes');
  assert.throws(()=>auditCrtCrossTimeframe(h,q),/volume mismatch/,
   'all reported positive contributors must count, not only one or two');
  // Missing tail 15m coverage cannot certify volume, but its observed
  // nonnegative contributors still disprove the same reported 4H total.
  assert.throws(()=>auditCrtCrossTimeframe([h[0]],q.slice(0,15)),
   /Partial 4H\/15m volume contradiction/,
   'partial observations must not conceal multiple omitted constituents');
 }
 const ordinary=fixture();
 ordinary.q.forEach(b=>{b.volume=0;});
 ordinary.q[0].volume=0.1;
 ordinary.q[1].volume=0.2;
 ordinary.q[2].volume=0.3;
 ordinary.h[0].volume=0.1+0.2+0.3;
 assert.deepEqual(auditCrtCrossTimeframe(ordinary.h,ordinary.q)
  .reconciledNumericVolumeStarts,[BASE],
  'ordinary binary64 decimal summation remains a valid received aggregate');
});
