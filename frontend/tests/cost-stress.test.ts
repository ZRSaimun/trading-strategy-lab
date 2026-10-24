import {test} from 'node:test';
import assert from 'node:assert/strict';
import {backtest,DEFAULTS} from '../lib/backtest.ts';
import {runCostStress,COST_MULTIPLIERS} from '../lib/cost-stress.ts';
import type {Bar} from '../lib/research.ts';

const candle=(i:number,open=10,high=11,low=9,close=10):Bar=>({
 time:1700000040+i*60,open,high,low,close,volume:null,observed_minutes:1,
});
const bars=[
 candle(0),candle(1),candle(2),candle(3,10,13,9,12),
 candle(4,12,40,11,13),candle(5,13,14,11,13),
];
const cfg={...DEFAULTS,lookback:3,atrPeriod:3,barSeconds:60,
 capital:1000,riskPercent:1,spread:.4,slippage:.1,commission:.05};

test('cost stress reruns the engine with original strategy and 1x, 2x, 3x costs',()=>{
 const rows=runCostStress(bars,backtest(bars,'A',cfg));
 assert.deepEqual(rows.map(r=>r.multiplier),[...COST_MULTIPLIERS]);
 for(const row of rows){
  const expected=backtest(bars,'A',{...cfg,spread:cfg.spread*row.multiplier,
   slippage:cfg.slippage*row.multiplier,commission:cfg.commission*row.multiplier});
  assert.equal(row.spread,cfg.spread*row.multiplier);
  assert.equal(row.slippage,cfg.slippage*row.multiplier);
  assert.equal(row.commission,cfg.commission*row.multiplier);
  assert.equal(row.trades,expected.metrics.trades);
  assert.equal(row.netReturn,expected.metrics.netReturn);
  assert.equal(row.maxDrawdownPercent,expected.metrics.maxDrawdownPercent);
  assert.equal(row.expectancy,expected.metrics.expectancy);
  assert.equal(row.averageR,expected.metrics.averageR);
 }
});
test('cost stress is deterministic and does not mutate candles or saved configuration',()=>{
 const originalBars=structuredClone(bars),originalConfig={...cfg};
 assert.deepEqual(runCostStress(bars,backtest(bars,'B',cfg)),runCostStress(bars,backtest(bars,'B',cfg)));
 assert.deepEqual(bars,originalBars);
 assert.deepEqual(cfg,originalConfig);
});
test('rejects zero, negative, or non-finite baseline costs instead of inventing friction',()=>{
 assert.throws(()=>runCostStress(bars,backtest(bars,'A',{...cfg,spread:0,slippage:0,commission:0})),/nonzero/);
 assert.throws(()=>runCostStress(bars,{...backtest(bars,'A',cfg),config:{...cfg,spread:-.1}}),/nonnegative/);
 assert.throws(()=>runCostStress(bars,{...backtest(bars,'A',cfg),config:{...cfg,slippage:Infinity}}),/finite/);
});
test('fails closed when historical candles are incomplete or unordered',()=>{
 assert.throws(()=>runCostStress(bars.map((x,i)=>i===2?{...x,observed_minutes:0}:x),backtest(bars,'A',cfg)),/Incomplete/);
 assert.throws(()=>runCostStress([...bars.slice(1),bars[0]],backtest(bars,'A',cfg)),/snapshot/);
});

test('rejects stale strategy versions, snapshot changes and falsified saved results',()=>{
 const saved=backtest(bars,'A',cfg);
 assert.throws(()=>runCostStress(bars,{...saved,engine:'old-engine'}),/version/);
 assert.throws(()=>runCostStress(bars,{...saved,ruleVersion:'stale'}),/version/);
 assert.throws(()=>runCostStress(bars,{...saved,bars:saved.bars+1}),/snapshot/);
 assert.throws(()=>runCostStress(bars,{...saved,metrics:{...saved.metrics,netReturn:saved.metrics.netReturn+10}}),/not reproducible/);
});
