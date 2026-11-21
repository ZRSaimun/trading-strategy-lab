import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic causal-access test; not historical market or profitability evidence.
test('second future-hour timestamp failure does not read either future market candle',()=>{
 const H=3600, cutoff=Date.UTC(2026,10,1,6)/1000;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const prefix:Bar[]=Array.from({length:23},(_,i)=>({
  time:cutoff-(23-i)*H,open:100,high:101,low:99,close:100,
  volume:10,observed_minutes:60,
 }));
 const timestamps=[0,0],market=[0,0];
 const future=[0,1].map(i=>({
  get time(){
   timestamps[i]++;
   if(i===1)throw Error('second future timestamp unavailable');
   return cutoff+H;
  },
  get open(){market[i]++;throw Error('future open accessed');},
  get high(){market[i]++;throw Error('future high accessed');},
  get low(){market[i]++;throw Error('future low accessed');},
  get close(){market[i]++;throw Error('future close accessed');},
  get volume(){market[i]++;throw Error('future volume accessed');},
  get observed_minutes(){market[i]++;throw Error('future coverage accessed');},
 })) as unknown as Bar[];
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([...prefix,...future],source,cutoff),
  /second future timestamp unavailable/
 );
 assert.deepEqual(timestamps,[1,1]);
 assert.deepEqual(market,[0,0]);
});
