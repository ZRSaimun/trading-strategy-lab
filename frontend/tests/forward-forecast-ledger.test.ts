import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ForwardForecastLedger,type FeedIdentity} from '../lib/forward-forecast-ledger.ts';
const identity:FeedIdentity={instrument:'XAUUSD-OTC',provider:'Test Feed',venue:'OTC-test',sourceId:'fixture-A',priceSide:'bid',seconds:60};
const base=1800000000; // divisible by 60
const candle=(start:number,close:number,id:FeedIdentity=identity)=>({identity:id,start,close});
const clock={now:base+60};
const ledger=()=>new ForwardForecastLedger(identity,()=>clock.now,30);

test('settles only after the target candle closes, without early future access',()=>{
 clock.now=base+60;const l=ledger();l.receive(candle(base,100));
 const one=l.issue({id:'a',modelVersion:'rolling-v1',horizon:1,probability:.7});
 const three=l.issue({id:'b',modelVersion:'rolling-v1',horizon:3,probability:.4});
 assert.equal(one.status,'PENDING');assert.equal(three.status,'PENDING');
 clock.now=base+120;l.receive(candle(base+60,101));
 assert.equal(l.entries()[0].outcomeUp,true);assert.equal(l.entries()[1].status,'PENDING');
 clock.now=base+180;l.receive(candle(base+120,99));
 assert.equal(l.entries()[1].status,'PENDING');
 clock.now=base+240;l.receive(candle(base+180,100));
 assert.equal(l.entries()[1].status,'SETTLED');assert.equal(l.entries()[1].outcomeUp,false);
 const s=l.summary();assert.equal(s.settled,2);assert.ok(Math.abs(s.brier!-(.09+.16)/2)<1e-12);
 assert.equal(s.referenceBrier,.25);
});

test('same forecast ID and same candle are idempotent; changed IDs and duplicates are rejected',()=>{
 clock.now=base+60;const l=ledger();l.receive(candle(base,100));
 const input={id:'a',modelVersion:'v1',horizon:1 as const,probability:.55};
 l.issue(input);l.receive(candle(base,100));
 assert.deepEqual(l.issue(input),l.entries()[0]);assert.equal(l.summary().issued,1);
 assert.throws(()=>l.issue({...input,probability:.7}),/Conflicting/);
 assert.throws(()=>l.issue({...input,id:'b'}),/already issued/);
 const copy=l.entries();copy[0].probability=0;
 assert.equal(l.entries()[0].probability,.55);
});

test('a missing intermediate bar permanently voids all pending outcomes, never scores across gaps',()=>{
 clock.now=base+60;const l=ledger();l.receive(candle(base,100));
 l.issue({id:'a',modelVersion:'v1',horizon:3,probability:.6});
 clock.now=base+240;l.receive(candle(base+180,120));
 assert.equal(l.entries()[0].status,'VOID_GAP');assert.equal(l.entries()[0].outcomeUp,null);
 assert.equal(l.summary().settled,0);assert.equal(l.summary().voidGap,1);
 clock.now=base+300;l.receive(candle(base+240,150));
 assert.equal(l.entries()[0].status,'VOID_GAP');
});

test('rejects stale, future, misaligned, revised, out-of-order and wrong-source bars without mutation',()=>{
 clock.now=base+60;const l=ledger();l.receive(candle(base,100));
 const wrong={...identity,sourceId:'fixture-B'};
 assert.throws(()=>l.receive(candle(base+60,101,wrong)),/identity/);
 assert.throws(()=>l.receive(candle(base+1,100)),/aligned/);
 assert.throws(()=>l.receive(candle(base,101)),/revised/);
 assert.throws(()=>l.receive(candle(base-60,100)),/Out-of-order/);
 assert.throws(()=>l.receive(candle(base+60,101)),/Future/);
 clock.now=base+120+31;
 assert.throws(()=>l.receive(candle(base+60,101)),/stale/);
 assert.equal(l.entries().length,0);
 clock.now=base+120;l.receive(candle(base+60,101));
 assert.throws(()=>l.receive(candle(base,100)),/Out-of-order/);
});

test('stale issuance, clock rollback, invalid probabilities and horizons fail closed',()=>{
 clock.now=base+60;const l=ledger();
 assert.throws(()=>l.issue({id:'x',modelVersion:'v1',horizon:1,probability:.5}),/No recent/);
 l.receive(candle(base,100));
 assert.throws(()=>l.issue({id:'x',modelVersion:'v1',horizon:1,probability:1}),/Invalid/);
 assert.throws(()=>l.issue({id:'x',modelVersion:'v1',horizon:2 as 1,probability:.5}),/Invalid/);
 clock.now=base+91;
 assert.throws(()=>l.issue({id:'x',modelVersion:'v1',horizon:1,probability:.5}),/No recent/);
 clock.now=base+59;
 assert.throws(()=>l.issue({id:'x',modelVersion:'v1',horizon:1,probability:.5}),/Non-monotonic/);
});

