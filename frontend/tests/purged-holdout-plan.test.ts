import {test} from 'node:test';
import assert from 'node:assert/strict';
import {planPurgedHoldout, type ArchiveLineage, type OutcomeTiming, type HoldoutProtocol} from '../lib/purged-holdout-plan.ts';
const year=(n:number)=>Math.floor(Date.UTC(n,0,1)/1000);
const d=86400;
const archives:ArchiveLineage[] = [2020,2021,2022,2023,2024].map((y,i)=>({
 id:'archive-'+y,provider:'TestProvider',instrument:'XAUUSD',venue:'synthetic',priceSide:'bid',utcConvention:'UTC',
 archiveSha256:String(i+1).repeat(64),start:year(y),end:year(y+1)
}));
const protocol:HoldoutProtocol={developmentEnd:year(2023),validationEnd:year(2024),holdoutEnd:year(2025),
 embargoSeconds:2*d,strategyVersion:'research-v1',configSha256:'a'.repeat(64)};
const event=(id:string,y:number,offset:number,horizon=1,featureOffset=0):OutcomeTiming=>({
 id,archiveId:'archive-'+y,featureStart:year(y)+featureOffset*d,decisionAt:year(y)+offset*d,labelAvailableAt:year(y)+(offset+horizon)*d
});
const sample=()=>[event('train',2022,100),event('train-late',2022,362,2),event('valid',2023,100),
 event('valid-late',2023,364,1),event('hold',2024,100)];

test('multi-year chronological partition excludes late labels and cross-boundary features',()=>{
 const p=planPurgedHoldout(archives,sample(),protocol);
 assert.deepEqual(p.eligible,{development:['train'],validation:['valid'],holdout:['hold']});
 assert.deepEqual(p.excluded,[{id:'train-late',reason:'EMBARGO_OR_UNSETTLED'},
  {id:'valid-late',reason:'EMBARGO_OR_UNSETTLED'}]);
 assert.equal(p.archiveLineage.length,5);
 assert.equal(p.source.priceSide,'bid');
});
test('rejects feature lookback crossing validation-to-holdout boundary',()=>{
 const joined=[...archives.slice(0,3),{...archives[3],end:year(2025)}];
 const o={...event('cross',2023,370,1),featureStart:year(2023)+300*d};
 const p=planPurgedHoldout(joined,[o],protocol);
 assert.deepEqual(p.eligible.holdout,[]);
 assert.deepEqual(p.excluded,[{id:'cross',reason:'CROSS_BOUNDARY_FEATURES'}]);
});
test('outcomes cannot enter planner, even as extra runtime fields',()=>{
 const obs={...event('secret',2024,100),realizedR:99};
 assert.throws(()=>planPurgedHoldout(archives,[obs],protocol),/unsupported fields/);
});
test('later test observations do not alter development or validation selection',()=>{
 const baseline=planPurgedHoldout(archives,sample(),protocol);
 const more=[...sample(),event('later',2024,200)];
 const p=planPurgedHoldout(archives,more,protocol);
 assert.deepEqual(p.eligible.development,baseline.eligible.development);
 assert.deepEqual(p.eligible.validation,baseline.eligible.validation);
 assert.deepEqual(p.eligible.holdout,['hold','later']);
});
test('rejects archive source family drift and overlapping source ranges',()=>{
 assert.throws(()=>planPurgedHoldout([...archives.slice(0,4),{...archives[4],priceSide:'ask'}],sample(),protocol),/Source family changed/);
 assert.throws(()=>planPurgedHoldout([...archives.slice(0,4),{...archives[4],start:year(2023)}],sample(),protocol),/Overlapping archive/);
 assert.throws(()=>planPurgedHoldout([...archives.slice(0,4),{...archives[4],archiveSha256:'not-sha'}],sample(),protocol),/Invalid or duplicate/);
});
test('rejects duplicate IDs, future knowledge, unverified source and cross-archive outcome',()=>{
 const e=event('same',2024,100);
 assert.throws(()=>planPurgedHoldout(archives,[e,e],protocol),/Duplicate, noncausal/);
 assert.throws(()=>planPurgedHoldout(archives,[{...e,labelAvailableAt:e.decisionAt-1}],protocol),/Duplicate, noncausal/);
 assert.throws(()=>planPurgedHoldout(archives,[{...e,archiveId:'other'}],protocol),/Duplicate, noncausal/);
 assert.throws(()=>planPurgedHoldout(archives,[{...e,labelAvailableAt:year(2025)+1}],protocol),/Duplicate, noncausal/);
});
test('rejects invalid cutoffs, inadequate training history and malformed metadata',()=>{
 assert.throws(()=>planPurgedHoldout(archives,sample(),{...protocol,validationEnd:year(2022)}),/Invalid preregistered/);
 assert.throws(()=>planPurgedHoldout(archives,sample(),{...protocol,developmentEnd:year(2021)}),/two elapsed years/);
 assert.throws(()=>planPurgedHoldout(archives,sample(),{...protocol,embargoSeconds:-1}),/Invalid preregistered/);
 assert.throws(()=>planPurgedHoldout(archives,sample(),{...protocol,configSha256:'unknown'}),/Invalid preregistered/);
});
test('source gaps remain disclosed and planner does not mutate input',()=>{
 const withGap=archives.map(a=>({...a}));
 withGap[1].start+=5*d;
 const before=structuredClone({withGap,observations:sample(),protocol});
 const p=planPurgedHoldout(withGap,before.observations,protocol);
 assert.ok(p.warnings.some(w=>w.includes('gaps')));
 assert.deepEqual({withGap,observations:before.observations,protocol},before);
});
test('strict embargo removes labels near each partition end, never invents fills',()=>{
 const obs=[event('early',2020,100),event('boundary',2023,1),event('hold',2024,2)];
 const p=planPurgedHoldout(archives,obs,{...protocol,embargoSeconds:30*d});
 assert.deepEqual(p.eligible,{development:['early'],validation:['boundary'],holdout:['hold']});
 assert.ok(p.warnings.some(w=>w.includes('No executable')));
});

