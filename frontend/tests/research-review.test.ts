import {test} from 'node:test';
import assert from 'node:assert/strict';
import {reviewResearchRun,type ResearchRun,type SnapshotMetrics} from '../lib/research-review.ts';

function metric(trades:number,netReturn:number,maxDrawdownPercent=4,winRate:number|null=50,profitFactor:number|null=1):SnapshotMetrics{
 return {trades,netReturn,maxDrawdownPercent,winRate,profitFactor};
}
const make=(dev:SnapshotMetrics,val:SnapshotMetrics,hold:SnapshotMetrics,full:SnapshotMetrics=dev):ResearchRun=>({
 id:'run-a',title:'Imported Gold · 1H',created_at:1700000000,
 payload:{
  reports:[{strategy:'B',ruleVersion:'sweep-shift-retest-v1',metrics:full}],
  splits:[
   {name:'Development 60%',reports:[{strategy:'B',metrics:dev}]},
   {name:'Validation 20%',reports:[{strategy:'B',metrics:val}]},
   {name:'Holdout 20%',reports:[{strategy:'B',metrics:hold}]}
  ],
  source:'HistData · XAUUSD OTC bid',datasetHash:'a'.repeat(64),
  window:{start:0,end:10000,bars:1000}
 }
});

test('identifies held-out negative reversal, small sample and large drawdown independently',()=>{
 const run=make(metric(90,20,5,65,1.7),metric(34,2,8,55,1.1),metric(12,-8,23,45,.7));
 const x=reviewResearchRun(run);
 assert.equal(x.strategies[0].strategy,'B');
 assert.equal(x.strategies[0].holdout?.netReturn,-8);
 const flags=x.strategies[0].findings.map(f=>f.code);
 assert.ok(flags.includes('SMALL_HOLDOUT'));
 assert.ok(flags.includes('RETURN_REVERSAL'));
 assert.ok(flags.includes('WIN_RATE_DROP'));
 assert.ok(flags.includes('LARGE_DRAWDOWN'));
 assert.ok(x.runFindings.some(f=>f.code==='NO_INDEPENDENT_HOLDOUT'));
 assert.ok(x.runFindings.some(f=>f.code==='EXECUTION_LIMITS'));
});
test('does not invent statistical confidence or positive returns from no trades',()=>{
 const no=make(metric(0,0,0,null,null),metric(0,0,0,null,null),metric(0,0,0,null,null));
 const x=reviewResearchRun(no).strategies[0];
 assert.ok(x.findings.some(f=>f.code==='NO_TRADES'));
 assert.ok(x.findings.some(f=>f.code==='SMALL_HOLDOUT'));
 assert.equal(x.holdout?.profitFactor,null);
 assert.ok(!x.findings.some(f=>f.code==='RETURN_REVERSAL'));
});
test('reports missing chronological splits and data provenance without pretending they exist',()=>{
 const r=make(metric(50,5),metric(10,0),metric(20,-2));
 r.payload.splits=r.payload.splits.slice(0,1);
 r.payload.datasetHash='Unknown';
 r.payload.notes='WARNING: source was capped at 2,000 aggregates, not a full archive';
 const x=reviewResearchRun(r);
 assert.ok(x.runFindings.some(f=>f.code==='MISSING_SPLITS'));
 assert.ok(x.runFindings.some(f=>f.code==='WINDOW_CAPPED'));
 assert.ok(x.runFindings.some(f=>f.code==='UNKNOWN_PROVENANCE'));
 assert.ok(x.strategies[0].findings.some(f=>f.code==='UNAVAILABLE_SPLIT'));
 assert.equal(x.strategies[0].holdout,null);
});
test('preserves independent strategy identities and reports without mixing versions',()=>{
 const r=make(metric(90,6),metric(25,2),metric(30,1));
 r.payload.reports.push({strategy:'C',ruleVersion:'crt-range-v1',metrics:metric(80,8)});
 const x=reviewResearchRun(r);
 assert.deepEqual(x.strategies.map(s=>s.strategy),['B','C']);
 assert.ok(x.strategies[1].findings.some(f=>f.code==='UNAVAILABLE_SPLIT'));
 assert.equal(x.strategies[1].ruleVersion,'crt-range-v1');
});
test('rejects malformed historic metrics, duplicate reports and misleading numbers',()=>{
 const r=make(metric(40,5),metric(12,2),metric(32,1));
 r.payload.splits[0].reports[0].metrics={...metric(40,5),winRate:110};
 assert.throws(()=>reviewResearchRun(r),/malformed/);
 r.payload.splits[0].reports[0].metrics=metric(40,5);
 r.payload.reports.push(r.payload.reports[0]);
 assert.throws(()=>reviewResearchRun(r),/duplicate/);
 r.payload.reports.pop();
 r.payload.splits.push({...r.payload.splits[0]});
 assert.throws(()=>reviewResearchRun(r),/Duplicate chronological split/);
});
