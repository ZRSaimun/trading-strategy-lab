import {test} from 'node:test';
import assert from 'node:assert/strict';
import {PaperExecutionLedger,type PaperRequest,type PaperQuote} from '../lib/paper-execution.ts';
const identity={instrument:'XAUUSD-CFD-BROKER-A',provider:'Broker A demo',venue:'Broker A OTC',priceSide:'bid-ask' as const,pointValue:1};
const q=(observedAt:number,bid=100,ask=100.2,receivedAt=observedAt):PaperQuote=>({instrument:identity.instrument,provider:identity.provider,venue:identity.venue,observedAt,receivedAt,bid,ask});
const req=(changes:Partial<PaperRequest>={}):PaperRequest=>({clientOrderId:'paper-001',instrument:identity.instrument,side:'BUY',units:2,submittedAt:100,expiresAt:500,stop:99,target:102,maxSpread:0.5,maxQuoteAgeSeconds:2,maxStopRiskCurrency:10,adverseSlippagePerSide:0.1,commissionPerUnitSide:0.05,...changes});

test('requires a strictly subsequent fresh bid/ask quote and calculates real-sided entry/exit',()=>{
 const l=new PaperExecutionLedger(identity);l.onQuote(q(100));l.submit(req());
 assert.deepEqual(l.onQuote(q(101,100,100.2,104)),[]); // stale
 assert.deepEqual(l.onQuote(q(102,100,100.2,104)).map(e=>e.status),['OPEN']);
 assert.equal(l.get('paper-001')?.entry,100.3);
 assert.deepEqual(l.onQuote(q(103,102.2,102.4,105)).map(e=>e.status),['CLOSED']);
 const order=l.get('paper-001')!;
 assert.equal(order.exit,102);assert.ok(Math.abs(order.pnl!-3.2)<1e-9);
 assert.equal(order.costs,0.2);
 assert.equal(l.history().length,2);
});
test('buy and sell stops fill at worse observed bid/ask after gaps, not at guaranteed stop',()=>{
 const buy=new PaperExecutionLedger(identity);buy.submit(req());buy.onQuote(q(101));buy.onQuote(q(102,97,97.2));
 assert.equal(buy.get('paper-001')?.exit,96.9);
 assert.ok(buy.get('paper-001')!.pnl! < -6);
 const sell=new PaperExecutionLedger(identity);sell.submit(req({side:'SELL',stop:101,target:98}));sell.onQuote(q(101));sell.onQuote(q(102,104,104.2));
 assert.equal(sell.get('paper-001')?.entry,99.9);
 assert.equal(sell.get('paper-001')?.exit,104.3);
 assert.ok(sell.get('paper-001')!.pnl! < -8);
});
test('duplicate client order is idempotent, conflicting duplicate and overlapping orders rejected',()=>{
 const l=new PaperExecutionLedger(identity);l.submit(req());assert.deepEqual(l.submit(req()),l.get('paper-001'));
 assert.deepEqual(l.submit(Object.fromEntries(Object.entries(req()).reverse()) as unknown as PaperRequest),l.get('paper-001'));
 assert.throws(()=>l.submit(req({units:3})),/Conflicting/);
 assert.throws(()=>l.submit(req({clientOrderId:'paper-002'})),/overlapping/);
 l.cancel('paper-001',100);assert.equal(l.get('paper-001')?.status,'CANCELED');
 assert.throws(()=>l.cancel('paper-001',101),/Only pending/);
 assert.deepEqual(l.onQuote(q(101)),[]);
});
test('invalid and out-of-order quotes fail without corrupting the ledger',()=>{
 const l=new PaperExecutionLedger(identity);l.submit(req());
 assert.throws(()=>l.onQuote({...q(101),provider:'wrong'}),/identity/);
 assert.throws(()=>l.onQuote(q(101,100.5,100.1)),/Invalid/);
 assert.throws(()=>l.onQuote(q(101,100,100.2,100)),/Invalid/);
 assert.deepEqual(l.onQuote(q(101)).map(e=>e.status),['OPEN']);
 assert.throws(()=>l.onQuote(q(101)),/non-monotonic/);
 assert.equal(l.get('paper-001')?.status,'OPEN');
});
test('wide spreads block entry, and excessive estimated stop loss rejects without a fill',()=>{
 const l=new PaperExecutionLedger(identity);l.submit(req({maxStopRiskCurrency:1}));
 assert.deepEqual(l.onQuote(q(101,100,101)),[]);
 assert.deepEqual(l.onQuote(q(102,100,100.2)).map(e=>e.status),['REJECTED']);
 assert.equal(l.get('paper-001')?.entry,undefined);
});
test('pending orders expire without fills, and retroactive cancellation is refused',()=>{
 const l=new PaperExecutionLedger(identity);l.onQuote(q(99));l.submit(req({expiresAt:102}));
 assert.throws(()=>l.cancel('paper-001',98),/Retroactive/);
 assert.deepEqual(l.onQuote(q(103)).map(e=>e.status),['EXPIRED']);
 assert.equal(l.get('paper-001')?.entry,undefined);
});
test('stale quotes cannot close an open position; adverse wide spread does not suppress protective exit',()=>{
 const l=new PaperExecutionLedger(identity);l.submit(req());l.onQuote(q(101));
 assert.deepEqual(l.onQuote(q(102,95,96,110)),[]); // stale despite price crossing stop
 assert.equal(l.get('paper-001')?.status,'OPEN');
 assert.deepEqual(l.onQuote(q(111,95,96,111)).map(e=>e.status),['CLOSED']);
 assert.equal(l.get('paper-001')?.exit,94.9);
});
test('future bars cannot change already-settled paper order results and source identity is mandatory',()=>{
 const l=new PaperExecutionLedger(identity);l.submit(req());l.onQuote(q(101));l.onQuote(q(102,102.5,102.7));
 const prior=l.get('paper-001');l.onQuote(q(103,80,80.5));assert.deepEqual(l.get('paper-001'),prior);
 assert.throws(()=>new PaperExecutionLedger({...identity,priceSide:'bid' as 'bid-ask'}),/identity/);
});
test('an already-observed quote cannot fill a new order, even if received later',()=>{
 const l=new PaperExecutionLedger(identity);l.submit(req());
 assert.deepEqual(l.onQuote(q(99,100,100.2,101)),[]);
 assert.equal(l.get('paper-001')?.status,'PENDING');
 assert.deepEqual(l.onQuote(q(102,100,100.2,102)).map(e=>e.status),['OPEN']);
});
test('SELL target closes using ask, and invalid brackets reject at entry',()=>{
 const sell=new PaperExecutionLedger(identity);sell.submit(req({side:'SELL',stop:101,target:98}));
 sell.onQuote(q(101));sell.onQuote(q(102,97,97.5));
 assert.equal(sell.get('paper-001')?.exit,98);
 const invalid=new PaperExecutionLedger(identity);invalid.submit(req({stop:101,target:102}));
 assert.deepEqual(invalid.onQuote(q(101)).map(e=>e.status),['REJECTED']);
 assert.equal(invalid.get('paper-001')?.entry,undefined);
});

