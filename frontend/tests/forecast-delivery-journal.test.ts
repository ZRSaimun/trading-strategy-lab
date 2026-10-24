import {test} from 'node:test';
import assert from 'node:assert/strict';
import {replayForecastDeliveryJournal} from '../lib/forecast-delivery-journal.ts';
import type {DeliveryJournalEvent} from '../lib/forecast-delivery-journal.ts';
import type {ForecastReviewCandidate} from '../lib/forecast-review-outbox.ts';
const identity={instrument:'XAUUSD-TEST',provider:'fixture',venue:'fixture',sourceId:'source-A',priceSide:'bid' as const,seconds:60};
const close=1800000060;
const id=JSON.stringify([JSON.stringify([identity.instrument,identity.provider,identity.venue,identity.sourceId,identity.priceSide,identity.seconds]),'v1',3,close]);
const candidate:ForecastReviewCandidate={id,kind:'FORECAST_CALIBRATION_REVIEW',mode:'UNVERIFIED_LOCAL_RESEARCH',
 live:false,delivery:'NOT_CONNECTED',execution:'NONE',quoteTimestamp:null,identity,
 modelVersion:'v1',horizon:3,latestTargetClose:close,earlierBrier:.1,recentBrier:.3,deltaBrier:.2,
 reasons:['Offline score degradation.']};
const queued:DeliveryJournalEvent={seq:1,at:close,id,action:'QUEUED',candidate};
const claim:DeliveryJournalEvent={seq:2,at:close+1,id,action:'CLAIMED',attemptId:'attempt-1'};
const ack:DeliveryJournalEvent={seq:3,at:close+2,id,action:'ACK_RECORDED',attemptId:'attempt-1',receiptId:'self-reported-1'};
const run=(xs:DeliveryJournalEvent[],now=close+100)=>replayForecastDeliveryJournal(xs,now);
test('empty replay is offline and has zero counts',()=>{
 assert.deepEqual(run([]).counts,{pending:0,inFlight:0,ackRecorded:0,cancelled:0});
 assert.equal(run([]).transportConnected,false);
});
test('queued review stays pending, claim never auto-retries after restart',()=>{
 assert.equal(run([queued]).entries[0].status,'PENDING');
 const first=run([queued,claim]);
 assert.equal(first.entries[0].status,'IN_FLIGHT_NEEDS_RECONCILIATION');
 assert.deepEqual(run([queued,claim]),first);
 assert.equal(first.counts.inFlight,1);
});
test('self-reported ACK is not verified transport delivery',()=>{
 const out=run([queued,claim,ack]);
 assert.equal(out.entries[0].status,'ACK_RECORDED_UNVERIFIED');
 assert.equal(out.counts.ackRecorded,1);
 assert.throws(()=>run([queued,claim,ack,{seq:4,at:close+3,id,action:'CLAIMED',attemptId:'attempt-2'}]));
});
test('release requires reason, and retry must use a new attempt ID',()=>{
 const release:DeliveryJournalEvent={seq:3,at:close+2,id,action:'RELEASED',attemptId:'attempt-1',reason:'transport failure'};
 assert.equal(run([queued,claim,release]).counts.pending,1);
 assert.throws(()=>run([queued,claim,release,{...claim,seq:4,at:close+3}]));
 assert.equal(run([queued,claim,release,{...claim,seq:4,at:close+3,attemptId:'attempt-2'}]).counts.inFlight,1);
});
test('duplicate enqueue, unknown candidate, skipped sequence rejected',()=>{
 assert.throws(()=>run([queued,{...queued,seq:2,at:close+1}]));
 assert.throws(()=>run([claim]));
 assert.throws(()=>run([queued,{...claim,seq:3}]));
});
test('future, out-of-order timestamps and early queue rejected',()=>{
 assert.throws(()=>run([queued],close-1));
 assert.throws(()=>run([{...queued,at:close-1}]));
 assert.throws(()=>run([queued,{...claim,at:close-1}]));
});
test('candidate source identity and immutable event metadata checked',()=>{
 assert.throws(()=>run([{...queued,candidate:{...candidate,identity:{...identity,sourceId:'other'}}}]));
 assert.throws(()=>run([{...queued,candidate:{...candidate,live:true as false}}]));
 assert.throws(()=>run([{...queued,candidate:{...candidate,deltaBrier:.5}}]));
 assert.throws(()=>run([{...queued,attemptId:'bad'}]));
});
test('claim and ACK require matching attempt and receipt, cancellation is final',()=>{
 assert.throws(()=>run([queued,{...ack,seq:2}]));
 assert.throws(()=>run([queued,claim,{...ack,attemptId:'wrong'}]));
 assert.throws(()=>run([queued,claim,{...ack,receiptId:''}]));
 const cancelled:DeliveryJournalEvent={seq:2,at:close+1,id,action:'CANCELLED',reason:'operator review'};
 assert.equal(run([queued,cancelled]).counts.cancelled,1);
 assert.throws(()=>run([queued,cancelled,{...claim,seq:3,at:close+2}]));
 assert.throws(()=>run([queued,claim,{...cancelled,seq:3,at:close+2}]));
});
