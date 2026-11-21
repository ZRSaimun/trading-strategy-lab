import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic archive-integrity test only: no licensed market data or profitability claim.
test('duplicate strictly future hourly timestamps fail closed without reading future market fields',()=>{
 const H=3600;
 const cutoff=Date.UTC(2026,10,1,6)/1000;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const prefix:Bar[]=Array.from({length:23},(_,i)=>({
  time:cutoff-(23-i)*H,open:100,high:101,low:99,close:100,
  volume:10,observed_minutes:60,
 }));
 const timestampReads=[0,0],marketReads=[0,0];
 const future=[0,1].map(index=>({
  get time(){timestampReads[index]++;return cutoff+H;},
  get open(){marketReads[index]++;throw Error('future open accessed');},
  get high(){marketReads[index]++;throw Error('future high accessed');},
  get low(){marketReads[index]++;throw Error('future low accessed');},
  get close(){marketReads[index]++;throw Error('future close accessed');},
  get volume(){marketReads[index]++;throw Error('future volume accessed');},
  get observed_minutes(){marketReads[index]++;throw Error('future coverage accessed');},
 })) as unknown as Bar[];
 assert.throws(()=>studyHourlyFvgMidpointAsOf([...prefix,...future],source,cutoff),
  /Invalid or unordered hourly as-of input timestamp/);
 assert.deepEqual(timestampReads,[1,1],'each future timestamp read exactly once');
 assert.deepEqual(marketReads,[0,0],'future market fields must stay unread');
});
