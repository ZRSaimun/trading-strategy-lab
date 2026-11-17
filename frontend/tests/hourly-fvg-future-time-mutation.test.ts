import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic regression: a future time getter is not a market-data receipt.
test('future timestamp cannot rewrite a previously completed own-data hour',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const first:Bar={time:0,open:100,high:101,low:99,close:100,
  volume:10,observed_minutes:60};
 const second:Bar={time:H,open:100,high:101,low:99,close:100,
  volume:10,observed_minutes:60};
 let futureTimeReads=0,futureMarketReads=0;
 const future={
  get time(){futureTimeReads++;second.time=2*H;return 4*H;},
  get open(){futureMarketReads++;throw Error('future open read');},
  get high(){futureMarketReads++;throw Error('future high read');},
  get low(){futureMarketReads++;throw Error('future low read');},
  get close(){futureMarketReads++;throw Error('future close read');},
  get volume(){futureMarketReads++;throw Error('future volume read');},
  get observed_minutes(){futureMarketReads++;throw Error('future coverage read');},
 } as unknown as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([first,second,future],source,2*H),
  /FVG as-of timestamp field changed during declaration snapshot/,
 );
 assert.equal(futureTimeReads,1,'future timestamp read is for ordering only');
 assert.equal(futureMarketReads,0,'future market evidence remains unread');
 assert.equal(second.time,2*H,'the hostile mutation actually occurred');
});

test('future timestamp cannot rewrite the first completed own-data hour',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const first:Bar={time:0,open:100,high:101,low:99,close:100,
  volume:10,observed_minutes:60};
 const second:Bar={time:H,open:100,high:101,low:99,close:100,
  volume:10,observed_minutes:60};
 let futureTimeReads=0,futureMarketReads=0;
 const future={
  get time(){futureTimeReads++;first.time=H;return 4*H;},
  get open(){futureMarketReads++;throw Error('future open read');},
  get high(){futureMarketReads++;throw Error('future high read');},
  get low(){futureMarketReads++;throw Error('future low read');},
  get close(){futureMarketReads++;throw Error('future close read');},
  get volume(){futureMarketReads++;throw Error('future volume read');},
  get observed_minutes(){futureMarketReads++;throw Error('future coverage read');},
 } as unknown as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([first,second,future],source,2*H),
  /FVG as-of timestamp field changed during declaration snapshot/,
 );
 assert.equal(futureTimeReads,1,'future timestamp is inspected only for ordering');
 assert.equal(futureMarketReads,0,'future OHLC and volume remain unread');
 assert.equal(first.time,H,'the hostile mutation actually occurred');
});
