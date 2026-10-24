import {test} from 'node:test';
import assert from 'node:assert/strict';
import {summarizeHistoricalQuality,type HistoricalCandle} from '../lib/archive-quality.ts';

const candle=(time:number,minutes=5,volume:number|null=null):HistoricalCandle=>({
 time,open:100,high:102,low:99,close:101,volume,observed_minutes:minutes
});
test('distinguishes loaded bucket gaps, incomplete aggregates and unknown volume',()=>{
 const report=summarizeHistoricalQuality([
  candle(0),candle(300,3,0),candle(1200,5,24)
 ],'5m');
 assert.equal(report.bars,3);
 assert.equal(report.minutesObserved,13);
 assert.equal(report.unobservedSpans,1);
 assert.equal(report.unobservedBuckets,2);
 assert.equal(report.partialBuckets,1);
 assert.equal(report.fullBuckets,2);
 assert.equal(report.unknownVolumeBars,1);
 assert.equal(report.zeroVolumeBars,1);
 assert.equal(report.invalidBars,0);
 assert.equal(report.firstTime,0);
 assert.equal(report.lastTime,1200);
});
test('daily and monthly buckets do not invent session completeness',()=>{
 const day=summarizeHistoricalQuality([candle(0,900),candle(86400*3,800)],'1D');
 assert.equal(day.partialBuckets,null);
 assert.equal(day.fullBuckets,null);
 assert.equal(day.unobservedBuckets,2);
 const month=summarizeHistoricalQuality([candle(1704067200,1300)],'1M');
 assert.equal(month.bucketDurationSeconds,null);
 assert.equal(month.unobservedBuckets,null);
 assert.equal(month.partialBuckets,null);
});
test('empty, invalid and out of order bars are observable rather than silently dropped',()=>{
 const empty=summarizeHistoricalQuality([],'1H');
 assert.equal(empty.bars,0);assert.equal(empty.firstTime,null);
 const malformed=[candle(300),{...candle(300),high:98,observed_minutes:6}];
 const result=summarizeHistoricalQuality(malformed,'5m');
 assert.equal(result.invalidBars,1);
 assert.equal(result.partialBuckets,1);
 assert.equal(result.fullBuckets,1);
 assert.throws(()=>summarizeHistoricalQuality([], '2Q'),/Unrecognized/);
});
test('weekly bucket alignment uses exchange-agnostic UTC sequence, not a calendar claim',()=>{
 const monday=345600;
 const result=summarizeHistoricalQuality([candle(monday),candle(monday+2*604800)],'1W');
 assert.equal(result.invalidBars,0);
 assert.equal(result.unobservedSpans,1);
 assert.equal(result.unobservedBuckets,1);
 assert.equal(result.partialBuckets,null);
});
