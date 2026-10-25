import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyNyCloseMomentum,type StudyConfig} from '../lib/ny-close-momentum.ts';
import type {Bar} from '../lib/research.ts';

const cfg:StudyConfig={
 instrument:'NSXUSD-CFD',provider:'HistData',archiveId:'a'.repeat(64),
 archiveSha256:'b'.repeat(64),priceSide:'bid',assumedRoundTripBps:1.8,
};
// UTC starting instant of US equity 09:30 local; January = UTC 14:30,
// July = UTC 13:30. A weekend is skipped; no invented weekend sessions.
function series(n=23,july=false):Bar[]{
 const bars:Bar[]=[];
 const day=new Date(Date.UTC(2026,july?6:0,july?6:5));
 let sessions=0;
 while(sessions<n){
  if(day.getUTCDay()!==0&&day.getUTCDay()!==6){
   const start=Date.UTC(day.getUTCFullYear(),day.getUTCMonth(),day.getUTCDate(),july?13:14,30)/1000;
   const highVol=sessions>=20,base=100+4*sessions;
   for(let m=0;m<390;m++){
    const close=m===29?base+1:m===389?base+3:base;
    const open=m===360?base+2:base;
    bars.push({time:start+m*60,open,close,
      high:Math.max(open,close,highVol&&m===10?base+10:base+1),
      low:Math.min(open,close,base-1),volume:null,observed_minutes:1});
   }
   sessions++;
  }
  day.setUTCDate(day.getUTCDate()+1);
 }
 return bars;
}
test('volatility threshold uses only 20 PRIOR complete NY sessions and trades are next close',()=>{
 const b=series(),report=studyNyCloseMomentum(b,cfg);
 assert.equal(report.totalObservedSessions,23);
 assert.equal(report.completeSessions,23);
 assert.equal(report.candidateDays,3);
 assert.equal(report.volatilityGatedDays,3);
 assert.equal(report.trades.length,3);
 assert.ok(report.trades.every(t=>t.morningRangeBps>t.priorMedianMorningRangeBps));
 assert.ok(report.trades.every(t=>t.entryAt+30*60===t.exitAt));
 assert.ok(report.trades.every(t=>t.entry>0&&t.direction==='LONG'));
 assert.ok(report.trades.every(t=>t.grossBps>0));
 assert.equal(report.costs.length,4);
 assert.equal(report.costs[1].roundTripBps,1.8);
 assert.ok(report.costs[1].averageNetBps!<report.costs[0].averageNetBps!);
});
test('changing unseen closing outcome changes PnL, not that session entry eligibility',()=>{
 const b=series(),baseline=studyNyCloseMomentum(b,cfg);
 const last=[...b].map(x=>({...x}));
 last[last.length-1].close=98;
 last[last.length-1].low=98;
 const changed=studyNyCloseMomentum(last,cfg);
 assert.equal(changed.trades.length,baseline.trades.length);
 assert.deepEqual(changed.trades.map(t=>({time:t.entryAt,direction:t.direction})),
  baseline.trades.map(t=>({time:t.entryAt,direction:t.direction})));
 assert.ok(changed.trades.at(-1)!.grossBps<baseline.trades.at(-1)!.grossBps);
});
test('DST season uses real New York local market clock, not fixed UTC open',()=>{
 const result=studyNyCloseMomentum(series(23,true),cfg);
 assert.equal(result.trades.length,3);
 const first=result.trades[0];
 const date=new Date(first.entryAt*1000);
 assert.equal(date.getUTCHours(),19); // 15:30 NY daylight time
 assert.equal(date.getUTCMinutes(),30);
});
test('partial RTH sessions and absent history do not produce synthetic trades',()=>{
 const b=series(23);
 const trimmed=b.filter((_,i)=>i!==390*21+12);
 const result=studyNyCloseMomentum(trimmed,cfg);
 assert.equal(result.totalObservedSessions,23);
 assert.equal(result.completeSessions,22);
 assert.equal(result.rejected.INCOMPLETE_NY_SESSION,1);
 assert.equal(result.trades.length,1);
 assert.ok((result.rejected.INSUFFICIENT_20_PRIOR_COMPLETE_SESSIONS??0)>0);
 const tooShort=studyNyCloseMomentum(series(20),cfg);
 assert.equal(tooShort.trades.length,0);
 assert.equal(tooShort.costs[0].winRatePct,null);
});
test('quiet days are rejected after the frozen 20-session median gate',()=>{
 const b=series(23);
 // Make all morning sessions use the same low range, so later days cannot pass.
 for(let i=0;i<b.length;i++){const base=100+4*Math.floor(i/390);b[i].high=Math.max(b[i].open,b[i].close,base+1)}
 const result=studyNyCloseMomentum(b,cfg);
 assert.equal(result.candidateDays,3);
 assert.equal(result.trades.length,0);
 assert.equal(result.rejected.MORNING_VOLATILITY_NOT_ABOVE_PRIOR_20_MEDIAN,3);
 assert.equal(result.ungatedCosts[1].trades,3);
 assert.equal(result.costs[1].trades,0);
});
test('fail closed on source mismatch, candle gaps, invalid bps and unordered history',()=>{
 const b=series();
 assert.throws(()=>studyNyCloseMomentum(b,{...cfg,priceSide:'ask' as 'bid'}),/Source identity/);
 assert.throws(()=>studyNyCloseMomentum(b,{...cfg,assumedRoundTripBps:0}),/Source identity/);
 assert.throws(()=>studyNyCloseMomentum(b.slice().reverse(),cfg),/malformed/);
 const broken=b.map(x=>({...x}));
 broken[1].observed_minutes=0;
 assert.throws(()=>studyNyCloseMomentum(broken,cfg),/malformed/);
 const bad=b.map(x=>({...x}));
 bad[25].high=0;
 assert.throws(()=>studyNyCloseMomentum(bad,cfg),/malformed/);
});
