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

test('bearish unclosed first-touch hour cannot leak volume into causal midpoint research',()=>{
 const completed:Bar[]=Array.from({length:20},(_,i)=>({
  time:i*H,open:101,high:102,low:100,close:101,volume:10,observed_minutes:60,
 }));
 completed.push(
  {time:20*H,open:101,high:102,low:100,close:101,volume:10,observed_minutes:60},
  {time:21*H,open:99,high:100,low:96,close:97,volume:10,observed_minutes:60},
  {time:22*H,open:97,high:98,low:95,close:96,volume:10,observed_minutes:60},
 );
 const pending={time:23*H,open:97,high:99.5,low:96,close:97,observed_minutes:60} as Bar;
 let reads=0;
 Object.defineProperty(pending,'volume',{enumerable:true,get(){
  reads++;throw new Error('future bearish touch volume must not be read');
 }});
 const expected=studyHourlyFvgMidpoint(completed,source);
 const actual=studyHourlyFvgMidpointAsOf([...completed,pending],source,23*H);
 assert.deepEqual(actual,expected);
 assert.equal(reads,0);
 const formed=actual.observations.find(x=>x.direction==='BEARISH' && x.formationClosedAt===23*H);
 assert.ok(formed,'completed bearish formation must remain observable');
 assert.equal(formed.firstTouchOutcome,'INCOMPLETE_WINDOW');
 assert.equal(formed.firstTouchClosedAt,null);
 assert.equal(formed.gates.verifiedVolume,'INSUFFICIENT_DATA');
 assert.equal(formed.eligibleForLiveTrading,false);
});