test('future-dated cancellation prevents older quotes from rewriting paper history',()=>{
 const l=new PaperExecutionLedger(identity);
 l.submit(req());
 l.cancel('paper-001',200);
 assert.throws(()=>l.onQuote(q(150)),/non-monotonic/);
 assert.equal(l.get('paper-001')?.status,'CANCELED');
 assert.deepEqual(l.history().map(e=>e.status),['CANCELED']);
 // An older submission must not be inserted after a future-dated cancel.
 assert.throws(()=>l.submit(req({clientOrderId:'paper-002',submittedAt:150})),/retroactive/);
 // Idempotent replay of the original request is allowed but cannot reopen it.
 assert.equal(l.submit(req()).status,'CANCELED');
 l.submit(req({clientOrderId:'paper-002',submittedAt:200,expiresAt:500}));
 assert.deepEqual(l.onQuote(q(201)).map(e=>e.status),['OPEN']);
 assert.equal(l.get('paper-001')?.status,'CANCELED');
});
test('quotes received before a submitted paper request cannot be processed afterward',()=>{
 const l=new PaperExecutionLedger(identity);
 l.onQuote(q(99));
 l.submit(req({submittedAt:150,expiresAt:300}));
 assert.throws(()=>l.onQuote(q(101,100,100.2,120)),/non-monotonic/);
 assert.equal(l.get('paper-001')?.status,'PENDING');
 assert.deepEqual(l.onQuote(q(151,100,100.2,151)).map(e=>e.status),['OPEN']);
});
test('rejected time-travel events do not advance the paper event clock',()=>{
 const l=new PaperExecutionLedger(identity);
 l.submit(req());
 l.cancel('paper-001',200);
 assert.throws(()=>l.onQuote(q(150)),/non-monotonic/);
 // This request is chronological and should remain valid after the rejection.
 l.submit(req({clientOrderId:'paper-002',submittedAt:200,expiresAt:500}));
 assert.deepEqual(l.onQuote(q(201)).map(e=>e.status),['OPEN']);
});


