import {test} from 'node:test';
import assert from 'node:assert/strict';
import {PaperReplayJournal,PersistentPaperSession,type PaperCheckpointStore,type StoredPaperCheckpoint} from '../lib/paper-replay-journal.ts';
import type {PaperRequest,PaperQuote} from '../lib/paper-execution.ts';
const identity={instrument:'XAUUSD-DEMO-A',provider:'Demo A',venue:'Demo OTC',priceSide:'bid-ask' as const,pointValue:1};
const req=(id='a'):PaperRequest=>({clientOrderId:id,instrument:identity.instrument,side:'BUY',units:2,
 submittedAt:100,expiresAt:500,stop:99,target:102,maxSpread:.5,maxQuoteAgeSeconds:2,
 maxStopRiskCurrency:10,adverseSlippagePerSide:.1,commissionPerUnitSide:.05});
const q=(at:number,bid=100,ask=100.2):PaperQuote=>({instrument:identity.instrument,provider:identity.provider,
 venue:identity.venue,observedAt:at,receivedAt:at,bid,ask});
function store():PaperCheckpointStore&{current:StoredPaperCheckpoint|null;fail:boolean}{
 return {current:null,fail:false,async load(){return this.current},async compareAndSwap(expected,next){
   if(this.fail||this.current?.revision!==expected && !(this.current===null&&expected===null))return false;
   this.current={...next};return true;
 }};
}
test('replays accepted quotes including no-fill quotes and settled BUY order identically',()=>{
 const j=new PaperReplayJournal(identity);j.submit(req());j.onQuote(q(101));j.onQuote(q(102,101,101.2));j.onQuote(q(103,102.3,102.5));
 const restored=PaperReplayJournal.restore(j.serialize());
 assert.equal(restored.get('a')?.status,'CLOSED');
 assert.deepEqual(restored.checkpoint(),j.checkpoint());
 assert.equal(restored.checkpoint().actions.length,4);
});
test('duplicate client ID retry is idempotent and not journaled twice',()=>{
 const j=new PaperReplayJournal(identity);j.submit(req());j.submit(req());
 assert.equal(j.checkpoint().actions.length,1);
 assert.throws(()=>j.submit({...req(),units:3}),/Conflicting/);
 assert.equal(j.checkpoint().actions.length,1);
});
test('corrupt closed P&L and omitted quote are detected by replay',()=>{
 const j=new PaperReplayJournal(identity);j.submit(req());j.onQuote(q(101));j.onQuote(q(102,102.3,102.5));
 const bad=JSON.parse(j.serialize());bad.orders[0].pnl=999;
 assert.throws(()=>PaperReplayJournal.restore(JSON.stringify(bad)),/does not match/);
 const missing=JSON.parse(j.serialize());missing.actions.splice(1,1);
 assert.throws(()=>PaperReplayJournal.restore(JSON.stringify(missing)),/replay failed|does not match/);
});
test('unknown fields, unknown action, retroactive quote and invalid JSON fail closed',()=>{
 const j=new PaperReplayJournal(identity);j.submit(req());
 const bad=JSON.parse(j.serialize());bad.actions[0].request.brokerPassword='secret';
 assert.throws(()=>PaperReplayJournal.restore(JSON.stringify(bad)),/Unknown action/);
 const invalid=JSON.parse(j.serialize());invalid.actions[0].kind='ORDER_NOW';
 assert.throws(()=>PaperReplayJournal.restore(JSON.stringify(invalid)),/Unknown action/);
 assert.throws(()=>PaperReplayJournal.restore('{broken'),/JSON/);
 assert.throws(()=>j.onQuote(q(90)),/non-monotonic|Invalid/);
 assert.equal(j.checkpoint().actions.length,1);
});
test('failed impossible quote does not persist an event or consume timestamp',()=>{
 const j=new PaperReplayJournal(identity);j.submit(req());j.onQuote(q(101));
 assert.throws(()=>j.onQuote(q(102,.05,.06)),/Invalid hypothetical exit price/);
 assert.equal(j.checkpoint().actions.length,2);
 j.onQuote(q(102,98,98.2));
 assert.equal(j.get('a')?.status,'CLOSED');
});
test('persisted journal survives restart and continues with chronological quotes',async()=>{
 const s=store();const first=await PersistentPaperSession.open(identity,s);
 await first.apply({kind:'SUBMIT',request:req()});await first.apply({kind:'QUOTE',quote:q(101)});
 const afterRestart=await PersistentPaperSession.open(identity,s);
 assert.equal(afterRestart.get('a')?.status,'OPEN');
 await afterRestart.apply({kind:'QUOTE',quote:q(102,102.3,102.5)});
 assert.equal((await PersistentPaperSession.open(identity,s)).get('a')?.status,'CLOSED');
});
test('atomic CAS conflict and failed persistence never publish uncommitted fills',async()=>{
 const s=store();const a=await PersistentPaperSession.open(identity,s);
 const b=await PersistentPaperSession.open(identity,s);
 await a.apply({kind:'SUBMIT',request:req()});
 await assert.rejects(()=>b.apply({kind:'SUBMIT',request:req('b')}),/Concurrent/);
 assert.equal(b.get('b'),undefined);
 s.fail=true;
 await assert.rejects(()=>a.apply({kind:'QUOTE',quote:q(101)}),/Concurrent/);
 assert.equal(a.get('a')?.status,'PENDING');
 assert.equal((await PersistentPaperSession.open(identity,s)).get('a')?.status,'PENDING');
});
test('stored source identity and altered settlement chronology fail before resuming',async()=>{
 const s=store();const a=await PersistentPaperSession.open(identity,s);
 await a.apply({kind:'SUBMIT',request:req()});
 await assert.rejects(()=>PersistentPaperSession.open({...identity,venue:'Different venue'},s),/identity mismatch/);
 const bad=JSON.parse(s.current!.json);bad.orders[0].submittedAt=500;
 s.current={...s.current!,json:JSON.stringify(bad)};
 await assert.rejects(()=>PersistentPaperSession.open(identity,s),/does not match/);
});
