import {test} from 'node:test';
import assert from 'node:assert/strict';
import {planFrozenWalkForward, type FrozenForwardSpecification} from '../lib/frozen-walk-forward-plan.ts';
import type {OutcomeTiming, PurgedPlan} from '../lib/purged-holdout-plan.ts';

const yr=(y:number)=>Math.floor(Date.UTC(y,0,1)/1000);
const d=86400;
const source={provider:'SyntheticOnly',instrument:'XAUUSD',venue:'test',priceSide:'bid' as const,utcConvention:'UTC' as const};
const archiveLineage=[2020,2021,2022,2023,2024].map((y,i)=>({
 id:\`a-\${y}\`,archiveSha256:String(i+1).repeat(64),start:yr(y),end:yr(y+1)
}));
const protocol={developmentEnd:yr(2023),validationEnd:yr(2024),holdoutEnd:yr(2025),
 embargoSeconds:0,strategyVersion:'frozen-v1',configSha256:'a'.repeat(64)};
const sample:OutcomeTiming[]=[
 {id:'t0',archiveId:'a-2020',featureStart:yr(2020)+20*d,decisionAt:yr(2020)+100*d,labelAvailableAt:yr(2020)+101*d},
 {id:'v1',archiveId:'a-2021',featureStart:yr(2021)+10*d,decisionAt:yr(2021)+40*d,labelAvailableAt:yr(2021)+41*d},
 {id:'v2',archiveId:'a-2021',featureStart:yr(2021)+190*d,decisionAt:yr(2021)+210*d,labelAvailableAt:yr(2021)+211*d},
 {id:'v3',archiveId:'a-2022',featureStart:yr(2022)+10*d,decisionAt:yr(2022)+100*d,labelAvailableAt:yr(2022)+101*d}
];
const makePlan=(obs=sample):PurgedPlan=>({source:{...source},archiveLineage:structuredClone(archiveLineage),
 protocol:{...protocol},eligible:{development:obs.map(o=>o.id),validation:[],holdout:[]},
 excluded:[],warnings:['synthetic metadata only']});
const folds=[
 {id:'fold-1',trainingStart:yr(2020),trainingEnd:yr(2021),testingStart:yr(2021),testingEnd:yr(2021)+181*d},
 {id:'fold-2',trainingStart:yr(2020),trainingEnd:yr(2021)+181*d,testingStart:yr(2021)+181*d,testingEnd:yr(2022)},
 {id:'fold-3',trainingStart:yr(2020),trainingEnd:yr(2022),testingStart:yr(2022),testingEnd:yr(2023)}
];
const spec:FrozenForwardSpecification={folds,embargoSeconds:0,minTrainingObservations:1,minTestingObservations:1};
const run=(p=makePlan(),o:readonly OutcomeTiming[]=sample,s:FrozenForwardSpecification=spec)=>planFrozenWalkForward(p,o,s);

test('three expanding past-only folds have disjoint chronological tests',async()=>{
 const r=await run();
 assert.equal(r.folds.length,3);
 assert.deepEqual(r.folds.map(f=>f.trainingIds),[['t0'],['t0','v1'],['t0','v1','v2']]);
 assert.deepEqual(r.folds.map(f=>f.testingIds),[['v1'],['v2'],['v3']]);
 assert.deepEqual(r.folds.map(f=>f.status),['TIMING_ONLY','TIMING_ONLY','TIMING_ONLY']);
 assert.equal(r.coverage,'UNVERIFIED_METADATA_ONLY');
 assert.match(r.scheduleSha256,/^[a-f0-9]{64}$/);
});
test('train label first available at test start is purged even with zero embargo',async()=>{
 const o=sample.map(x=>x.id==='v1'?{...x,labelAvailableAt:folds[1].testingStart}:x);
 const r=await run(makePlan(o),o);
 assert.deepEqual(r.folds[1].trainingIds,['t0']);
 assert.equal(r.folds[1].trainingExcluded,1);
 assert.deepEqual(r.folds[2].trainingIds,['t0','v1','v2']);
});
test('test label first available at test end is purged',async()=>{
 const o=sample.map(x=>x.id==='v1'?{...x,labelAvailableAt:folds[0].testingEnd}:x);
 const r=await run(makePlan(o),o);
 assert.deepEqual(r.folds[0].testingIds,[]);
 assert.equal(r.folds[0].testingExcluded,1);
});
test('feature lookback across fold testing boundary is excluded',async()=>{
 const o=sample.map(x=>x.id==='v2'?{...x,featureStart:folds[1].testingStart-1}:x);
 const r=await run(makePlan(o),o);
 assert.deepEqual(r.folds[1].testingIds,[]);
 assert.equal(r.folds[1].testingExcluded,1);
});
test('positive embargo rejects label at cutoff but permits earlier label',async()=>{
 const cutoff=folds[0].trainingEnd-2*d;
 const o=sample.map(x=>x.id==='t0'?{...x,labelAvailableAt:cutoff}:x);
 const r=await run(makePlan(o),o,{...spec,embargoSeconds:2*d});
 assert.deepEqual(r.folds[0].trainingIds,[]);
 const earlier=o.map(x=>x.id==='t0'?{...x,labelAvailableAt:cutoff-1}:x);
 const good=await run(makePlan(earlier),earlier,{...spec,embargoSeconds:2*d});
 assert.deepEqual(good.folds[0].trainingIds,['t0']);
});
test('minimum counts are warnings not invented trade performance',async()=>{
 const r=await run(makePlan(),sample,{...spec,minTrainingObservations:30,minTestingObservations:30});
 assert.ok(r.folds.every(f=>f.status==='INSUFFICIENT_TIMING_COUNTS'));
 assert.ok(r.warnings.some(x=>x.includes('not trade counts')));
 assert.equal('netReturn' in r,false);
});
test('forbids validation and holdout observations even when labelled development',async()=>{
 const o=sample.map(x=>x.id==='v3'?{...x,decisionAt:yr(2023)+1}:x);
 await assert.rejects(run(makePlan(o),o),/non-development/);
});
test('forbids extra realized P&L or outcome fields',async()=>{
 const o=[...sample.slice(0,3),{...sample[3],realizedR:100}] as OutcomeTiming[];
 await assert.rejects(run(makePlan(o),o),/extra outcome fields/);
});
test('requires complete unique development eligible set',async()=>{
 await assert.rejects(run(makePlan(),sample.slice(1)),/Complete development-only/);
 const duplicate=[...sample.slice(0,3),sample[0]];
 await assert.rejects(run(makePlan(),duplicate),/duplicate/);
 const wrong=[...sample.slice(0,3),{...sample[3],id:'holdout-id'}];
 await assert.rejects(run(makePlan(),wrong),/Unknown/);
});
test('rejects crossed source archives, reused digests and malformed identities',async()=>{
 const p=makePlan();p.archiveLineage[1].start=yr(2020);
 await assert.rejects(run(p),/overlapping/);
 const q=makePlan();q.archiveLineage[1].archiveSha256=q.archiveLineage[0].archiveSha256;
 await assert.rejects(run(q),/duplicated/);
 const t=makePlan();t.source.utcConvention='LOCAL' as 'UTC';
 await assert.rejects(run(t),/source/);
});
test('rejects fold overlap, training reset and evaluation outside development',async()=>{
 const overlap=folds.map(f=>({...f}));overlap[1].testingStart=folds[0].testingStart;
 await assert.rejects(run(makePlan(),sample,{...spec,folds:overlap}),/Overlapping/);
 const reset=folds.map(f=>({...f}));reset[2].trainingStart=yr(2021);
 await assert.rejects(run(makePlan(),sample,{...spec,folds:reset}),/nonexpanding/);
 const hold=folds.map(f=>({...f}));hold[2].testingEnd=yr(2024);
 await assert.rejects(run(makePlan(),sample,{...spec,folds:hold}),/out-of-development/);
});
test('rejects unbounded, missing and outcome-bearing specification fields',async()=>{
 await assert.rejects(run(makePlan(),sample,{...spec,embargoSeconds:-1}),/Invalid predeclared/);
 await assert.rejects(run(makePlan(),sample,{...spec,folds:[folds[0]]}),/Invalid predeclared/);
 const extra={...spec,observedProfit:999};
 await assert.rejects(run(makePlan(),sample,extra),/extra outcome fields/);
});
test('digest is canonical across metadata order, and source and fold changes alter it',async()=>{
 const first=await run();
 const p=makePlan();p.archiveLineage.reverse();
 p.source={utcConvention:'UTC',priceSide:'bid',venue:'test',instrument:'XAUUSD',provider:'SyntheticOnly'};
 const reordered=await run(p,[...sample].reverse());
 assert.equal(reordered.scheduleSha256,first.scheduleSha256);
 assert.deepEqual(reordered.folds,first.folds);
 const changed=makePlan();changed.source.provider='OtherSyntheticProvider';
 assert.notEqual((await run(changed)).scheduleSha256,first.scheduleSha256);
 const altered=folds.map(f=>({...f}));altered[2].testingEnd-=d;
 assert.notEqual((await run(makePlan(),sample,{...spec,folds:altered})).scheduleSha256,first.scheduleSha256);
});
test('does not mutate caller source, observations or schedule',async()=>{
 const p=makePlan(),o=structuredClone(sample),s=structuredClone(spec);
 const before=structuredClone({p,o,s});
 await run(p,o,s);
 assert.deepEqual({p,o,s},before);
});
