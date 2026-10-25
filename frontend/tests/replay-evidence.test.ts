import {test} from 'node:test';
import assert from 'node:assert/strict';
import {replayEvidence} from '../lib/replay-evidence.ts';
import {replayPrefix,type Bar} from '../lib/research.ts';
const bar=(time:number,observed_minutes=5):Bar=>({time,open:10,high:12,low:9,close:11,volume:null,observed_minutes});
test('empty replay has no window or implied evidence',()=>{
 assert.deepEqual(replayEvidence([],'5m'),{revealedBars:0,firstBarOpen:null,lastBarOpen:null,observedMinutes:0,unusableBars:0,discontinuities:0,state:'NO_DATA'});
});
test('future mutations and rewinds do not change prefix evidence',()=>{
 const bars=[bar(0),bar(300),bar(600)];
 const before=replayEvidence(replayPrefix(bars,2),'5m');
 bars[2]=bar(900,1);
 assert.deepEqual(replayEvidence(replayPrefix(bars,2),'5m'),before);
 assert.equal(before.lastBarOpen,300);assert.equal(before.observedMinutes,10);
 assert.equal(replayEvidence(replayPrefix(bars,1),'5m').observedMinutes,5);
});
test('partial buckets and unknown gaps stay insufficient without fabricated minutes',()=>{
 const result=replayEvidence([bar(0),bar(300,2),bar(900)],'5m');
 assert.equal(result.state,'INSUFFICIENT_DATA');assert.equal(result.unusableBars,1);
 assert.equal(result.discontinuities,1);assert.equal(result.observedMinutes,12);
 assert.equal(replayEvidence([bar(0),bar(600)],'5m').discontinuities,1);
});
test('invalid coverage, OHLC and duplicate time cannot certify a continuous prefix',()=>{
 for(const invalid of [bar(300,NaN),bar(300,-1),bar(300,1.5),{...bar(300),high:1}])
  assert.equal(replayEvidence([bar(0),invalid],'5m').state,'INSUFFICIENT_DATA');
 assert.equal(replayEvidence([bar(0),bar(0)],'5m').state,'INSUFFICIENT_DATA');
});
test('calendar month adjacency uses existing structural gate without assuming full coverage',()=>{
 const result=replayEvidence([bar(Date.UTC(2024,0,1)/1000,1),bar(Date.UTC(2024,1,1)/1000,1)],'1M');
 assert.equal(result.state,'OBSERVED_PREFIX');assert.equal(result.observedMinutes,2);
 assert.throws(()=>replayEvidence([],'unsupported'));
});
