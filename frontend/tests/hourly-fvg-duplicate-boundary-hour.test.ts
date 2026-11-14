import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic timing/integrity regression; not market evidence.
test('duplicate hourly timestamps exactly at as-of boundary fail closed without pending market reads',()=>{
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
 const reads=[0,0],market=[0,0];
 const pending=[0,1].map(i=>({
  get time(){reads[i]++;return cutoff;},
  get open(){market[i]++;throw Error('pending open accessed');},
  get high(){market[i]++;throw Error('pending high accessed');},
  get low(){market[i]++;throw Error('pending low accessed');},
  get close(){market[i]++;throw Error('pending close accessed');},
  get volume(){market[i]++;throw Error('pending volume accessed');},
  get observed_minutes(){market[i]++;throw Error('pending coverage accessed');},
 })) as unknown as Bar[];
 assert.throws(()=>studyHourlyFvgMidpointAsOf([...prefix,...pending],source,cutoff),
  /Invalid or unordered hourly as-of input timestamp/);
 assert.deepEqual(reads,[1,1]);
 assert.deepEqual(market,[0,0]);
});
