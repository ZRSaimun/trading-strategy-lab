import {test} from 'node:test';
import assert from 'node:assert/strict';
import {replayDisconnectedPaperLedger as replay} from '../lib/disconnected-paper-ledger.ts';
import type {PaperEvent,PaperPolicy,PaperSource} from '../lib/disconnected-paper-ledger.ts';
const source:PaperSource={instrument:'XAUUSD-FIXTURE',provider:'fixture',venue:'test',sourceId:'feed-A',currency:'USD'};
const policy:PaperPolicy={startingCash:1000,maxNotional:500,maxQuoteAgeSeconds:5,markSlippageBps:0};
const q=(seq:number,at:number,bid:number,ask:number):PaperEvent=>({kind:'QUOTE',seq,at,source:{...source},bid,ask});
const o=(seq:number,at:number,id='A',side:'LONG'|'SHORT'='LONG'):PaperEvent=>({kind:'OPEN',seq,at,id,side,quantity:1,fee:1,slippageBps:0,quoteSeq:seq-1});
const c=(seq:number,at:number,id='A'):PaperEvent=>({kind:'CLOSE',seq,at,id,fee:1,slippageBps:0,quoteSeq:seq-1});
const long=():PaperEvent[]=>[q(1,100,99,101),o(2,101),q(3,160,109,111),c(4,161)];
test('offline long uses ask entry, bid exit, both fees and drawdown',()=>{
 const r=replay(long(),source,policy);
 assert.equal(r.mode,'UNVERIFIED_LOCAL_RESEARCH');assert.equal(r.live,false);
 assert.equal(r.quoteAuthenticated,false);assert.equal(r.persisted,false);assert.equal(r.ordersSubmitted,0);
 assert.equal(r.realizedNet,6);assert.equal(r.equity,1006);
 assert.equal(r.maxDrawdownCash,3);assert.equal(r.winRate,1);
 assert.deepEqual(r.snapshots.map(s=>s.equity),[1000,997,1007,1006]);
 assert.equal(r.closedTrades[0].entryPrice,101);assert.equal(r.closedTrades[0].exitPrice,109);
});
test('short sells at bid and covers at ask; open mark includes spread',()=>{
 const r=replay([q(1,100,99,101),o(2,101,'S','SHORT'),q(3,160,89,91),c(4,161,'S')],source,policy);
 assert.equal(r.snapshots[1].equity,997);assert.equal(r.realizedNet,6);
 assert.equal(r.closedTrades[0].side,'SHORT');
});
test('open trade is marked to liquidation side and never counted as a closed win',()=>{
 const r=replay([q(1,100,99,101),o(2,101)],source,policy);
 assert.equal(r.realizedNet,0);assert.equal(r.unrealizedNet,-3);
 assert.equal(r.equity,997);assert.equal(r.winRate,null);assert.equal(r.openPosition?.id,'A');
});
test('empty journal reports zero trades and no invented return',()=>{
 const r=replay([],source,policy);
 assert.equal(r.equity,1000);assert.equal(r.winRate,null);
 assert.equal(r.maxDrawdownCash,0);assert.equal(r.quotes,0);
});
test('mixed feed and crossed quotes fail closed',()=>{
 const events=long();
 assert.throws(()=>replay([{...events[0],source:{...source,sourceId:'other'}} as PaperEvent],source,policy));
 assert.throws(()=>replay([q(1,100,101,100)],source,policy));
 assert.throws(()=>replay([q(1,100,0,101)],source,policy));
});
test('no retroactive, stale or nonexistent quote references',()=>{
 assert.throws(()=>replay([o(1,100)],source,policy));
 assert.throws(()=>replay([q(1,100,99,101),o(2,106)],source,policy));
 assert.throws(()=>replay([q(1,100,99,101),{...o(2,101),quoteSeq:0} as PaperEvent],source,policy));
 assert.throws(()=>replay([q(1,100,99,101),o(2,99)],source,policy));
});
test('journal sequence and quote-time monotonicity are enforced',()=>{
 assert.throws(()=>replay([q(2,100,99,101)],source,policy));
 assert.throws(()=>replay([q(1,100,99,101),q(2,100,99,101)],source,policy));
 assert.throws(()=>replay([q(1,100,99,101),q(2,99,99,101)],source,policy));
 assert.throws(()=>replay([q(1,100,99,101),{...o(2,101),seq:4} as PaperEvent],source,policy));
});
test('same-quote roundtrip, wrong trade id and duplicate close are rejected',()=>{
 assert.throws(()=>replay([q(1,100,99,101),o(2,101),{...c(3,102),quoteSeq:1} as PaperEvent],source,policy));
 assert.throws(()=>replay([q(1,100,99,101),o(2,101),q(3,160,109,111),c(4,161,'wrong')],source,policy));
 assert.throws(()=>replay([...long(),q(5,200,109,111),c(6,201)],source,policy));
});
test('cannot overlap positions or reuse a completed trade id',()=>{
 assert.throws(()=>replay([q(1,100,99,101),o(2,101),q(3,160,99,101),o(4,161,'B')],source,policy));
 assert.throws(()=>replay([...long(),q(5,200,99,101),o(6,201)],source,policy));
});
test('cash, notional, quantity, fees and slippage limits fail closed',()=>{
 const base=[q(1,100,99,101),o(2,101)];
 assert.throws(()=>replay(base,source,{...policy,maxNotional:100}));
 assert.throws(()=>replay(base,source,{...policy,startingCash:100}));
 assert.throws(()=>replay([base[0],{...base[1],quantity:0} as PaperEvent],source,policy));
 assert.throws(()=>replay([base[0],{...base[1],fee:-1} as PaperEvent],source,policy));
 assert.throws(()=>replay([base[0],{...base[1],slippageBps:501} as PaperEvent],source,policy));
});
test('configured exit marking slippage worsens open equity',()=>{
 const r=replay([q(1,100,99,101),o(2,101)],source,{...policy,markSlippageBps:100});
 assert.ok(r.equity<997);
});
test('slippage, loss and fees reduce closed net returns',()=>{
 const events:PaperEvent[]=[q(1,100,99,101),{...o(2,101),slippageBps:100} as PaperEvent,
  q(3,160,90,92),{...c(4,161),slippageBps:100} as PaperEvent];
 const r=replay(events,source,policy);
 assert.ok(r.realizedNet<-13);assert.equal(r.winRate,0);
 assert.ok(r.maxDrawdownCash>0);assert.equal(r.totalFees,2);
});
test('replay deterministic and source result cannot mutate caller',()=>{
 const events=long(),a=replay(events,source,policy),b=replay(events,source,policy);
 assert.deepEqual(a,b);a.source.sourceId='changed';assert.equal(source.sourceId,'feed-A');
});
