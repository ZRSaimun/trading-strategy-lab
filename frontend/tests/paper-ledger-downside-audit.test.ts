import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditDisconnectedPaperDownside as audit} from '../lib/paper-ledger-downside-audit.ts';
import type {PaperEvent,PaperPolicy,PaperSource} from '../lib/disconnected-paper-ledger.ts';
const source:PaperSource={instrument:'XAUUSD-FIXTURE',provider:'fixture',venue:'test',sourceId:'feed-A',currency:'USD'};
const policy:PaperPolicy={startingCash:1000,maxNotional:500,maxQuoteAgeSeconds:5,markSlippageBps:0};
const q=(seq:number,at:number,bid:number,ask:number):PaperEvent=>({kind:'QUOTE',seq,at,source:{...source},bid,ask});
const o=(seq:number,at:number,id:string,side:'LONG'|'SHORT'='LONG'):PaperEvent=>({kind:'OPEN',seq,at,id,side,quantity:1,fee:1,slippageBps:0,quoteSeq:seq-1});
const c=(seq:number,at:number,id:string):PaperEvent=>({kind:'CLOSE',seq,at,id,fee:1,slippageBps:0,quoteSeq:seq-1});
const win:PaperEvent[]=[q(1,100,99,101),o(2,101,'A'),q(3,160,109,111),c(4,161,'A')];
test('empty journal abstains from per-trade metrics and never implies a return',()=>{
 const r=audit([],source,policy);
 assert.equal(r.closedTrades,0);assert.equal(r.profitFactor,null);
 assert.equal(r.averageClosedNetCash,null);assert.equal(r.medianClosedNetCash,null);
 assert.equal(r.worstClosedNetCash,null);assert.equal(r.realizedReturnPct,0);
 assert.equal(r.observedMaxUnderwaterSeconds,0);assert.equal(r.unrecoveredAtLastObservation,false);
 assert.equal(r.live,false);assert.equal(r.quoteAuthenticated,false);assert.equal(r.execution,'NONE');
});
test('single winner includes fees, drawdown, return and unbounded factor abstention',()=>{
 const r=audit(win,source,policy);
 assert.equal(r.closedTrades,1);assert.equal(r.realizedNetCash,6);
 assert.equal(r.realizedReturnPct,0.6);assert.equal(r.grossWinningCash,6);
 assert.equal(r.grossLosingCash,0);assert.equal(r.profitFactor,null);
 assert.equal(r.medianClosedNetCash,6);assert.equal(r.feesCash,2);
 assert.equal(r.observedMaxDrawdownCash,3);
 assert.equal(r.observedMaxUnderwaterSeconds,59);
 assert.equal(r.unrecoveredAtLastObservation,true); // closing fee leaves equity below prior marked peak
});
test('loss streak, gross profit/loss, median, factor and observed underwater are causal',()=>{
 const events:PaperEvent[]=[...win,
  q(5,200,99,101),o(6,201,'B'),q(7,260,94,96),c(8,261,'B'),
  q(9,300,99,101),o(10,301,'C'),q(11,360,94,96),c(12,361,'C')];
 const r=audit(events,source,policy);
 assert.equal(r.closedTrades,3);assert.equal(r.realizedNetCash,-12);
 assert.equal(r.grossWinningCash,6);assert.equal(r.grossLosingCash,18);
 assert.equal(r.profitFactor,1/3);assert.equal(r.maxConsecutiveLosses,2);
 assert.equal(r.worstClosedNetCash,-9);assert.equal(r.medianClosedNetCash,-9);
 assert.equal(r.averageClosedNetCash,-4);assert.equal(r.feesCash,6);
 assert.equal(r.unrecoveredAtLastObservation,true);
 assert.ok(r.observedMaxDrawdownCash>0);
 assert.ok(r.observedMaxUnderwaterSeconds>=160);
});
test('unclosed position stays unrealized; does not manufacture a closed trade',()=>{
 const r=audit([q(1,100,99,101),o(2,101,'A')],source,policy);
 assert.equal(r.closedTrades,0);assert.equal(r.openPositions,1);
 assert.equal(r.realizedNetCash,0);assert.equal(r.unrealizedNetCash,-3);
 assert.equal(r.markToMarketReturnPct,-0.3);
 assert.equal(r.profitFactor,null);assert.equal(r.unrecoveredAtLastObservation,true);
});
test('a short loss uses actual quote side, fees and non-positive profit factor',()=>{
 const r=audit([q(1,100,99,101),o(2,101,'S','SHORT'),q(3,160,109,111),c(4,161,'S')],source,policy);
 assert.equal(r.realizedNetCash,-14);assert.equal(r.grossLosingCash,14);
 assert.equal(r.profitFactor,0);assert.equal(r.maxConsecutiveLosses,1);
});
test('quote gaps, stale references, mixed sources and crossed spreads fail closed',()=>{
 assert.throws(()=>audit([q(1,100,99,101),o(2,110,'A')],source,policy));
 assert.throws(()=>audit([q(1,100,101,100)],source,policy));
 assert.throws(()=>audit([{...q(1,100,99,101),source:{...source,sourceId:'B'}} as PaperEvent],source,policy));
 assert.throws(()=>audit([q(1,100,99,101),{...o(2,101,'A'),quoteSeq:99} as PaperEvent],source,policy));
});
test('replay is deterministic and does not mutate the input event journal',()=>{
 const events=[...win],before=structuredClone(events);
 assert.deepEqual(audit(events,source,policy),audit(events,source,policy));
 assert.deepEqual(events,before);
});
