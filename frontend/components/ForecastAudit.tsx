'use client';
import {useEffect,useState} from 'react';
import {auditRollingDirection,type ForecastAudit as Audit} from '../lib/forecast-audit';
import {reviewForecastStability} from '../lib/forecast-stability';
import {loadArchiveWindow,type ArchivePage} from '../lib/backtest-history';
import type {Bar} from '../lib/research';

type API=(path:string,init?:RequestInit)=>Promise<any>;
type Archive={id:string;provider:string;instrument:string;format:string;state:string;accepted:number};
const FRAMES={'1m':60,'5m':300,'15m':900,'1H':3600} as const;
const number=(v:number|null,d=4)=>v===null?'—':v.toFixed(d);
const time=(v:number|null)=>v===null?'—':new Date(v*1000).toISOString();

export default function ForecastAudit({api,pages}:{api:API;pages:boolean}){
 const [sourceMode,setSourceMode]=useState<'legacy'|'archive'>('legacy');
 const [instrument,setInstrument]=useState('XAUUSD-IMPORT');
 const [frame,setFrame]=useState<keyof typeof FRAMES>('5m');
 const [window,setWindow]=useState(40);
 const [archives,setArchives]=useState<Archive[]>([]),[archiveId,setArchiveId]=useState('');
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 const [result,setResult]=useState<{audit:Audit;source:string;hash:string;instrument:string;start:number;end:number;capped:boolean}|null>(null);
 useEffect(()=>{
  if(pages||sourceMode!=='archive')return;
  let active=true;
  api('/history/datasets').then((v:Archive[])=>{
   if(!active)return;
   const ready=v.filter(x=>x.state==='READY');
   setArchives(ready);setArchiveId(old=>ready.some(a=>a.id===old)?old:ready[0]?.id||'');
  }).catch(e=>{if(active)setError(e instanceof Error?e.message:String(e))});
  return()=>{active=false};
 },[api,pages,sourceMode]);
 async function run(){
  setBusy(true);setError('');setResult(null);
  try{
   let candles:Bar[],source:string,hash:string,exactInstrument:string,capped:boolean;
   if(sourceMode==='archive'){
    const archive=archives.find(a=>a.id===archiveId);
    if(!archive)throw Error('Select an imported READY archive');
    const w=await loadArchiveWindow(archiveId,frame,async(before,limit)=>{
     const params=new URLSearchParams({timeframe:frame,limit:String(limit)});
     if(before!==null)params.set('before',String(before));
     return await api(`/history/${encodeURIComponent(archiveId)}/candles?${params}`) as ArchivePage;
    });
    candles=w.bars;source=`${w.dataset.provider} · ${archive.format} · historical BID only`;
    hash=w.dataset.archive_sha256;exactInstrument=w.dataset.instrument;capped=w.capped;
   }else{
    const data=await api(`/candles/${instrument}?timeframe=${frame}`);
    if(data.quality?.live===true)throw Error('Only historical completed candles are supported');
    candles=data.candles;source=data.dataset?.source;hash=data.dataset?.sha256;
    exactInstrument=instrument;capped=Boolean(data.has_more);
   }
   if(!source||!/^[a-f0-9]{64}$/.test(hash))throw Error('Historical source provenance/hash is missing; refusing unverified data');
   if(!Array.isArray(candles)||!candles.length)throw Error('Import historical candles before evaluating forecast calibration');
   const audit=auditRollingDirection(candles,FRAMES[frame],window);
   setResult({audit,source,hash,instrument:exactInstrument,start:candles[0].time,end:candles.at(-1)!.time,capped});
  }catch(e){setError(e instanceof Error?e.message:String(e))}
  finally{setBusy(false)}
 }
 return <section className="panel research-panel">
  <span className="eyebrow">HISTORICAL PROBABILITY RESEARCH · NO LIVE SIGNALS</span>
  <h2>Forecast Calibration Audit</h2>
  <p>Evaluate a simple rolling, smoothed probability of the close being higher after 1, 3 or 12 bars. Each forecast uses only outcomes already known when issued. Results are scored only after future candles close. This is a baseline research model, not a BUY/SELL recommendation or evidence of net trading profit.</p>
  {error&&<p role="alert" className="error">{error}</p>}
  <div className="backtest-settings">
   {!pages&&<label>Historical source<select value={sourceMode} onChange={e=>{setSourceMode(e.target.value as 'legacy'|'archive');setResult(null)}}><option value="legacy">Imported chart CSV</option><option value="archive">Ready source-isolated archive</option></select></label>}
   {sourceMode==='archive'?<label>Exact archive<select value={archiveId} onChange={e=>{setArchiveId(e.target.value);setResult(null)}}><option value="">Choose ready archive</option>{archives.map(a=><option key={a.id} value={a.id}>{a.instrument} · {a.provider} · {a.id.slice(0,8)} · {a.accepted.toLocaleString()} minutes</option>)}</select></label>:<label>Exact instrument<select value={instrument} onChange={e=>{setInstrument(e.target.value);setResult(null)}}><option value="XAUUSD-IMPORT">Gold · imported CSV</option><option value="NDX-IMPORT">Nasdaq-100 cash index · imported CSV</option>{!pages&&<option value="XAUUSD-TD">Gold · authorized historical adapter</option>}</select></label>}
   <label>Completed candle timeframe<select value={frame} onChange={e=>{setFrame(e.target.value as keyof typeof FRAMES);setResult(null)}}>{Object.keys(FRAMES).map(f=><option key={f}>{f}</option>)}</select></label>
   <label>Prior matured outcomes<select value={window} onChange={e=>{setWindow(Number(e.target.value));setResult(null)}}>{[40,100,250].map(w=><option key={w} value={w}>{w}</option>)}</select></label>
  </div>
  <button className="primary" onClick={run} disabled={busy}>{busy?'Evaluating completed historical bars…':'Run historical calibration audit'}</button>
  {result&&<>
   <p><strong>Source:</strong> {result.instrument} · {result.source}<br/><strong>SHA-256:</strong> <code>{result.hash}</code><br/><strong>Window:</strong> {time(result.start)} to {time(result.end)} · {result.audit.completeBars.toLocaleString()} complete bars · {result.audit.excludedBars} partial bars excluded · {result.audit.segments} contiguous segments.</p>
   {result.capped&&<p role="status" className="banner">Only the latest bounded historical window was evaluated. This is not the entire archive; earlier observations remain outside the audit.</p>}
   <p><strong>Model:</strong> {result.audit.version} · {result.audit.window} prior matured outcomes, Beta({result.audit.alpha},{result.audit.alpha}) smoothing. Fixed 50% reference forecast; Brier skill above zero means improvement against that reference on this same historical sample only. Scores do not include spreads, slippage, commissions or trading rules.</p>
   <div className="table-wrap"><table><thead><tr><th>Horizon</th><th>Evaluated</th><th>Brier ↓</th><th>50% baseline</th><th>Brier skill</th><th>Log loss ↓</th><th>Calibration error ↓</th></tr></thead><tbody>{result.audit.horizons.map(h=><tr key={h.horizon}><td>{h.horizon} bars</td><td>{h.samples.toLocaleString()}</td><td>{number(h.brier)}</td><td>{number(h.baselineBrier)}</td><td>{h.brierSkill===null?'—':(h.brierSkill*100).toFixed(2)+'%'}</td><td>{number(h.logLoss)}</td><td>{number(h.calibrationError)}</td></tr>)}</tbody></table></div>
   <h3>Historical score stability · fixed-window review</h3>
   <p>Compare the last 100 matured evaluations with the preceding 100, separately for each horizon. If those 200 evaluations span any missing or non-contiguous candle interval, the comparison is withheld as insufficient rather than joining unrelated periods. A review flag means recent Brier loss is at least 0.02 worse than the earlier window or exceeds the fixed 50% baseline (0.25). These are descriptive thresholds, not statistically significant drift detection, live alerts, or trading signals. Overlapping multi-bar outcomes are correlated.</p>
   <div className="table-wrap"><table><thead><tr><th>Horizon</th><th>Earlier Brier</th><th>Recent Brier</th><th>Change (recent − earlier)</th><th>Review status</th></tr></thead><tbody>
    {result.audit.horizons.map(h=>{
     const s=reviewForecastStability(h.evaluations,h.horizon as 1|3|12,FRAMES[frame],100);
     return <tr key={h.horizon}><td>{h.horizon} bars</td><td>{number(s.earlier?.brier??null)}</td><td>{number(s.recent?.brier??null)}</td><td>{number(s.deltaBrier)}</td><td>{s.status==='INSUFFICIENT'?'Insufficient settled samples':s.status==='REVIEW'?'Review deterioration':'No threshold flag'}{s.reasons.length>0?' · '+s.reasons.join(' '):''}</td></tr>;
    })}
   </tbody></table></div>
   {result.audit.horizons.map(h=><details key={h.horizon} className="rule-definitions"><summary>{h.horizon}-bar horizon · calibration buckets and last ten settled forecasts</summary>
    <p>First evaluated: {time(h.firstEvaluatedAt)} · Last evaluated: {time(h.lastEvaluatedAt)}. Overlapping horizon outcomes are correlated; small bins are unreliable.</p>
    <div className="table-wrap"><table><thead><tr><th>Forecast probability</th><th>Count</th><th>Mean forecast</th><th>Observed up rate</th></tr></thead><tbody>{h.bins.map(b=><tr key={b.from}><td>{Math.round(b.from*100)}–{Math.round(b.to*100)}%</td><td>{b.count}</td><td>{b.meanForecast===null?'—':(b.meanForecast*100).toFixed(1)+'%'}</td><td>{b.observedUpRate===null?'—':(b.observedUpRate*100).toFixed(1)+'%'}</td></tr>)}</tbody></table></div>
    <div className="table-wrap"><table><thead><tr><th>Issued after close (UTC)</th><th>Evaluated at close (UTC)</th><th>Predicted up</th><th>Actual</th></tr></thead><tbody>{h.recent.map(s=><tr key={s.observedAt}><td>{time(s.observedAt)}</td><td>{time(s.evaluatedAt)}</td><td>{(s.probability*100).toFixed(1)}%</td><td>{s.up?'Higher':'Not higher'}</td></tr>)}</tbody></table></div>
   </details>)}
   <p>Research limitation: this uses past historical candles, not executable quotes. It does not estimate expected P&amp;L or promise a live advantage. Treat repeated model selection on the same history as overfitting; use a new untouched forward sample before considering a strategy.</p>
  </>}
 </section>;
}
