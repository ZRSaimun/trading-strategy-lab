/** Time-based, expanding-window research evaluation on an immutable saved candle snapshot.
 * Candidate lookbacks are selected using PAST training data only; each later
 * test period is simulated independently, with no positions crossing boundaries.
 * This is not an untouched holdout, real execution, or verified profitability.
 */
import {backtest,ENGINE,STRATEGIES,type Config,type Metrics,type StrategyId} from './backtest.ts';
import type {Bar} from './research.ts';
import type {ResearchRun} from './research-review.ts';

export type ForwardFold={
 number:number;
 training:{start:number;end:number;bars:number};
 testing:{start:number;end:number;bars:number};
 lookback:number;selection:'TRAIN_SELECTED'|'DEFAULT_INSUFFICIENT_TRADES';
 trainingTrades:number;trainingAverageR:number;
 testingTrades:number;testingReturn:number;testingAverageR:number;
 testingMaxDrawdownPercent:number;warnings:string[];
};
export type ForwardReview={
 strategy:StrategyId;ruleVersion:string;source:string;datasetHash:string;
 candidates:number[];folds:ForwardFold[];warnings:string[];
};

function lowerBound(bars:Bar[],time:number):number{
 let lo=0,hi=bars.length;
 while(lo<hi){const mid=(lo+hi)>>>1;if(bars[mid].time<time)lo=mid+1;else hi=mid}
 return lo;
}
function span(bars:Bar[],barSeconds:number){
 return {start:bars[0].time,end:bars[bars.length-1].time+barSeconds,bars:bars.length};
}
function validSnapshot(run:ResearchRun,strategy:StrategyId){
 if(!run?.payload||!Array.isArray(run.payload.candles))throw Error('Saved run has no candle snapshot; cannot perform forward evaluation');
 const bars=run.payload.candles;
 if(bars.length<500||bars.length>20000)throw Error('Time-based forward evaluation requires 500–20,000 saved aggregate candles');
 const matches=run.payload.reports?.filter(r=>r.strategy===strategy)||[];
 if(matches.length!==1)throw Error('Select a strategy with exactly one saved full-sample report');
 const report=matches[0];
 const version=STRATEGIES.find(s=>s.id===strategy)?.version;
 if(report.ruleVersion!==version||report.engine!==ENGINE)throw Error('Saved engine/rule version differs from this simulator; do not silently mix research definitions');
 const cfg=report.config;
 if(!cfg||!Number.isSafeInteger(cfg.barSeconds)||cfg.barSeconds<60||cfg.barSeconds%60!==0)throw Error('Saved report lacks a valid aggregate timeframe');
 if(!run.payload.window||run.payload.window.bars!==bars.length||
    run.payload.window.start!==bars[0]?.time||run.payload.window.end!==bars.at(-1)?.time)
  throw Error('Saved coverage metadata disagrees with the candle snapshot');
 // The underlying simulator will also check complete constituents, OHLC, ordering
 // and candidate-specific settings for each training/test segment.
 for(let i=0;i<bars.length;i++){
  const b=bars[i];
  if(!b||!Number.isFinite(b.time)||!Number.isFinite(b.open)||
     !Number.isFinite(b.high)||!Number.isFinite(b.low)||!Number.isFinite(b.close)||
     b.observed_minutes!==cfg.barSeconds/60||
     (i>0&&b.time-bars[i-1].time<cfg.barSeconds))
   throw Error('Saved candle snapshot is incomplete, malformed or not chronological');
 }
 return {bars,cfg,version};
}
export function runTimeBasedWalkForward(run:ResearchRun,strategy:StrategyId):ForwardReview{
 const {bars,cfg,version}=validSnapshot(run,strategy);
 const first=bars[0].time,lastEnd=bars.at(-1)!.time+cfg.barSeconds;
 const duration=lastEnd-first;
 const cutoffs=[2,3,4,5].map(i=>lowerBound(bars,first+duration*i/5));
 const candidates=[cfg.lookback,Math.max(3,Math.floor(cfg.lookback/2)),Math.min(500,cfg.lookback*2)]
  .filter((n,i,a)=>Number.isSafeInteger(n)&&n>=3&&n<=500&&a.indexOf(n)===i);
 if(!candidates.length)throw Error('No valid predeclared lookback settings in saved report');
 const folds:ForwardFold[]=[];
 for(let i=0;i<3;i++){
  const start=cutoffs[i],end=cutoffs[i+1],training=bars.slice(0,start),testing=bars.slice(start,end);
  if(training.length<200||testing.length<100)
   throw Error(`Time-based fold ${i+1} lacks 200 training or 100 test candles. Calendar gaps are not filled; use a longer, better-covered dataset.`);
  // Training selection is restricted to bars strictly BEFORE this fold's test start.
  const trials=candidates.map(lookback=>{
   const metrics=backtest(training,strategy,{...cfg,lookback}).metrics;
   return {lookback,metrics};
  });
  const eligible=trials.filter(x=>x.metrics.trades>=30);
  // No 30-trade training candidate means NO parameter selection: use the
  // saved original setting, rather than optimizing noisy short samples.
  const selected=eligible.length?
   eligible.reduce((best,next)=>next.metrics.averageR>best.metrics.averageR?next:best):
   trials.find(x=>x.lookback===cfg.lookback)!;
  const out:Metrics=backtest(testing,strategy,{...cfg,lookback:selected.lookback}).metrics;
  const warnings:string[]=[];
  if(!eligible.length)warnings.push('Fewer than 30 training trades per eligible candidate: original saved lookback used without fitting.');
  if(selected.metrics.averageR<0)warnings.push('Selected training sample has negative simulated average R.');
  if(out.trades<30)warnings.push('Fewer than 30 simulated test trades; insufficient evidence of robustness.');
  if(out.netReturn<0)warnings.push('Negative forward-period simulated return after assumed costs.');
  if(out.maxDrawdownPercent>=20)warnings.push('Simulated close-marked drawdown reaches at least 20%.');
  folds.push({
   number:i+1,training:span(training,cfg.barSeconds),testing:span(testing,cfg.barSeconds),
   lookback:selected.lookback,selection:eligible.length?'TRAIN_SELECTED':'DEFAULT_INSUFFICIENT_TRADES',
   trainingTrades:selected.metrics.trades,trainingAverageR:selected.metrics.averageR,
   testingTrades:out.trades,testingReturn:out.netReturn,testingAverageR:out.averageR,
   testingMaxDrawdownPercent:out.maxDrawdownPercent,warnings
  });
 }
 const warnings=[
  'Expanding training windows overlap; three forward test windows are chronological and non-overlapping, but the saved history is not a locked, unseen final holdout.',
  'This is limited lookback selection among predeclared variants, not general strategy optimization. Trying more ideas after inspecting results causes selection bias.',
  'Every test window starts with independent warmup and capital. Trades cannot cross its boundaries; returns are not additive or a compound live equity curve.',
  'OHLC-only fills, modelled costs, missing ask prices and repeated historical inspection limit real-world inference.'
 ];
 if(!run.payload.source||!run.payload.datasetHash||
    /unknown/i.test(run.payload.source)||/unknown/i.test(run.payload.datasetHash))
  warnings.push('Saved source identity or dataset fingerprint is unknown; verify provenance before interpreting results.');
 if(/capp?ed|not a full archive|limited window/i.test(run.payload.notes||''))
  warnings.push('The saved history was capped or incomplete. This evaluation does not cover the full archive.');
 return {strategy,ruleVersion:version!,source:run.payload.source||'Unknown',
  datasetHash:run.payload.datasetHash||'Unknown',candidates,folds,warnings};
}
