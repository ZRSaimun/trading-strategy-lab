import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditPaperValuationFreshness as audit} from '../lib/paper-valuation-freshness.ts';
import type {PaperEvent,PaperPolicy,PaperSource} from '../lib/disconnected-paper-ledger.ts';
const t=1800000000;
const source:PaperSource={instrument:'SYNTHETIC-XAU',provider:'fixture',venue:'offline',sourceId:'A',currency:'USD'};
const policy:PaperPolicy={startingCash:10000,maxNotional:5000,maxQuoteAgeSeconds:20,markSlippageBps:5};
const q=(seq:number,at:number,bid=99,ask=101):PaperEvent=>({seq,at,kind:'QUOTE',source:{...source},bid,ask});
const open=(seq:number,at:number,quoteSeq:number):PaperEvent=>({seq,at,kind:'OPEN',id:'a',side:'LONG',quantity:1,fee:1,slippageBps:0,quoteSeq});
const close=(seq:number,at:number,quoteSeq:number):PaperEvent=>({seq,at,kind:'CLOSE',id:'a',fee:1,slippageBps:0,quoteSeq});
const openEvents=()=>[q(1,t),open(2,t+1,1)];
test('open mark within freshness boundary is research-only and never executable',()=>{
 const x=audit(openEvents(),source,policy,t+120,120);
 assert.equal(x.status,'RECENT_UNAUTHENTICATED_MARK');
 assert.equal(x.quoteAgeSeconds,120);
 assert.equal(x.positionOpen,true);
 assert.equal(x.asOfResearchEquity,x.lastObservedEquity);
 assert.deepEqual([x.live,x.persisted,x.quoteAuthenticated,x.executableQuoteAvailable,x.orderPreviewEnabled,x.ordersSubmitted],
   [false,false,false,false,false,0]);
});
test('stale open position suppresses current equity and unrealized P&L',()=>{
 const x=audit(openEvents(),source,policy,t+121,120);
 assert.equal(x.status,'STALE_OPEN_MARK');
 assert.equal(x.asOfResearchEquity,null);
 assert.equal(x.asOfResearchUnrealizedNet,null);
 assert.equal(typeof x.lastObservedEquity,'number');
});
test('a newer quote refreshes freshness without changing source authenticity',()=>{
 const events=[...openEvents(),q(3,t+100,98,100)];
 const x=audit(events,source,policy,t+110,10);
 assert.equal(x.status,'RECENT_UNAUTHENTICATED_MARK');
 assert.equal(x.quoteAgeSeconds,10);
 assert.equal(x.quoteAuthenticated,false);
});
test('flat closed portfolio exposes realized cash even when last quote is old',()=>{
 const events=[...openEvents(),q(3,t+10,102,104),close(4,t+11,3)];
 const x=audit(events,source,policy,t+5000,0);
 assert.equal(x.status,'FLAT_REALIZED_ONLY');
 assert.equal(x.asOfResearchEquity,policy.startingCash+x.realizedNet);
 assert.equal(x.asOfResearchUnrealizedNet,0);
});
test('empty journal is flat with no fabricated quote age',()=>{
 const x=audit([],source,policy,t);
 assert.equal(x.status,'FLAT_REALIZED_ONLY');
 assert.equal(x.lastQuoteAt,null);
 assert.equal(x.quoteAgeSeconds,null);
 assert.equal(x.asOfResearchEquity,10000);
});
test('zero freshness limit only permits exact quote timestamp',()=>{
 assert.equal(audit(openEvents(),source,policy,t+1,0).status,'STALE_OPEN_MARK');
 assert.equal(audit([q(1,t),open(2,t,1)],source,policy,t,0).status,'RECENT_UNAUTHENTICATED_MARK');
});
test('future-dated quote and open are rejected, not treated as recent',()=>{
 assert.throws(()=>audit(openEvents(),source,policy,t));
 assert.throws(()=>audit([q(1,t+10)],source,policy,t));
});
test('invalid clocks and freshness policies fail closed',()=>{
 for(const asOf of [-1,NaN,Infinity,1.5,Number.MAX_SAFE_INTEGER+1])
   assert.throws(()=>audit(openEvents(),source,policy,asOf));
 for(const maxAge of [-1,NaN,Infinity,1.5,3601])
   assert.throws(()=>audit(openEvents(),source,policy,t+2,maxAge));
});
test('replay rejects crossed/mixed-source quotes and duplicate sequence',()=>{
 assert.throws(()=>audit([q(1,t,102,101)],source,policy,t+1));
 const wrong=q(1,t);if(wrong.kind==='QUOTE')wrong.source.sourceId='B';
 assert.throws(()=>audit([wrong],source,policy,t+1));
 assert.throws(()=>audit([q(1,t),q(1,t+1)],source,policy,t+1));
});
test('stale quote cannot authorize a simulated close via freshness audit',()=>{
 const events=[...openEvents(),q(3,t+10,102,104),close(4,t+50,3)];
 assert.throws(()=>audit(events,source,policy,t+100));
});
test('same inputs replay deterministically without mutation',()=>{
 const events=openEvents(),before=JSON.stringify(events);
 assert.deepEqual(audit(events,source,policy,t+20),audit(events,source,policy,t+20));
 assert.equal(JSON.stringify(events),before);
});
