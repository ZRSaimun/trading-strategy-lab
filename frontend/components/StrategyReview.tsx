'use client';
import {useEffect,useMemo,useState} from 'react';
import {reviewResearchRun,type ResearchRun,type SnapshotMetrics,type ReviewFinding} from '../lib/research-review';
import {runTimeBasedWalkForward,type ForwardReview} from '../lib/walk-forward';
import {STRATEGIES,type StrategyId} from '../lib/backtest';

type API=(path:string,init?:RequestInit)=>Promise<any>;
const fmt=(n:number|null|undefined,d=2)=>n===null||n===undefined?'—':n.toLocaleString('en-GB',{maximumFractionDigits:d});
function metricCell(value:SnapshotMetrics|null,field:'trades'|'netReturn'|'maxDrawdownPercent'){
 if(!value)return '—';
 return field==='trades'?String(value.trades):fmt(value[field])+'%';
}
function Finding({item}:{item:ReviewFinding}){
 return <li><strong>{item.severity==='caution'?'Review required':'Context'}:</strong> {item.message}</li>;
}

/** Read-only interpretation of saved backtests, with explicit no-profit disclaimer. */
export default function StrategyReview({api}:{api:API}){
 const [runs,setRuns]=useState<ResearchRun[]>([]);
 const [selected,setSelected]=useState('');
 const [loading,setLoading]=useState(true);
 const [error,setError]=useState('');
 const [forwardStrategy,setForwardStrategy]=useState<StrategyId>('A');
 const [forward,setForward]=useState<ForwardReview|null>(null);
 const [forwardError,setForwardError]=useState('');
 const [forwardBusy,setForwardBusy]=useState(false);
 function clearForward(){setForward(null);setForwardError('')}
 async function refresh(){
  setLoading(true);setError('');clearForward();
  try{
   const data=await api('/research/backtests');
   if(!Array.isArray(data))throw Error('Expected saved backtest records');
   setRuns(data);
   setSelected(old=>data.some(r=>r.id===old)?old:data[0]?.id||'');
  }catch(e){setError(e instanceof Error?e.message:String(e))}
  finally{setLoading(false)}
 }
 useEffect(()=>{void refresh()},[]);
 const chosen=runs.find(r=>r.id===selected);
 const computed=useMemo(()=>{
  if(!chosen)return {review:null,error:''};
  try{return {review:reviewResearchRun(chosen),error:''}}
  catch(e){return {review:null,error:e instanceof Error?e.message:String(e)}}
 },[chosen]);
 const review=computed.review;
 return <section className="panel research-panel">
  <span className="eyebrow">RESEARCH ROBUSTNESS · SAVED SIMULATIONS ONLY</span>
  <h2>Strategy Robustness Review</h2>
  <p>Inspect the development, validation and holdout metrics already saved by Backtesting. This review uses no future data or fresh market prices, and does not verify live performance. All thresholds are descriptive research checks, not statistical proof.</p>
  <div className="backtest-settings">
   <label>Saved historical backtest
    <select aria-label="Saved historical backtest" value={selected} onChange={e=>{setSelected(e.target.value);clearForward()}} disabled={!runs.length}>
     {!runs.length&&<option value="">No saved backtests</option>}
     {runs.map(r=><option key={r.id} value={r.id}>{r.title||r.id} · {new Date(r.created_at*1000).toISOString().slice(0,10)}</option>)}
    </select>
   </label>
  </div>
  <button onClick={()=>void refresh()} disabled={loading}>{loading?'Checking saved research…':'Refresh saved backtests'}</button>
  {error&&<p className="error" role="alert">{error}</p>}
  {!loading&&!runs.length&&<p>No saved simulations available. Open Backtesting, run the defined historical strategies, then save a report. This page analyses saved results; it cannot generate market data.</p>}
  {computed.error&&<p className="error" role="alert">Saved run cannot be reviewed safely: {computed.error}</p>}
  {review&&<>
   <h3>{review.title}</h3>
   <p>Source: {review.source}<br/>Source fingerprint: <code>{review.datasetHash}</code><br/>
    {review.window?<>Recorded sample: {review.window.bars.toLocaleString()} aggregate bars, {new Date(review.window.start*1000).toISOString()} to {new Date(review.window.end*1000).toISOString()}</>:'No saved sample coverage metadata'}
   </p>
   <h3>Chronological performance comparisons</h3>
   <div className="table-wrap"><table><thead><tr>
    <th>Versioned rule</th><th>All trades</th><th>Development return</th>
    <th>Validation return</th><th>Holdout return</th><th>Holdout trades</th><th>Holdout max DD</th>
   </tr></thead><tbody>{review.strategies.map(s=><tr key={s.strategy}>
    <td>{s.strategy} · {s.ruleVersion}</td><td>{metricCell(s.full,'trades')}</td>
    <td>{metricCell(s.development,'netReturn')}</td>
    <td>{metricCell(s.validation,'netReturn')}</td>
    <td>{metricCell(s.holdout,'netReturn')}</td>
    <td>{metricCell(s.holdout,'trades')}</td>
    <td>{metricCell(s.holdout,'maxDrawdownPercent')}</td>
   </tr>)}</tbody></table></div>
   <h3>Dataset and evaluation limitations</h3>
   <ul>{review.runFindings.map(f=><Finding key={f.code} item={f}/>)}</ul>
   <h3>Strategy-specific evidence checks</h3>
   {review.strategies.map(s=><details key={s.strategy} open={s.findings.some(f=>f.severity==='caution')}>
    <summary>Strategy {s.strategy} · {s.findings.filter(f=>f.severity==='caution').length} caution(s)</summary>
    {s.findings.length?<ul>{s.findings.map(f=><Finding item={f} key={f.code}/>)}</ul>:<p>No automatic caution threshold triggered. That does not mean a profitable edge has been proven.</p>}
   </details>)}
   <h3>Time-based expanding-window forward evaluation</h3>
   <p>Optional research stress test on the <em>saved candle snapshot</em>. Each fold uses earlier time for training, selects among at most three predefined lookbacks only when the training sample has enough trades, then independently tests the following time window. No orders, live data or fitting on test candles.</p>
   <div className="backtest-settings"><label>Versioned strategy
    <select aria-label="Walk-forward strategy" value={forwardStrategy} onChange={e=>{setForwardStrategy(e.target.value as StrategyId);clearForward()}}>
     {STRATEGIES.filter(s=>review.strategies.some(r=>r.strategy===s.id)).map(s=><option key={s.id} value={s.id}>{s.name}</option>)}
    </select>
   </label></div>
   <button disabled={forwardBusy||!chosen} onClick={async()=>{
    if(!chosen)return;
    setForwardBusy(true);clearForward();
    await new Promise(resolve=>setTimeout(resolve,0));
    try{setForward(runTimeBasedWalkForward(chosen,forwardStrategy))}
    catch(e){setForwardError(e instanceof Error?e.message:String(e))}
    finally{setForwardBusy(false)}
   }}>{forwardBusy?'Evaluating saved history…':'Run three time-based forward folds'}</button>
   {forwardError&&<p role="alert" className="error">Forward evaluation unavailable: {forwardError}</p>}
   {forward&&<>
    <p>Rule: {forward.strategy} · {forward.ruleVersion}. Predeclared lookbacks: {forward.candidates.join(', ')} bars. The 3 forward windows never overlap; training windows expand.</p>
    <div className="table-wrap"><table><thead><tr><th>Fold</th><th>Training UTC</th><th>Forward test UTC</th><th>Selected lookback</th><th>Training trades</th><th>Test trades</th><th>Test return</th><th>Test average R</th><th>Test max DD</th></tr></thead>
     <tbody>{forward.folds.map(f=><tr key={f.number}>
      <td>{f.number}</td>
      <td>{new Date(f.training.start*1000).toISOString().slice(0,10)} – {new Date(f.training.end*1000).toISOString().slice(0,10)} ({f.training.bars} bars)</td>
      <td>{new Date(f.testing.start*1000).toISOString().slice(0,10)} – {new Date(f.testing.end*1000).toISOString().slice(0,10)} ({f.testing.bars} bars)</td>
      <td>{f.lookback} {f.selection==='DEFAULT_INSUFFICIENT_TRADES'?'(default)':'(training-selected)'}</td>
      <td>{f.trainingTrades}</td><td>{f.testingTrades}</td>
      <td>{fmt(f.testingReturn)}%</td><td>{fmt(f.testingAverageR)}</td>
      <td>{fmt(f.testingMaxDrawdownPercent)}%</td>
     </tr>)}</tbody></table></div>
    {forward.folds.map(f=><details key={f.number}><summary>Fold {f.number} · {f.warnings.length} caution(s)</summary>
     {f.warnings.length?<ul>{f.warnings.map(w=><li key={w}>{w}</li>)}</ul>:<p>No automatic warning triggered; this is not evidence of a verified trading edge.</p>}
    </details>)}
    <h3>Forward-evaluation limitations</h3><ul>{forward.warnings.map(w=><li key={w}>{w}</li>)}</ul>
   </>}
   <p><strong>Interpretation:</strong> Strong-looking or stable historical results can still be due to chance, repeated hypothesis selection, incomplete data, wrong costs or modelling assumptions. Before forward research, use independently secured out-of-sample data and paper trading. This page cannot tell you which strategy to trade or guarantee returns.</p>
  </>}
 </section>;
}
