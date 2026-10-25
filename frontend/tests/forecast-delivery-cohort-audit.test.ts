import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditForecastDeliveryCohort} from '../lib/forecast-delivery-cohort-audit.ts';
import type {DeclaredReviewCandidate,DeliveryCohortPolicy} from '../lib/forecast-delivery-cohort-audit.ts';
import type {DeliveryJournalEvent} from '../lib/forecast-delivery-journal.ts';
import type {ForecastReviewCandidate} from '../lib/forecast-review-outbox.ts';
const identity={instrument:'XAUUSD-TEST',provider:'fixture',venue:'fixture',sourceId:'source-A',priceSide:'bid' as const,seconds:60};
const close=1800000060;
const make=(target:number,model='v1'):{planned:DeclaredReviewCandidate,candidate:ForecastReviewCandidate}=>{
 const id=JSON.stringify([JSON.stringify([identity.instrument,identity.provider,identity.venue,identity.sourceId,identity.priceSide,identity.seconds]),model,3,target]);
 return {planned:{id,latestTargetClose:target},candidate:{id,kind:'FORECAST_CALIBRATION_REVIEW',mode:'UNVERIFIED_LOCAL_RESEARCH',
 live:false,delivery:'NOT_CONNECTED',execution:'NONE',quoteTimestamp:null,identity,modelVersion:model,horizon:3,
 latestTargetClose:target,earlierBrier:.1,recentBrier:.3,deltaBrier:.2,reasons:['Review synthetic degradation.']}};
};
const a=make(close),b=make(close+180),c=make(close+360);
const q=(v:typeof a,seq:number,lag=0):DeliveryJournalEvent=>({seq,at:v.planned.latestTargetClose+lag,id:v.planned.id,action:'QUEUED',candidate:v.candidate});
const policy:DeliveryCohortPolicy={maxQueueLagSeconds:30,maxResolutionLagSeconds:120};
const run=(planned:DeclaredReviewCandidate[],events:DeliveryJournalEvent[],asOf=close+500,p=policy)=>auditForecastDeliveryCohort(planned,events,asOf,p);
test('empty cohort abstains rather than asserting perfect coverage',()=>{
 const x=run([],[]);assert.equal(x.queueCoverage,null);assert.equal(x.selfAttestedAckCoverage,null);
 assert.equal(x.independentlyVerifiedDelivery,false);
});
test('missing queue remains in declared denominator',()=>{
 const x=run([a.planned,b.planned,c.planned],[q(a,1)],close+500);
 assert.equal(x.expected,3);assert.equal(x.queued,1);assert.equal(x.missing,2);
 assert.equal(x.queueCoverage,1/3);assert.equal(x.selfAttestedAckCoverage,0);
});
test('in-flight claim is not a delivery, even when overdue',()=>{
 const x=run([a.planned],[q(a,1),{seq:2,at:close+1,id:a.planned.id,action:'CLAIMED',attemptId:'try-1'}]);
 assert.equal(x.inFlight,1);assert.equal(x.overdueWithoutSelfAck,1);
 assert.equal(x.selfAttestedAck,0);assert.equal(x.transportConnected,false);
});
test('self-attested ACK remains explicitly unverified',()=>{
 const x=run([a.planned],[q(a,1),{seq:2,at:close+1,id:a.planned.id,action:'CLAIMED',attemptId:'try-1'},
 {seq:3,at:close+2,id:a.planned.id,action:'ACK_RECORDED',attemptId:'try-1',receiptId:'unverified-receipt'}]);
 assert.equal(x.selfAttestedAck,1);assert.equal(x.selfAttestedAckCoverage,1);
 assert.equal(x.independentlyVerifiedDelivery,false);assert.equal(x.overdueWithoutSelfAck,0);
});
test('queue lag boundary is inclusive; late queues counted',()=>{
 const x=run([a.planned,b.planned],[q(a,1,30),q(b,2,31)],close+500);
 assert.equal(x.lateQueued,1);assert.equal(x.rows[0].lateQueue,false);
 assert.equal(x.rows[1].queueLagSeconds,31);
});
test('resolution age boundary is inclusive',()=>{
 assert.equal(run([a.planned],[],close+120).overdueWithoutSelfAck,0);
 assert.equal(run([a.planned],[],close+121).overdueWithoutSelfAck,1);
});
test('cancelled and pending are not counted as acknowledgements',()=>{
 const x=run([a.planned,b.planned],[q(a,1),{seq:2,at:close+1,id:a.planned.id,action:'CANCELLED',reason:'operator'},q(b,3)],close+500);
 assert.equal(x.cancelled,1);assert.equal(x.pending,1);assert.equal(x.overdueWithoutSelfAck,2);
});
test('unknown journal candidates fail closed',()=>assert.throws(()=>run([a.planned],[q(a,1),q(b,2)])));
test('duplicate and unordered declarations fail closed',()=>{
 assert.throws(()=>run([a.planned,a.planned],[]));
 assert.throws(()=>run([b.planned,a.planned],[]));
});
test('mixed source/model/horizon declarations fail closed',()=>{
 assert.throws(()=>run([a.planned,make(close+180,'v2').planned],[]));
 const bad=make(close+180);bad.planned.id=bad.planned.id.replace('source-A','source-B');
 assert.throws(()=>run([a.planned,bad.planned],[]));
});
test('future declarations, invalid canonical IDs, and malformed policies rejected',()=>{
 assert.throws(()=>run([a.planned],[],close-1));
 assert.throws(()=>run([{id:'invalid',latestTargetClose:close}],[]));
 assert.throws(()=>run([a.planned],[],close+500,{...policy,maxQueueLagSeconds:0}));
 assert.throws(()=>run([a.planned],[],close+500,{...policy,maxResolutionLagSeconds:Infinity}));
});
test('duplicate self-reported receipt IDs across candidates fail closed',()=>{
 const events:DeliveryJournalEvent[]=[q(a,1),{seq:2,at:close+1,id:a.planned.id,action:'CLAIMED',attemptId:'try-1'},
 {seq:3,at:close+2,id:a.planned.id,action:'ACK_RECORDED',attemptId:'try-1',receiptId:'same'},q(b,4),
 {seq:5,at:close+181,id:b.planned.id,action:'CLAIMED',attemptId:'try-2'},
 {seq:6,at:close+182,id:b.planned.id,action:'ACK_RECORDED',attemptId:'try-2',receiptId:'same'}];
 assert.throws(()=>run([a.planned,b.planned],events));
});
test('journal target-close mismatch is rejected',()=>{
 const bad=q(a,1);bad.candidate={...a.candidate,latestTargetClose:close+60};
 assert.throws(()=>run([a.planned],[bad]));
});
test('replay is deterministic and does not mutate caller data',()=>{
 const declared=[a.planned,b.planned];const events=[q(a,1),q(b,2)];
 const before=JSON.stringify({declared,events});
 assert.deepEqual(run(declared,events),run(declared,events));
 assert.equal(JSON.stringify({declared,events}),before);
});
