import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic causality contract, not market provenance or trading performance.
test('completed hourly timestamp accessor cannot certify mutable private time state',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 let completedReads=0,futureReads=0,futureMarketReads=0;
 let privateTime=0;
 const completed={
  get time(){completedReads++;return privateTime;},
  open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
 } as Bar;
 const future={
  get time(){futureReads++;privateTime=H;return 2*H;},
  get open(){futureMarketReads++;throw Error('future open read');},
  get high(){futureMarketReads++;throw Error('future high read');},
  get low(){futureMarketReads++;throw Error('future low read');},
  get close(){futureMarketReads++;throw Error('future close read');},
  get volume(){futureMarketReads++;throw Error('future volume read');},
  get observed_minutes(){futureMarketReads++;throw Error('future coverage read');},
 } as unknown as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([completed,future],source,H),
  /FVG as-of completed timestamps require own data properties/,
 );
 assert.equal(completedReads,1);
 assert.equal(futureReads,0,'reject unstable completed time before future getter');
 assert.equal(futureMarketReads,0);
 // A normal completed own-data timestamp is still accepted, while an
 // unrevealed future time accessor is consulted once for ordering only.
 privateTime=0;
 const stable={time:0,open:100,high:101,low:99,close:100,
  volume:10,observed_minutes:60} as Bar;
 const study=studyHourlyFvgMidpointAsOf([stable,future],source,H);
 assert.equal(study.coverage.observedBars,1);
 assert.equal(futureReads,1);
 assert.equal(futureMarketReads,0);
});

test('later completed timestamp accessor is rejected before any future timestamp or market field',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 let completedReads=0,futureTimeReads=0,futureMarketReads=0;
 const first:Bar={time:0,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60};
 const second={
  get time(){completedReads++;return H;},
  open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
 } as Bar;
 const future={
  get time(){futureTimeReads++;return 3*H;},
  get open(){futureMarketReads++;throw Error('future open read');},
  get high(){futureMarketReads++;throw Error('future high read');},
  get low(){futureMarketReads++;throw Error('future low read');},
  get close(){futureMarketReads++;throw Error('future close read');},
  get volume(){futureMarketReads++;throw Error('future volume read');},
  get observed_minutes(){futureMarketReads++;throw Error('future coverage read');},
 } as unknown as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([first,second,future],source,2*H),
  /FVG as-of completed timestamps require own data properties/,
 );
 assert.equal(completedReads,1);
 assert.equal(futureTimeReads,0);
 assert.equal(futureMarketReads,0);
});

test('last completed hourly timestamp accessor fails without requiring a future row',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 let reads=0;
 const first:Bar={time:0,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60};
 const last={
  get time(){reads++;return H;},
  open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
 } as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([first,last],source,2*H),
  /FVG as-of completed timestamps require own data properties/,
 );
 assert.equal(reads,1,'reject final completed accessor even without a future row');
});

test('inherited completed timestamp is not accepted as own historical evidence',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 let inheritedReads=0,futureTimeReads=0,futureMarketReads=0;
 const prototype=Object.create(null) as {time:number};
 Object.defineProperty(prototype,'time',{
  get(){inheritedReads++;return 0;},enumerable:true,
 });
 const completed=Object.assign(Object.create(prototype),{
  open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
 }) as Bar;
 const future={
  get time(){futureTimeReads++;return 2*H;},
  get open(){futureMarketReads++;throw Error('future open read');},
  get high(){futureMarketReads++;throw Error('future high read');},
  get low(){futureMarketReads++;throw Error('future low read');},
  get close(){futureMarketReads++;throw Error('future close read');},
  get volume(){futureMarketReads++;throw Error('future volume read');},
  get observed_minutes(){futureMarketReads++;throw Error('future coverage read');},
 } as unknown as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([completed,future],source,H),
  /Hourly as-of timestamp lacks own field evidence/,
 );
 assert.equal(inheritedReads,0,'inherited timestamp getter must never execute');
 assert.equal(futureTimeReads,0);
 assert.equal(futureMarketReads,0);
});

test('inherited plain timestamp data cannot certify a completed hourly candle',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 let futureReads=0;
 const completed=Object.assign(Object.create({time:0}),{
  open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
 }) as Bar;
 const future={
  get time(){futureReads++;throw Error('future time read');},
  get open(){throw Error('future open read');},
 } as unknown as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([completed,future],source,H),
  /Hourly as-of timestamp lacks own field evidence/,
 );
 assert.equal(futureReads,0,'reject inherited plain data before future timestamp');
});


test('later completed inherited timestamp fails before a future time accessor',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const first:Bar={time:0,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60};
 let inheritedReads=0,futureReads=0;
 const prototype=Object.create(null);
 Object.defineProperty(prototype,'time',{get(){inheritedReads++;return H;},enumerable:true});
 const second=Object.assign(Object.create(prototype),{
  open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
 }) as Bar;
 const future={
  get time(){futureReads++;throw Error('future timestamp read');},
  get open(){throw Error('future OHLC read');},
 } as unknown as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([first,second,future],source,2*H),
  /Hourly as-of timestamp lacks own field evidence/,
 );
 assert.equal(inheritedReads,0,'second completed inherited getter must not execute');
 assert.equal(futureReads,0,'future timestamp must remain unread');
});
