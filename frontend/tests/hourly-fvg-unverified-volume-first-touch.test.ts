import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpoint,studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

const H=3600;
const source={
 datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
 volumeType:'unverified' as const,volumeVerified:false,
};

test('large synthetic first-touch volume cannot override unverified source provenance',()=>{
 const bars:Bar[]=Array.from({length:20},(_,i)=>({
  time:i*H,open:99,high:100,low:98,close:99,volume:10,observed_minutes:60,
 }));
 bars.push(
  {time:20*H,open:99,high:100,low:98,close:99,volume:10,observed_minutes:60},
  {time:21*H,open:101,high:104,low:100,close:103,volume:10,observed_minutes:60},
  {time:22*H,open:103,high:105,low:102,close:104,volume:10,observed_minutes:60},
  {time:23*H,open:103,high:104,low:100.5,close:103.5,volume:1000000,observed_minutes:60},
 );
 const full=studyHourlyFvgMidpoint(bars,source);
 const asOf=studyHourlyFvgMidpointAsOf(bars,source,24*H);
 assert.deepEqual(asOf,full,'all 24 hourly candles are completed at the decision boundary');
 const touched=full.observations.find(x=>x.formationClosedAt===23*H);
 assert.ok(touched,'the synthetic three-hour gap must form');
 assert.equal(touched.firstTouchOutcome,'TOUCH');
 assert.equal(touched.volumeEvidenceReason,'SOURCE_UNVERIFIED');
 assert.equal(touched.gates.verifiedVolume,'INSUFFICIENT_DATA');
 assert.notEqual(touched.gates.strictCandidate,'PASS');
 assert.equal(touched.eligibleForLiveTrading,false);
});
