import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studySweepConfluence} from '../lib/sweep-confluence-study.ts';
import {simulateConfluenceRiskPath} from '../lib/sweep-confluence-risk-path.ts';
import type {Bar,Detection} from '../lib/research.ts';

const BASE=Date.UTC(2025,0,6)/1000,H=3600;
function bars():Bar[]{
 return Array.from({length:35},(_,i)=>({
  time:BASE+i*H,open:100,high:101,low:99,close:100,
  volume:null,observed_minutes:60
 }));
}
function event(kind:string,i:number,refs:number[]):Detection{
 return {kind,direction:'synthetic',observed_at:BASE+(i+1)*H,
  reference_times:refs.map(j=>BASE+j*H),level:100,
  explanation:'synthetic',rule_version:'structure-research-v3'};
}
function study(b:Bar[],bearish=false){
 const sweep=bearish?'BUY-SIDE SWEEP':'SELL-SIDE SWEEP';
 const structure=bearish?'BEARISH STRUCTURE BREAK':'BULLISH STRUCTURE BREAK';
 const fvg=bearish?'BEARISH FVG':'BULLISH FVG';
 return studySweepConfluence(b,[
  event(sweep,20,[18,20]),event(structure,22,[20,22]),
  event(fvg,22,[20,21,22])
 ],{datasetId:'source-sha',instrument:'NSXUSD-CFD',frame:'1H',
  maxConfirmationBars:3,horizonBars:3,costScenariosBps:[0,5,15]});
}
const cfg={atrPeriod:14,stopAtrMultiple:0.25,rewardRisk:1,
 maxHoldBars:2,roundTripCostsBps:[0,5,15]};

test('same-bar target and stop resolve pessimistically to stop',()=>{
 const b=bars(),s=study(b),r=simulateConfluenceRiskPath(b,s,cfg);
 assert.equal(s.completed,1);assert.equal(r.closed,1);
 assert.equal(r.trades[0].reason,'STOP');
 assert.equal(r.trades[0].entryAt,BASE+23*H);
 assert.equal(r.trades[0].exitAt,BASE+24*H);
 assert.equal(r.trades[0].stop,99.5);
 assert.equal(r.trades[0].target,100.5);
 assert.equal(r.trades[0].exit,99.5);
 assert.ok(Math.abs(r.trades[0].netR[0]+1)<1e-10);
 assert.ok(r.trades[0].netR[2]<r.trades[0].netR[1]);
});

test('unambiguous target receives no favorable price improvement',()=>{
 const b=bars();b[23]={...b[23],low:99.8,high:102,close:101};
 const r=simulateConfluenceRiskPath(b,study(b),cfg);
 assert.equal(r.trades[0].reason,'TARGET');
 assert.equal(r.trades[0].exit,100.5);
 assert.ok(Math.abs(r.trades[0].netR[0]-1)<1e-10);
});

test('adverse opening gap is filled at worse opening price',()=>{
 const b=bars();
 b[23]={...b[23],high:100.2,low:99.8,close:100};
 b[24]={...b[24],open:98,high:99,low:97,close:98};
 const r=simulateConfluenceRiskPath(b,study(b),cfg);
 assert.equal(r.trades[0].reason,'STOP');
 assert.equal(r.trades[0].exit,98);
 assert.ok(r.trades[0].netR[0]<-1);
});

test('time exit uses completed last candle close, not future candle',()=>{
 const b=bars();
 for(const i of [23,24,25]){
  b[i]={...b[i],open:100,high:100.3,low:99.7,close:100.1};
 }
 const r=simulateConfluenceRiskPath(b,study(b),cfg);
 assert.equal(r.trades[0].reason,'TIME');
 assert.equal(r.trades[0].exit,100.1);
 assert.equal(r.trades[0].exitAt,BASE+25*H);
});

test('bearish observations invert stop/target and pessimistic fill',()=>{
 const b=bars(),r=simulateConfluenceRiskPath(b,study(b,true),cfg);
 assert.equal(r.trades[0].direction,'bearish');
 assert.equal(r.trades[0].stop,100.5);
 assert.equal(r.trades[0].target,99.5);
 assert.equal(r.trades[0].reason,'STOP');
});

test('later candles cannot alter earlier completed path',()=>{
 const b=bars(),s=study(b);
 const first=simulateConfluenceRiskPath(b.slice(0,26),s,cfg);
 const extended=simulateConfluenceRiskPath(b,s,cfg);
 assert.deepEqual(first.trades,extended.trades);
});

test('partial candle after entry censors outcome rather than inventing fill',()=>{
 const b=bars(),s=study(b);
 b[23]={...b[23],high:100.2,low:99.8,close:100};
 b[24]={...b[24],observed_minutes:59};
 const r=simulateConfluenceRiskPath(b,s,cfg);
 assert.equal(r.closed,0);assert.equal(r.gapExcluded,1);
 assert.deepEqual(r.meanNetBps,[null,null,null]);
});

test('warmup and cost configuration fail closed',()=>{
 const b=bars(),s=study(b);
 assert.equal(simulateConfluenceRiskPath(b,s,{...cfg,atrPeriod:25}).warmupExcluded,1);
 assert.throws(()=>simulateConfluenceRiskPath(b,s,{...cfg,maxHoldBars:4}),/Holding horizon/);
 assert.throws(()=>simulateConfluenceRiskPath(b,s,{...cfg,roundTripCostsBps:[5,5]}),/Round-trip costs/);
 assert.throws(()=>simulateConfluenceRiskPath(b,s,{...cfg,stopAtrMultiple:0}),/Stop ATR/);
});

test('tampered next-open and noncausal confirmation fail closed',()=>{
 const b=bars(),s=study(b);
 const tampered={...s,signals:s.signals.map(x=>({...x,entry:101}))};
 assert.throws(()=>simulateConfluenceRiskPath(b,tampered,cfg),/Entry price/);
 const future={...s,signals:s.signals.map(x=>({...x,sweepAt:x.confirmationAt}))};
 assert.throws(()=>simulateConfluenceRiskPath(b,future,cfg),/causal/);
});

test('no completed study signals never become profitable hypothetical trades',()=>{
 const b=bars(),s=study(b);
 const empty={...s,signals:[]};
 const r=simulateConfluenceRiskPath(b,empty,cfg);
 assert.equal(r.inputSignals,0);assert.equal(r.closed,0);
 assert.deepEqual(r.meanNetR,[null,null,null]);
});
