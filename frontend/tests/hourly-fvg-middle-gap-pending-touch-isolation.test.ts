import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic BID geometry only; no authenticated quote or volume provenance.
const H=3600;
const source={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
 volumeType:'unverified' as const,volumeVerified:false};

for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending ${direction} midpoint touch cannot override previously exposed middle-hour censor`,()=>{
  const bull=direction==='BULLISH';
  const bars:Bar[]=Array.from({length:21},(_,i)=>({
   time:i*H,open:bull?100:101,high:bull?101:102,
   low:bull?99:100,close:bull?100:101,volume:10,observed_minutes:60,
  }));
  bars.push(...(bull?[
   {time:21*H,open:102,high:105,low:101,close:104,volume:10,observed_minutes:60},
   {time:22*H,open:104,high:106,low:103,close:105,volume:10,observed_minutes:60},
   {time:23*H,open:104,high:105,low:103,close:104,volume:10,observed_minutes:60},
   {time:25*H,open:104,high:105,low:103,close:104,volume:10,observed_minutes:60},
  ]:[
   {time:21*H,open:99,high:100,low:96,close:97,volume:10,observed_minutes:60},
   {time:22*H,open:97,high:98,low:95,close:96,volume:10,observed_minutes:60},
   {time:23*H,open:96,high:97,low:95,close:96,volume:10,observed_minutes:60},
   {time:25*H,open:96,high:97,low:95,close:96,volume:10,observed_minutes:60},
  ]));
  const prefix=studyHourlyFvgMidpointAsOf(bars,source,26*H);
  let reads=0;
  const forbidden=():number=>{reads++;throw Error('unclosed touch field accessed');};
  const pending={time:26*H,
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},get observed_minutes(){return forbidden();},
  } as Bar;
  const actual=studyHourlyFvgMidpointAsOf([...bars,pending],source,26*H);
  assert.deepEqual(actual,prefix);
  // Multiple not-yet-eligible future candles cannot turn a historical
  // missing-hour censor into an observed first touch. Neither accessor may
  // be consulted even when the archive extends beyond the immediate hour.
  const fartherPending=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
   time:{value:27*H,enumerable:true,configurable:true,writable:true},
  }) as Bar;
  assert.deepEqual(studyHourlyFvgMidpointAsOf([...bars,pending,fartherPending],source,26*H),prefix);
  assert.equal(reads,0);
  // An intrabar timestamp is not a completed hourly close: reject it before
  // consulting any pending price, volume or minute-coverage accessor.
  assert.throws(()=>studyHourlyFvgMidpointAsOf([...bars,pending],source,26*H+H/2),
   /Invalid UTC hourly as-of close/);
  assert.equal(reads,0);
  // A malformed future timestamp cannot be silently dropped to make an
  // incomplete source archive appear complete. Reject before touching OHLC.
  const malformed=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
   time:{value:Number.NaN,enumerable:true,configurable:true,writable:true},
  }) as Bar;
  assert.throws(()=>studyHourlyFvgMidpointAsOf([...bars,malformed],source,26*H));
  assert.equal(reads,0);
  // An integer-valued future timestamp outside the safe epoch range must
  // fail before accessing any pending OHLC/volume/coverage getter. Reject
  // both signs of infinity as well; none is a missing-hour observation.
  for(const badTime of [Number.POSITIVE_INFINITY,Number.NEGATIVE_INFINITY,
   Number.MAX_SAFE_INTEGER+1,Number.MIN_SAFE_INTEGER-1,26*H+0.5]){
   const invalid=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
    time:{value:badTime,enumerable:true,configurable:true,writable:true},
   }) as Bar;
   assert.throws(()=>studyHourlyFvgMidpointAsOf([...bars,invalid],source,26*H),
    /Invalid|hourly|timestamp|candle/i);
   assert.equal(reads,0);
  }
  const o=actual.observations.find(x=>x.direction===direction&&x.formationClosedAt===23*H);
  assert.ok(o);
  assert.equal(o.firstTouchOutcome,'INCOMPLETE_WINDOW');
  assert.equal(o.firstTouchCensorReason,'MISSING_HOUR');
  assert.equal(o.firstTouchCensorObservedAt,26*H);
  assert.equal(o.firstTouchObservedWaitBars,1);
  assert.equal(o.firstTouchClosedAt,null);
  assert.equal(o.volumeEvidenceReason,'NOT_EVALUATED');
  assert.equal(o.gates.verifiedVolume,'INSUFFICIENT_DATA');
  assert.equal(o.eligibleForLiveTrading,false);
 });
}
