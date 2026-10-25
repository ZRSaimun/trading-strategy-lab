'use client';
import {useEffect,useRef,useState,type FormEvent} from 'react';
import {createChart,CandlestickSeries,ColorType,type UTCTimestamp} from 'lightweight-charts';

type Bar={time:number;open:number;high:number;low:number;close:number;volume:number};
type Summary={id:string;filename:string;rows:number;start:number;end:number;price_side:string;interval_seconds:number;sha256:string};
type Dataset=Summary&{candles:Bar[];unobserved_spans:{start:number;end:number;unobserved_intervals:number}[]};
const utc=(t:number)=>new Date(t*1000).toISOString().replace('T',' ').replace('.000Z',' UTC');
async function request(path='',init?:RequestInit){
 const response=await fetch('/api/gold-csv'+path,init);
 if(!response.ok){const body=await response.json().catch(()=>null);throw Error(typeof body?.detail==='string'?body.detail:`Request failed (${response.status})`)}
 return response.json();
}
export default function GoldCsvResearch({pages,light}:{pages:boolean;light:boolean}){
 const [items,setItems]=useState<Summary[]>([]),[data,setData]=useState<Dataset|null>(null);
 const [error,setError]=useState(''),[busy,setBusy]=useState(false),[selected,setSelected]=useState('');
 const [count,setCount]=useState(0),[replay,setReplay]=useState(false);
 const host=useRef<HTMLDivElement>(null),generation=useRef(0);
 useEffect(()=>{if(pages)return;let active=true;request().then(x=>{if(active)setItems(x)}).catch(e=>{if(active)setError(String(e))});return()=>{active=false}},[pages]);
 useEffect(()=>{
  if(!host.current||!data)return;
  const chart=createChart(host.current,{autoSize:true,height:420,layout:{background:{type:ColorType.Solid,color:light?'#ffffff':'#101620'},textColor:light?'#172536':'#dbe4ee'},timeScale:{timeVisible:true}});
  const series=chart.addSeries(CandlestickSeries);
  series.setData(data.candles.slice(0,replay?count:data.candles.length).map(b=>({...b,time:b.time as UTCTimestamp})));
  chart.timeScale().fitContent();return()=>chart.remove();
 },[data,count,replay,light]);
 async function choose(id:string){
  const ticket=++generation.current;setSelected(id);setData(null);setError('');setReplay(false);
  if(!id)return;setBusy(true);
  try{const d=await request('/'+id);if(ticket===generation.current){setData(d);setCount(1)}}
  catch(e){if(ticket===generation.current)setError(String(e))}
  finally{if(ticket===generation.current)setBusy(false)}
 }
 async function upload(event:FormEvent<HTMLFormElement>){
  event.preventDefault();const form=new FormData(event.currentTarget);setBusy(true);setError('');
  const ticket=++generation.current;
  try{const d=await request('',{method:'POST',body:form});if(ticket===generation.current){setItems(old=>[...old.filter(x=>x.id!==d.id),d]);setSelected(d.id);setData(d);setCount(1);setReplay(false)}}
  catch(e){if(ticket===generation.current)setError(String(e))}
  finally{if(ticket===generation.current)setBusy(false)}
 }
 if(pages)return <section className="panel"><h2>Gold CSV Research</h2><p>Open your authenticated private deployment to import and save native hourly or one-minute Gold CSV files.</p></section>;
 return <section className="panel">
  <span className="eyebrow">HISTORICAL RESEARCH · NATIVE TIMEFRAME</span><h2>Gold CSV Research</h2>
  <p>Import an original XAU-USD Dukascopy-format CSV with UTC timestamps. Hourly bars remain hourly. BID and ASK exports stay separate. Saved files are available after refreshing this private website.</p>
  <form onSubmit={upload}>
   <label>Original 1Hour or 1Min BID / ASK CSV<input name="file" type="file" accept=".csv,text/csv" required disabled={busy}/></label>
   <label className="checkbox"><input name="rights_confirmed" type="checkbox" value="true" required disabled={busy}/>I am authorized to use this export for private research.</label>
   <button className="primary" disabled={busy}>{busy?'Working…':'Validate & save Gold CSV'}</button>
  </form>
  <p>Up to 1 MB and 5,000 candles per file. Keep the original filename and headers. Empty, duplicate, future, incomplete or malformed candles are rejected.</p>
  {error&&<p role="alert">{error}</p>}
  <label>Saved dataset<select value={selected} disabled={busy} onChange={e=>choose(e.target.value)}><option value="">Select a file</option>{items.map(d=><option key={d.id} value={d.id}>{d.filename} · {d.rows} bars</option>)}</select></label>
  {data&&<>
   <h3>XAU/USD · {data.interval_seconds===3600?'1 hour':'1 minute'} · {data.price_side}</h3>
   <p>{data.rows.toLocaleString()} candles · {utc(data.start)} to {utc(data.end)}</p>
   <p>{data.unobserved_spans.length} unobserved spans between candles. These may include session closures or missing observations; completeness is unverified.</p>
   <p><strong>Volume classification unknown.</strong> A nonzero Volume column does not establish exchange volume or justify volume-based confirmations. A single price side cannot establish spreads; differences between BID/ASK hourly highs or lows are not observed spreads.</p>
   <p>This chart does not feed minute-based strategy backtests or live signals. Source authenticity and broker equivalence remain unverified.</p>
   <div className="drawing-tools"><button onClick={()=>{setReplay(!replay);setCount(1)}}>{replay?'Exit replay':'Replay from first candle'}</button>{replay&&<><button disabled={count<=1} onClick={()=>setCount(n=>n-1)}>Previous</button><button disabled={count>=data.rows} onClick={()=>setCount(n=>n+1)}>Next</button><span>{count} / {data.rows} candles revealed</span></>}</div>
   <div ref={host} style={{height:420}} aria-label="Native timeframe Gold candlestick chart"/>
   <details><summary>Dataset provenance</summary><p>SHA-256: <code style={{overflowWrap:'anywhere'}}>{data.sha256}</code></p><p>User-supplied Dukascopy-format export · UTC · historical only.</p></details>
  </>}
 </section>;
}
