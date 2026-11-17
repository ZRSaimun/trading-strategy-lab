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
 } as Bar;
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
