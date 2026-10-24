import {test} from 'node:test';
import assert from 'node:assert/strict';
import {appendHoldoutAuditEvent,createHoldoutCommitment,verifyHoldoutAudit,
 type HoldoutAuditEntry} from '../lib/holdout-access-audit.ts';
import type {ArchiveLineage,HoldoutProtocol} from '../lib/purged-holdout-plan.ts';

const year=(n:number)=>Math.floor(Date.UTC(n,0,1)/1000);
const archives:ArchiveLineage[]=[2020,2021,2022,2023,2024].map((y,i)=>({
 id:'archive-'+y,provider:'SyntheticProvider',instrument:'XAUUSD',venue:'test',priceSide:'bid',
 utcConvention:'UTC',archiveSha256:String(i+1).repeat(64),start:year(y),end:year(y+1)
}));
const protocol:HoldoutProtocol={developmentEnd:year(2023),validationEnd:year(2024),holdoutEnd:year(2025),
 embargoSeconds:86400,strategyVersion:'v1',configSha256:'a'.repeat(64)};
const make=()=>createHoldoutCommitment(archives,protocol,'researcher-1',year(2023)+100);
const access=(eventId:string,occurredAt:number,action:'VALIDATION_ACCESS'|'HOLDOUT_ACCESS'|'HOLDOUT_EVALUATION'|'PROTOCOL_CHANGED',archiveId:string|null='archive-2024')=>({eventId,occurredAt,action,archiveId});

test('stable source-identified commitment despite archive input order',async()=>{
 const a=await make();
 const b=await createHoldoutCommitment([...archives].reverse(),{...protocol},'researcher-1',year(2023)+100);
 assert.equal(a.digest,b.digest);
 assert.deepEqual(a.archives.map(x=>x.id),archives.map(x=>x.id));
 assert.equal(a.digest.length,64);
 assert.equal((await verifyHoldoutAudit(a,[])).recordedStatus,'NO_CONTAMINATION_RECORDED');
});
test('appends chronological self-attested receipts without mutating previous state',async()=>{
 const c=await make();
 const one=await appendHoldoutAuditEvent(c,[],access('v1',year(2023)+200,'VALIDATION_ACCESS','archive-2023'));
 const two=await appendHoldoutAuditEvent(c,one,access('h1',year(2024)+200,'HOLDOUT_ACCESS'));
 assert.equal(one.length,1);
 assert.equal(two.length,2);
 assert.equal(two[1].previousDigest,one[0].digest);
 assert.equal((await verifyHoldoutAudit(c,two)).eventCount,2);
 assert.equal((await verifyHoldoutAudit(c,two)).recordedStatus,'NO_CONTAMINATION_RECORDED');
});
test('rejects edited event data and changed digests',async()=>{
 const c=await make();
 const entries=await appendHoldoutAuditEvent(c,[],access('h1',year(2024)+200,'HOLDOUT_ACCESS'));
 await assert.rejects(verifyHoldoutAudit(c,[{...entries[0],occurredAt:entries[0].occurredAt+1}]),/digest mismatch/);
 await assert.rejects(verifyHoldoutAudit(c,[{...entries[0],digest:'0'.repeat(64)}]),/digest mismatch/);
});
test('rejects missing middle event and reordered chain',async()=>{
 const c=await make();
 const one=await appendHoldoutAuditEvent(c,[],access('a',year(2024)+200,'HOLDOUT_ACCESS'));
 const two=await appendHoldoutAuditEvent(c,one,access('b',year(2024)+201,'HOLDOUT_EVALUATION'));
 await assert.rejects(verifyHoldoutAudit(c,[two[1]]),/Broken audit sequence/);
 await assert.rejects(verifyHoldoutAudit(c,[two[1],two[0]]),/Broken audit sequence/);
});
test('rejects commitment changes after event chain creation',async()=>{
 const c=await make();
 const entries=await appendHoldoutAuditEvent(c,[],access('a',year(2024)+200,'HOLDOUT_ACCESS'));
 await assert.rejects(verifyHoldoutAudit({...c,operatorId:'another'},entries),/commitment digest mismatch/);
 await assert.rejects(verifyHoldoutAudit({...c,protocol:{...c.protocol,strategyVersion:'v2'}},entries),/commitment digest mismatch/);
});
test('records early holdout access as contamination, not a clean sample',async()=>{
 const c=await make();
 const entries=await appendHoldoutAuditEvent(c,[],access('early',year(2023)+300,'HOLDOUT_ACCESS'));
 const result=await verifyHoldoutAudit(c,entries);
 assert.equal(result.integrity,'HASH_CHAIN_VALID');
 assert.equal(result.recordedStatus,'CONTAMINATION_RECORDED');
 assert.ok(result.findings.some(f=>f.includes('before preregistered validation end')));
});
test('protocol revision invalidates untouched claim even if after validation',async()=>{
 const c=await make();
 const entries=await appendHoldoutAuditEvent(c,[],access('revision',year(2024)+10,'PROTOCOL_CHANGED',null));
 assert.equal((await verifyHoldoutAudit(c,entries)).recordedStatus,'CONTAMINATION_RECORDED');
});
test('rejects duplicate and retroactive event IDs and times',async()=>{
 const c=await make();
 const entries=await appendHoldoutAuditEvent(c,[],access('a',year(2024)+200,'HOLDOUT_ACCESS'));
 await assert.rejects(appendHoldoutAuditEvent(c,entries,access('a',year(2024)+201,'HOLDOUT_ACCESS')),/Duplicate or backdated/);
 await assert.rejects(appendHoldoutAuditEvent(c,entries,access('b',year(2024)+199,'HOLDOUT_ACCESS')),/Duplicate or backdated/);
});
test('rejects unknown archive, outcomes, and extra fields',async()=>{
 const c=await make();
 await assert.rejects(appendHoldoutAuditEvent(c,[],access('a',year(2024)+200,'HOLDOUT_ACCESS','archive-other')),/frozen source lineage/);
 const bad={...access('a',year(2024)+200,'HOLDOUT_ACCESS'),realizedPnl:999};
 await assert.rejects(appendHoldoutAuditEvent(c,[],bad),/no outcomes or additional fields/);
 const entries=await appendHoldoutAuditEvent(c,[],access('a',year(2024)+200,'HOLDOUT_ACCESS'));
 const mutated=[{...entries[0],realizedR:100}] as HoldoutAuditEntry[];
 await assert.rejects(verifyHoldoutAudit(c,mutated),/no outcomes or additional fields/);
});
test('rejects malformed freeze, wrong protocol window, and backdated access',async()=>{
 await assert.rejects(createHoldoutCommitment(archives,protocol,'researcher-1',year(2024)),/freeze before holdout/);
 await assert.rejects(createHoldoutCommitment(archives,protocol,'bad name',year(2023)),/valid operator/);
 const c=await make();
 await assert.rejects(appendHoldoutAuditEvent(c,[],access('old',year(2023),'VALIDATION_ACCESS','archive-2023')),/Invalid access event/);
});
test('clean self-attested hash chain still warns it cannot prove untouched holdout',async()=>{
 const c=await make();
 const entries=await appendHoldoutAuditEvent(c,[],access('a',year(2024)+200,'HOLDOUT_ACCESS'));
 const result=await verifyHoldoutAudit(c,entries);
 assert.ok(result.findings.some(f=>f.includes('self-reported')));
});