test('rejects one immutable archive digest advertised as two different calendar years',()=>{
 const reused=archives.map(a=>({...a}));
 reused[4].archiveSha256=reused[0].archiveSha256;
 assert.throws(()=>planPurgedHoldout(reused,[],protocol),/Invalid or duplicate source-identified archive/);
 // Distinct archives and their metadata remain untouched on rejection.
 assert.equal(reused[4].archiveSha256,reused[0].archiveSha256);
});
test('exclusive archive-end labels are excluded even with zero embargo',()=>{
 const atEnd=event('archive-end',2023,364,1);
 assert.equal(atEnd.labelAvailableAt,year(2024));
 const zeroEmbargo={...protocol,embargoSeconds:0};
 const result=planPurgedHoldout(archives,[atEnd],zeroEmbargo);
 assert.deepEqual(result.eligible.validation,[]);
 assert.deepEqual(result.excluded,[{id:'archive-end',reason:'EMBARGO_OR_UNSETTLED'}]);
 const beforeEnd={...atEnd,labelAvailableAt:year(2024)-1};
 const within=planPurgedHoldout(archives,[beforeEnd],zeroEmbargo);
 assert.deepEqual(within.eligible.validation,['archive-end']);
});

test('zero embargo never admits a label first available at the next partition start',()=>{
 // A single source archive can span validation and holdout. Its exclusive end
 // is later than the validation cutoff, so archive-end purging alone misses this.
 const spanning=[...archives.slice(0,3),{...archives[3],end:year(2025)}];
 const atCutoff=event('next-segment-label',2023,364,1);
 const zeroEmbargo={...protocol,embargoSeconds:0};
 const rejected=planPurgedHoldout(spanning,[atCutoff],zeroEmbargo);
 assert.deepEqual(rejected.eligible.validation,[]);
 assert.deepEqual(rejected.excluded,[{id:'next-segment-label',reason:'EMBARGO_OR_UNSETTLED'}]);
 // Evidence strictly before the cutoff remains eligible at zero embargo.
 const before={...atCutoff,labelAvailableAt:year(2024)-1};
 const accepted=planPurgedHoldout(spanning,[before],zeroEmbargo);
 assert.deepEqual(accepted.eligible.validation,['next-segment-label']);
});

test('positive embargo admits labels exactly at its preregistered safe cutoff',()=>{
 const spanning=[...archives.slice(0,3),{...archives[3],end:year(2025)}];
 const cutoff=year(2024)-2*d;
 const label={...event('embargo-edge',2023,300),labelAvailableAt:cutoff};
 const result=planPurgedHoldout(spanning,[label],protocol);
 assert.deepEqual(result.eligible.validation,['embargo-edge']);
 const late=planPurgedHoldout(spanning,[{...label,labelAvailableAt:cutoff+1}],protocol);
 assert.deepEqual(late.excluded,[{id:'embargo-edge',reason:'EMBARGO_OR_UNSETTLED'}]);
});
