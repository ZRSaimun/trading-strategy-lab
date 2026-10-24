import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studySweepOutcomes} from '../lib/sweep-outcome-study.ts';
import {analyze,type Bar,type Detection} from '../lib/research.ts';
const base=Date.UTC(2026,9,19)/1000;
const bar=(i:number,open:number,close:number):Bar=>({time:base+i*60,open,high:Math.max(open,close)+1,low:Math.min(open,close)-1,close,volume:null,observed_minutes:1});
const event=(i:number,kind:'SELL-SIDE SWEEP'|'BUY-SIDE SWEEP'='SELL-SIDE SWEEP'):Detection=>({kind,direction:kind==='SELL-SIDE SWEEP'?'bullish observation':'bearish observation',
 observed_at:base+(i+1)*60,reference_times:[base],level:100,explanation:'synthetic',rule_version:'structure-research-v3'});
const cfg={datasetId:'test-sha-1',instrument:'XAUUSD-OTC',frame:'1m',horizonBars:2,costBps:5};
test('uses next open and horizon close, subtracting explicit round-trip cost',()=>{
 const bars=[bar(0,100,100),bar(1,100,101),bar(2,102,103),bar(3,103,105)];
 const r=studySweepOutcomes(bars,[event(1)],cfg);
 assert.equal(r.completed.length,1);
 assert.equal(r.completed[0].entry,102);
 assert.equal(r.completed[0].exit,105);
 assert.equal(r.completed[0].entryAt,bars[2].time);
 assert.equal(r.completed[0].exitAt,bars[3].time+60);
 assert.ok(Math.abs(r.completed[0].netBps-((105/102-1)*10000-5))<1e-9);
 assert.equal(r.positiveFraction,1);
});
test('bearish outcomes reverse the sign; adverse costs cannot improve returns',()=>{
 const bars=[bar(0,100,100),bar(1,100,100),bar(2,101,100),bar(3,99,98)];
 const a=studySweepOutcomes(bars,[event(1,'BUY-SIDE SWEEP')],cfg);
 const b=studySweepOutcomes(bars,[event(1,'BUY-SIDE SWEEP')],{...cfg,costBps:25});
 assert.ok(a.completed[0].netBps>0);
 assert.equal(a.completed[0].netBps-b.completed[0].netBps,20);
});
test('future labels remain pending and do not leak into a prefix',()=>{
 const bars=[bar(0,100,100),bar(1,100,100),bar(2,100,101),bar(3,100,105)];
 const e=event(1);
 const full=studySweepOutcomes(bars,[e],cfg);
 const prefix=studySweepOutcomes(bars.slice(0,3),[e],cfg);
 assert.equal(full.completed.length,1);
 assert.equal(prefix.completed.length,0);
 assert.equal(prefix.pending,1);
});
test('gaps and incomplete bars exclude rather than invent fixed-horizon outcomes',()=>{
 const bars=[bar(0,100,100),bar(1,100,100),bar(3,101,102),bar(4,103,104)];
 const r=studySweepOutcomes(bars,[event(1)],cfg);
 assert.equal(r.completed.length,0);
 assert.equal(r.gapExcluded,1);
 const partial=[bar(0,100,100),bar(1,100,100),{...bar(2,101,102),observed_minutes:0},bar(3,103,104)];
 assert.equal(studySweepOutcomes(partial,[event(1)],cfg).gapExcluded,1);
});
test('rejects incompatible rule versions, future references, duplicates and invalid assumptions',()=>{
 const bars=[bar(0,100,100),bar(1,100,100),bar(2,101,102),bar(3,103,104)];
 assert.throws(()=>studySweepOutcomes(bars,[{...event(1),rule_version:'structure-research-v2'}],cfg),/causal v3/);
 assert.throws(()=>studySweepOutcomes(bars,[{...event(1),reference_times:[base+100000]}],cfg),/future-referencing/);
 assert.throws(()=>studySweepOutcomes(bars,[event(1),event(1)],cfg),/duplicate/);
 assert.throws(()=>studySweepOutcomes(bars,[event(1)],{...cfg,costBps:-1}),/cost/);
 assert.throws(()=>studySweepOutcomes(bars,[event(1)],{...cfg,frame:'9H'}),/Unsupported/);
});
test('nonpositive price levels are excluded because percentage returns are undefined',()=>{
 const bars=[bar(0,100,100),bar(1,100,100),bar(2,-1,-1),bar(3,-2,-2)];
 const r=studySweepOutcomes(bars,[event(1)],cfg);
 assert.equal(r.priceExcluded,1);
 assert.equal(r.meanNetBps,null);
});
test('duplicate or backward candles cannot remap a sweep to a different bar',()=>{
 const bars=[bar(0,100,100),bar(1,100,100),bar(1,101,102),bar(3,103,104)];
 assert.throws(()=>studySweepOutcomes(bars,[event(1)],cfg),/strictly increasing/);
 assert.throws(()=>studySweepOutcomes([...bars.slice(0,2),bar(0,101,102)],[],cfg),/strictly increasing/);
});

test('accepts real v3 detector sweeps but never treats unrelated formations as trades',()=>{
 const mk=(n:number,low:number,high:number,close:number):Bar=>({
  time:base+n*60,open:(low+high)/2,high,low,close,volume:null,observed_minutes:1
 });
 const bars=[mk(0,10,14,12),mk(1,9,13,11),mk(2,5,12,8),mk(3,8,13,10),
             mk(4,9,14,11),mk(5,4,10,6),mk(6,6,12,11),mk(7,11,13,12)];
 const detections=analyze(bars,2,'1m');
 assert.ok(detections.some(d=>d.kind==='SELL-SIDE SWEEP'));
 const study=studySweepOutcomes(bars,detections,cfg);
 assert.equal(study.completed.length,1);
 assert.equal(study.completed[0].observedAt,bars[5].time+60);
});
test('nonfinite percentage return is excluded instead of reporting infinite profitability',()=>{
 const rows=[bar(0,100,100),bar(1,100,100),{...bar(2,100,100),open:1e-300,low:1e-300,close:1e300,high:1e300}];
 const r=studySweepOutcomes(rows,[event(1)],{...cfg,horizonBars:1});
 assert.equal(r.priceExcluded,1);assert.equal(r.completed.length,0);assert.equal(r.meanNetBps,null);
});
