import {test} from 'node:test';
import assert from 'node:assert/strict';
import {vetoOfflineCrossHorizon} from '../lib/forecast-cross-horizon-veto.ts';
import type {ForecastAgreement,AgreementHorizon,AgreementStatus} from '../lib/forecast-agreement-gate.ts';

const at=1800000000;
function horizon(h:1|3|12,status:AgreementStatus):AgreementHorizon{
  const pair:[number,number]|null=
    status==='ABSTAIN_INSUFFICIENT'?null:
    status==='CONSENSUS_UP_RESEARCH_ONLY'?[0.65,0.64]:
    status==='CONSENSUS_DOWN_RESEARCH_ONLY'?[0.35,0.36]:
    status==='ABSTAIN_CONFLICT'?[0.7,0.3]:[0.52,0.52];
  const direction=status==='CONSENSUS_UP_RESEARCH_ONLY'?'UP':
    status==='CONSENSUS_DOWN_RESEARCH_ONLY'?'DOWN':null;
  return {horizon:h,status,direction,frequencyProbability:pair?.[0]??null,
    ewmaProbability:pair?.[1]??null,
    absoluteDisagreement:pair?Math.abs(pair[0]-pair[1]):null,
    probabilityRange:pair?[Math.min(...pair),Math.max(...pair)]:null,
    frequencySamples:40,ewmaEffectiveSamples:25};
}
const up='CONSENSUS_UP_RESEARCH_ONLY',down='CONSENSUS_DOWN_RESEARCH_ONLY';
function fixture(statuses:AgreementStatus[]=[up,up,up]):ForecastAgreement{
  return {mode:'UNVERIFIED_LOCAL_RESEARCH',live:false,authenticated:false,
    persisted:false,alertsEnabled:false,execution:'NONE',ordersSubmitted:0,
    issuedAsOf:at-5,assessedAt:at,
    identity:{instrument:'XAUUSD-TEST',provider:'fixture',venue:'fixture',
      sourceId:'A',priceSide:'bid',seconds:60},
    horizons:[horizon(1,statuses[0]),horizon(3,statuses[1]),horizon(12,statuses[2])]};
}
test('three UP horizons allow research-only direction, never alerts or orders',()=>{
  const x=vetoOfflineCrossHorizon(fixture(),at+120);
  assert.equal(x.status,'RESEARCH_CONSENSUS_ONLY');
  assert.equal(x.direction,'UP');assert.equal(x.reason,'RESEARCH_CONSENSUS_ONLY');
  assert.equal(x.live,false);assert.equal(x.alertsEnabled,false);
  assert.equal(x.ordersSubmitted,0);assert.equal(x.execution,'NONE');
});
test('three DOWN horizons yield research-only DOWN',()=>{
  const x=vetoOfflineCrossHorizon(fixture([down,down,down]),at);
  assert.equal(x.direction,'DOWN');assert.equal(x.status,'RESEARCH_CONSENSUS_ONLY');
});
test('opposing long and short horizon vetoes the apparent signal',()=>{
  const x=vetoOfflineCrossHorizon(fixture([up,up,down]),at);
  assert.equal(x.reason,'CROSS_HORIZON_CONFLICT');assert.equal(x.direction,null);
  assert.deepEqual(x.researchDirections,['UP','UP','DOWN']);
});
test('within-horizon model conflict has priority over cross-horizon disagreement',()=>{
  const x=vetoOfflineCrossHorizon(fixture([up,'ABSTAIN_CONFLICT',down]),at);
  assert.equal(x.reason,'MODEL_CONFLICT');assert.equal(x.status,'ABSTAIN');
});
test('insufficient evidence vetoes even two aligned horizons',()=>{
  const x=vetoOfflineCrossHorizon(fixture([up,'ABSTAIN_INSUFFICIENT',up]),at);
  assert.equal(x.reason,'INSUFFICIENT');assert.equal(x.direction,null);
});
test('uncertain model evidence vetoes',()=>{
  assert.equal(vetoOfflineCrossHorizon(fixture([up,'ABSTAIN_UNCERTAIN',up]),at).reason,'UNCERTAIN');
});
test('age boundary is inclusive and stale status takes precedence',()=>{
  assert.equal(vetoOfflineCrossHorizon(fixture(),at+120).reason,'RESEARCH_CONSENSUS_ONLY');
  assert.equal(vetoOfflineCrossHorizon(fixture(),at+121).reason,'STALE');
  assert.equal(vetoOfflineCrossHorizon(fixture([up,'ABSTAIN_CONFLICT',up]),at+121).reason,'STALE');
});
test('future and retroactive timestamps fail closed',()=>{
  assert.throws(()=>vetoOfflineCrossHorizon(fixture(),at-1));
  const f=fixture();f.issuedAsOf=at+1;
  assert.throws(()=>vetoOfflineCrossHorizon(f,at+2));
});
test('missing, duplicated, or unordered horizons fail closed',()=>{
  const f=fixture();f.horizons=[f.horizons[0],f.horizons[0],f.horizons[2]];
  assert.throws(()=>vetoOfflineCrossHorizon(f,at));
  f.horizons=[f.horizons[1],f.horizons[0],f.horizons[2]];
  assert.throws(()=>vetoOfflineCrossHorizon(f,at));
  f.horizons=[f.horizons[0]];
  assert.throws(()=>vetoOfflineCrossHorizon(f,at));
});
test('mismatched probability ranges and differences fail closed',()=>{
  const f=fixture();f.horizons[0].absoluteDisagreement=0.5;
  assert.throws(()=>vetoOfflineCrossHorizon(f,at));
  const g=fixture();g.horizons[0].probabilityRange=[0.1,0.9];
  assert.throws(()=>vetoOfflineCrossHorizon(g,at));
});
test('consensus direction cannot contradict probabilities or status',()=>{
  const f=fixture();f.horizons[0].direction='DOWN';
  assert.throws(()=>vetoOfflineCrossHorizon(f,at));
  const g=fixture();g.horizons[0].status='ABSTAIN_UNCERTAIN';
  assert.throws(()=>vetoOfflineCrossHorizon(g,at));
});
test('untrusted flags, malformed source and age policy fail closed',()=>{
  const f=fixture();f.alertsEnabled=true;
  assert.throws(()=>vetoOfflineCrossHorizon(f,at));
  const g=fixture();g.identity.sourceId='';
  assert.throws(()=>vetoOfflineCrossHorizon(g,at));
  assert.throws(()=>vetoOfflineCrossHorizon(fixture(),at,-1));
  assert.throws(()=>vetoOfflineCrossHorizon(fixture(),at,3601));
});
test('deterministic replay without mutation',()=>{
  const f=fixture([down,up,up]);const before=JSON.stringify(f);
  assert.deepEqual(vetoOfflineCrossHorizon(f,at+10),vetoOfflineCrossHorizon(f,at+10));
  assert.equal(JSON.stringify(f),before);
});