test('flat close is not up; scored outcomes cannot be overwritten',()=>{
 clock.now=base+60;const l=ledger();l.receive(candle(base,100));
 l.issue({id:'x',modelVersion:'v1',horizon:1,probability:.8});
 clock.now=base+120;l.receive(candle(base+60,100));
 assert.equal(l.entries()[0].outcomeUp,false);
 assert.ok(Math.abs(l.summary().brier!-.64)<1e-12);
 assert.throws(()=>l.receive(candle(base+60,200)),/revised/);
 assert.ok(Math.abs(l.summary().brier!-.64)<1e-12);
});

test('rejects forecasts issued after the target close even when the base candle is within a permissive lag',()=>{
 clock.now=base+60;const l=new ForwardForecastLedger(identity,()=>clock.now,120);l.receive(candle(base,100));
 clock.now=base+120;
 assert.throws(()=>l.issue({id:'late',modelVersion:'v1',horizon:1,probability:.6}),/retroactive/);
 assert.equal(l.summary().issued,0);
});

test('long-horizon forecasts cannot be backdated after an unreceived next candle has closed',()=>{
 clock.now=base+60;const l=new ForwardForecastLedger(identity,()=>clock.now,3600);
 l.receive(candle(base,100));
 clock.now=base+119;
 const early=l.issue({id:'early',modelVersion:'v1',horizon:12,probability:.51});
 assert.equal(early.issuedAt,base+119);
 assert.equal(early.provider,identity.provider);
 assert.equal(early.venue,identity.venue);
 assert.equal(early.seconds,60);
 clock.now=base+120;
 assert.throws(()=>l.issue({id:'late-3',modelVersion:'v1',horizon:3,probability:.6}),/retroactive/);
 assert.throws(()=>l.issue({id:'late-12',modelVersion:'v2',horizon:12,probability:.6}),/retroactive/);
 assert.equal(l.summary().issued,1);
 assert.equal(l.issue({id:'early',modelVersion:'v1',horizon:12,probability:.51}).id,'early');
});


test('per-horizon scores keep settled, pending and losses separate',()=>{
 clock.now=base+60;const l=ledger();l.receive(candle(base,100));
 l.issue({id:'one',modelVersion:'v1',horizon:1,probability:.7});
 l.issue({id:'three',modelVersion:'v1',horizon:3,probability:.4});
 l.issue({id:'twelve',modelVersion:'v1',horizon:12,probability:.9});
 clock.now=base+120;l.receive(candle(base+60,101));
 clock.now=base+180;l.receive(candle(base+120,99));
 clock.now=base+240;l.receive(candle(base+180,100));
 const by=l.summaryByHorizon();
 assert.equal(by[1].settled,1);assert.equal(by[1].pending,0);
 assert.ok(Math.abs(by[1].brier!-.09)<1e-12);
 assert.equal(by[3].settled,1);assert.ok(Math.abs(by[3].brier!-.16)<1e-12);
 assert.equal(by[12].pending,1);assert.equal(by[12].brier,null);
 assert.equal(by[12].referenceBrier,null);
 assert.equal(l.summary().settled,2);
 assert.ok(Math.abs(l.summary().brier!-.125)<1e-12);
 by[1].brier=999;
 assert.ok(Math.abs(l.summaryByHorizon()[1].brier!-.09)<1e-12);
});

test('per-horizon gap invalidation cannot be mistaken for poor prediction',()=>{
 clock.now=base+60;const l=ledger();l.receive(candle(base,100));
 l.issue({id:'one',modelVersion:'v1',horizon:1,probability:.7});
 l.issue({id:'long',modelVersion:'v1',horizon:12,probability:.9});
 clock.now=base+240;l.receive(candle(base+180,102));
 const by=l.summaryByHorizon();
 assert.equal(by[1].voidGap,1);assert.equal(by[12].voidGap,1);
 assert.equal(by[1].settled,0);assert.equal(by[12].settled,0);
 assert.equal(by[1].brier,null);assert.equal(by[12].logLoss,null);
 assert.equal(by[3].issued,0);assert.equal(by[3].referenceBrier,null);
});

test('model and horizon grouping keeps opposite calibration scores separate',()=>{
 clock.now=base+60;const l=ledger();l.receive(candle(base,100));
 l.issue({id:'alpha1',modelVersion:'alpha',horizon:1,probability:.9});
 l.issue({id:'beta1',modelVersion:'beta',horizon:1,probability:.1});
 l.issue({id:'alpha3',modelVersion:'alpha',horizon:3,probability:.6});
 clock.now=base+120;l.receive(candle(base+60,110));
 const groups=l.summaryByModelAndHorizon();
 assert.deepEqual(groups.map(g=>[g.modelVersion,g.horizon]),[['alpha',1],['alpha',3],['beta',1]]);
 assert.ok(Math.abs(groups[0].summary.brier!-.01)<1e-12);
 assert.equal(groups[1].summary.pending,1);
 assert.equal(groups[1].summary.brier,null);
 assert.ok(Math.abs(groups[2].summary.brier!-.81)<1e-12);
 groups[0].summary.brier=999;
 assert.ok(Math.abs(l.summaryByModelAndHorizon()[0].summary.brier!-.01)<1e-12);
});
