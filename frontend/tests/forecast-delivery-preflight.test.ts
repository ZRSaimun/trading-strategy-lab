import {test} from 'node:test';
import assert from 'node:assert/strict';
import {preflightForecastReviewClaims} from '../lib/forecast-delivery-preflight.ts';
import type {DeliveryJournalEvent} from '../lib/forecast-delivery-journal.ts';
import type {ForecastReviewCandidate} from '../lib/forecast-review-outbox.ts';

const identity={instrument:'XAUUSD-FIXTURE',provider:'fixture',venue:'fixture',
  sourceId:'offline-A',priceSide:'bid' as const,seconds:60};
const close=1800000060;
const source=JSON.stringify([identity.instrument,identity.provider,identity.venue,
  identity.sourceId,identity.priceSide,identity.seconds]);
const id=JSON.stringify([source,'v1',3,close]);
const candidate:ForecastReviewCandidate={
  id,kind:'FORECAST_CALIBRATION_REVIEW',mode:'UNVERIFIED_LOCAL_RESEARCH',
  live:false,delivery:'NOT_CONNECTED',execution:'NONE',quoteTimestamp:null,
  identity,modelVersion:'v1',horizon:3,latestTargetClose:close,
  earlierBrier:0.1,recentBrier:0.3,deltaBrier:0.2,
  reasons:['Offline deterioration'],
};
const queued:DeliveryJournalEvent={seq:1,at:close,id,action:'QUEUED',candidate};
const claimed:DeliveryJournalEvent={seq:2,at:close+1,id,action:'CLAIMED',attemptId:'attempt-1'};
const released:DeliveryJournalEvent={seq:3,at:close+2,id,action:'RELEASED',
  attemptId:'attempt-1',reason:'Manual reconciliation completed'};
const ack:DeliveryJournalEvent={seq:3,at:close+2,id,action:'ACK_RECORDED',
  attemptId:'attempt-1',receiptId:'self-attested'};
const policy={maxCandidateAgeSeconds:3600,retryCooldownSeconds:120,maxAttempts:2};
const run=(events:DeliveryJournalEvent[],now=close+100,
  p=policy)=>preflightForecastReviewClaims(events,now,p);

test('empty preflight is explicitly offline, never atomic or transport-connected',()=>{
  const result=run([]);
  assert.deepEqual(result.assessments,[]);
  assert.equal(result.live,false);
  assert.equal(result.transportConnected,false);
  assert.equal(result.claimIsAtomic,false);
});
test('fresh pending candidate can only be rehearsed, not delivered',()=>{
  assert.deepEqual(run([queued]).assessments,[{
    id,decision:'REHEARSAL_ONLY',reason:'PENDING_OFFLINE_ONLY',
    attempts:0,candidateTargetClose:close,
  }]);
});
test('stale candidate blocked; boundary age is inclusive',()=>{
  assert.equal(run([queued],close+3600).assessments[0].reason,'PENDING_OFFLINE_ONLY');
  assert.equal(run([queued],close+3601).assessments[0].reason,'EXPIRED');
});
test('ambiguous claimed event requires reconciliation after replay',()=>{
  const item=run([queued,claimed]).assessments[0];
  assert.equal(item.reason,'NEEDS_RECONCILIATION');
  assert.equal(item.decision,'BLOCKED');
});
test('released claim observes cooldown, then only offline rehearsal',()=>{
  assert.equal(run([queued,claimed,released],close+121).assessments[0].reason,'RETRY_COOLDOWN');
  assert.equal(run([queued,claimed,released],close+122).assessments[0].reason,'PENDING_OFFLINE_ONLY');
});
test('attempt budget blocks retry even after cooldown',()=>{
  const twice:DeliveryJournalEvent[]=[
    queued,claimed,released,
    {seq:4,at:close+3,id,action:'CLAIMED',attemptId:'attempt-2'},
    {seq:5,at:close+4,id,action:'RELEASED',attemptId:'attempt-2',reason:'reconciled'},
  ];
  assert.equal(run(twice,close+200).assessments[0].reason,'ATTEMPTS_EXHAUSTED');
});
test('acknowledged and cancelled records remain terminal',()=>{
  assert.equal(run([queued,claimed,ack]).assessments[0].reason,'ACK_RECORDED_UNVERIFIED');
  assert.equal(run([queued,{seq:2,at:close+1,id,action:'CANCELLED',
    reason:'operator cancellation'}]).assessments[0].reason,'CANCELLED');
});
test('invalid policies and malformed journal fail closed',()=>{
  assert.throws(()=>run([queued],close+100,{...policy,maxAttempts:0}));
  assert.throws(()=>run([queued],close+100,{...policy,maxCandidateAgeSeconds:0}));
  assert.throws(()=>run([queued],close+100,{...policy,retryCooldownSeconds:-1}));
  assert.throws(()=>run([queued],close-1));
  assert.throws(()=>run([queued,{...queued,seq:2,at:close+1}]));
});
test('independent candidates remain isolated and ordered by journal queue',()=>{
  const second={...candidate,modelVersion:'v2',id:JSON.stringify([source,'v2',3,close])};
  const secondQueued:DeliveryJournalEvent={seq:2,at:close+1,id:second.id,
    action:'QUEUED',candidate:second};
  const firstClaim:DeliveryJournalEvent={seq:3,at:close+2,id,action:'CLAIMED',
    attemptId:'attempt-1'};
  const items=run([queued,secondQueued,firstClaim]).assessments;
  assert.deepEqual(items.map(x=>x.id),[id,second.id]);
  assert.deepEqual(items.map(x=>x.reason),['NEEDS_RECONCILIATION','PENDING_OFFLINE_ONLY']);
});
