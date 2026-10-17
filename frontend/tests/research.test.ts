import {test} from 'node:test';
import assert from 'node:assert/strict';
import {parseCSV,aggregate,analyze,replayPrefix,type Bar} from '../lib/research.ts';
const csv='time,open,high,low,close\n2024-01-02T10:00:00Z,10,12,9,11\n2024-01-02T10:01:00Z,11,14,10,13\n2024-01-02T11:00:00Z,13,16,12,15\n';
const bar=(n:number,low:number,high:number,close=(low+high)/2):Bar=>({time:1704189600+n*60,open:(low+high)/2,low,high,close,volume:null,observed_minutes:1});
test('strict import preserves real UTC timestamps and aggregates observed rows only',()=>{
 const bars=parseCSV(csv);const hourly=aggregate(bars,'1H');assert.equal(hourly.length,2);assert.equal(hourly[0].open,10);assert.equal(hourly[0].close,13);assert.equal(hourly[0].observed_minutes,2);assert.equal(hourly[0].time,1704189600);
 assert.throws(()=>parseCSV(csv.replaceAll('Z','')));assert.throws(()=>parseCSV(csv+csv.split('\n')[1]+'\n'));assert.throws(()=>parseCSV(csv.replace('10,12','NaN,12')));
});
test('quoted fields, week and calendar month aggregation',()=>{
 assert.equal(parseCSV(csv.replace('10,12','"10","12"'))[0].open,10);
 const bars=[bar(0,1,3)];assert.equal(new Date(aggregate(bars,'1W')[0].time*1000).getUTCDay(),1);assert.equal(new Date(aggregate(bars,'1M')[0].time*1000).getUTCDate(),1);
});
test('sweep requires a confirmed swing and reclaim; first break never becomes SELL signal',()=>{
 const bars=[bar(0,10,14),bar(1,9,13),bar(2,5,12),bar(3,8,13),bar(4,9,14),bar(5,4,10,6)];
 assert.equal(analyze(bars.slice(0,5)).filter(d=>d.kind==='SELL-SIDE SWEEP').length,0);
 const detection=analyze(bars).find(d=>d.kind==='SELL-SIDE SWEEP');assert.ok(detection);assert.equal(detection.observed_at,bars[5].time+60);assert.match(detection.explanation,/WAIT/);
 const broken=[...bars.slice(0,5),bar(5,3,9,4)];assert.ok(analyze(broken).some(d=>d.kind==='BEARISH STRUCTURE BREAK'));assert.ok(analyze(broken).every(d=>!d.kind.includes('CONFIRMED')));
});
test('structure cannot appear until right-side swing confirmation and closing break',()=>{
 const bars=[bar(0,7,10),bar(1,8,12),bar(2,9,15),bar(3,8,13),bar(4,8,12),bar(5,11,17,16)];
 assert.equal(analyze(bars.slice(0,5)).filter(d=>d.kind==='BULLISH STRUCTURE BREAK').length,0);
 assert.equal(analyze(bars).find(d=>d.kind==='BULLISH STRUCTURE BREAK')?.observed_at,bars[5].time+60);
});
test('replay excludes future bars and future detections',()=>{
 const bars=[bar(0,7,10),bar(1,8,12),bar(2,13,15)];
 const prefix=replayPrefix(bars,2);assert.equal(prefix.length,2);assert.equal(analyze(prefix).length,0);assert.ok(analyze(bars).some(d=>d.kind==='BULLISH FVG'));
 assert.ok(analyze(prefix).every(d=>d.observed_at<=prefix.at(-1)!.time+60));
});
