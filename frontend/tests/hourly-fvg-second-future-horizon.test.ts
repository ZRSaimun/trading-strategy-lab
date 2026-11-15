import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic input-integrity regression, not authenticated market or P&L evidence.
test('second future hour beyond supported timestamp horizon is rejected without reading future market fields',()=>{
 const H=3600, cutoff=Date.UTC(2026,10,1,6)/1000;
 const source:FvgSource={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false};
 const prefix:Bar[]=Array.from({length:23},(_,i)=>({
  time:cutoff-(23-i)*H,open:100,high:101,low:99,close:100,
  volume:10,observed_minutes:60}));
 const reads=[0,0],market=[0,0];
 const future=[cutoff+H,Date.UTC(2100,0,1,1)/1000].map((time,i)=>({
  get time(){reads[i]++;return time;},
  get open(){market[i]++;throw Error('future OHLC read');},
  get high(){market[i]++;throw Error('future OHLC read');},
  get low(){market[i]++;throw Error('future OHLC read');},
  get close(){market[i]++;throw Error('future OHLC read');},
  get volume(){market[i]++;throw Error('future volume read');},
  get observed_minutes(){market[i]++;throw Error('future coverage read');},
 })) as unknown as Bar[];
 assert.throws(()=>studyHourlyFvgMidpointAsOf([...prefix,...future],source,cutoff),
  /Invalid or unordered hourly as-of input timestamp/);
 assert.deepEqual(reads,[1,1]);
 assert.deepEqual(market,[0,0]);
});