test('impossible adverse gap fill never creates a negative executable price or closes the paper position',()=>{
 const l=new PaperExecutionLedger(identity);
 l.submit(req());
 assert.deepEqual(l.onQuote(q(101)).map(e=>e.status),['OPEN']);
 const before=l.get('paper-001');
 // A quoted positive bid smaller than the fixed adverse slippage would
 // otherwise manufacture a negative fill price.
 assert.throws(()=>l.onQuote(q(102,0.05,0.06)),/Invalid hypothetical exit price/);
 assert.deepEqual(l.get('paper-001'),before);
 assert.deepEqual(l.history().map(e=>e.status),['OPEN']);
 // The rejected event did not advance the clock: a corrected quote at the
 // same timestamp may still close the simulated position.
 assert.deepEqual(l.onQuote(q(102,98,98.2)).map(e=>e.status),['CLOSED']);
 assert.ok(l.get('paper-001')!.exit!>0);
});

test('overflowing paper P&L cannot settle as Infinity or consume the quote timestamp',()=>{
 const huge={...identity,pointValue:1e308};
 const l=new PaperExecutionLedger(huge);
 l.submit(req({units:1,stop:99.9,target:1e308,maxStopRiskCurrency:1e308,commissionPerUnitSide:0}));
 assert.deepEqual(l.onQuote(q(101)).map(e=>e.status),['OPEN']);
 const before=l.get('paper-001');
 // Stop risk is finite, but a target at the edge of finite price range
 // multiplies to non-finite gross P&L.
 assert.throws(()=>l.onQuote(q(102,1e308,1e308)),/Non-finite paper exit arithmetic/);
 assert.deepEqual(l.get('paper-001'),before);
 assert.deepEqual(l.history().map(e=>e.status),['OPEN']);
 assert.deepEqual(l.onQuote(q(102,99,99.2)).map(e=>e.status),['CLOSED']);
 assert.ok(Number.isFinite(l.get('paper-001')!.pnl));
});

test('underflowed initial stop risk is not accepted as zero-risk exposure',()=>{
 const l=new PaperExecutionLedger({...identity,pointValue:Number.MIN_VALUE});
 l.submit(req({units:Number.MIN_VALUE,commissionPerUnitSide:0,maxStopRiskCurrency:1}));
 assert.deepEqual(l.onQuote(q(101)).map(e=>e.status),['REJECTED']);
 const o=l.get('paper-001')!;
 assert.equal(o.status,'REJECTED');
 assert.equal(o.entry,undefined);
 assert.match(o.reason||'',/unrepresentable/);
});
