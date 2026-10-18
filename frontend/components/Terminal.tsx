'use client';
import {installIndicators,STUDIES,type Study} from './ResearchIndicators';
import {volumeAvailable} from '../lib/indicators';
import WorkspaceBackup from './WorkspaceBackup';
import DataConnection from './DataConnection';
import MarketCharts from './MarketCharts';
import Alerts from './Alerts';
import {evaluateAdvance,type AlertRule,type AlertEvent} from '../lib/alerts';
import Backtesting from './Backtesting';
import {localAPI} from '../lib/local-api';
import {analyze,replayPrefix} from '../lib/research';
import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {createChart,CandlestickSeries,ColorType,LineStyle,type IChartApi,type ISeriesApi,type Time,type UTCTimestamp} from 'lightweight-charts';

type Point={time:number;price:number};
type Drawing={id:string;kind:'horizontal'|'trendline'|'rectangle'|'note';points:Point[];text:string;version:number;provenance?:string};
type Bar={time:number;open:number;high:number;low:number;close:number;volume:number|null;observed_minutes:number};
type Dataset={source:string;rows:number;start:number;end:number;gaps:number;volume_type:string;sha256:string};
type Payload={candles:Bar[];has_more?:boolean;dataset:Dataset|null;quality:{state:string;message?:string}};
const FRAMES=['1m','3m','5m','15m','30m','1H','2H','4H','1D','1W','1M'];
const PAGES=process.env.NEXT_PUBLIC_DEPLOYMENT==='pages';
const NAV=['Market Charts','Charts','Backtesting','Trading Journal','Research Alerts','Watchlist','Data Sources','Data Connection','Audit Log'];
async function api(path:string,init?:RequestInit){if(PAGES)return localAPI(path,init);const res=await fetch('/api'+path,init);if(!res.ok){let msg=await res.text();try{msg=JSON.parse(msg).detail}catch{}throw Error(typeof msg==='string'?msg:JSON.stringify(msg))}return res.json()}
const json=(body:unknown)=>({headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
const stamp=(t:number)=>new Date(t*1000).toLocaleString('en-GB',{timeZone:'Europe/London',timeZoneName:'short'});

export default function Terminal(){
 const [authenticated,setAuthenticated]=useState(false),[checking,setChecking]=useState(true),[password,setPassword]=useState('');
 const [error,setError]=useState(''),[notice,setNotice]=useState(''),[page,setPage]=useState('Market Charts');
 const [instrument,setInstrument]=useState('XAUUSD-IMPORT'),[frame,setFrame]=useState('5m');
 const [payload,setPayload]=useState<Payload>({candles:[],dataset:null,quality:{state:'NO DATA'}});
 const [drawings,setDrawings]=useState<Drawing[]>([]),[selected,setSelected]=useState<Drawing|null>(null);
 const [tool,setTool]=useState<Drawing['kind']|null>(null),[first,setFirst]=useState<Point|null>(null);
 const [watchlist,setWatchlist]=useState<string[]>([]),[logs,setLogs]=useState<Array<{id:number;time:number;action:string;detail:unknown}>>([]);
 const [replaying,setReplaying]=useState(false),[cursor,setCursor]=useState(1);
 const [alertRules,setAlertRules]=useState<AlertRule[]>([]),[alertGeneration,setAlertGeneration]=useState(0),[alertsReady,setAlertsReady]=useState(false),[latestAlert,setLatestAlert]=useState<AlertEvent|null>(null);
 const seenAlertIds=useRef(new Set<string>()),alertQueue=useRef(Promise.resolve());
 const lastRevealed=useRef<{key:string;count:number}|null>(null);
 const [busy,setBusy]=useState(false),[light,setLight]=useState(true);
 const host=useRef<HTMLDivElement>(null),chart=useRef<IChartApi|null>(null),series=useRef<ISeriesApi<'Candlestick'>|null>(null);
 const [studies,setStudies]=useState<Study[]>([]),[hovered,setHovered]=useState<Bar|null>(null);
 const [revision,setRevision]=useState(0),[dataRevision,setDataRevision]=useState(0);
 const loadGeneration=useRef(0);
 const toolRef=useRef(tool),firstRef=useRef(first),instrumentRef=useRef(instrument),frameRef=useRef(frame);
 toolRef.current=tool;firstRef.current=first;instrumentRef.current=instrument;frameRef.current=frame;
 const changeInstrument=(next:string)=>{instrumentRef.current=next;loadGeneration.current++;setInstrument(next);setHovered(null);setSelected(null);setDrawings([]);setFirst(null);setTool(null);setPayload({candles:[],dataset:null,quality:{state:'NO DATA'}})};
 const changeFrame=(next:string)=>{frameRef.current=next;loadGeneration.current++;setFrame(next);setHovered(null);setSelected(null);setDrawings([]);setFirst(null);setTool(null);setPayload({candles:[],dataset:null,quality:{state:'NO DATA'}})};
 useEffect(()=>{try{const saved=localStorage.getItem('tsl-theme');setLight(saved!=='dark')}catch{}},[]);
 useEffect(()=>{document.documentElement.dataset.theme=light?'light':'dark'},[light]);
 const toggleTheme=()=>{const next=!light;setLight(next);try{localStorage.setItem('tsl-theme',next?'light':'dark')}catch{}};
 const report=useCallback((e:unknown)=>setError(e instanceof Error?e.message:String(e)),[]);
 useEffect(()=>{api('/me').then(()=>setAuthenticated(true)).catch(()=>{}).finally(()=>setChecking(false))},[]);
 const reload=useCallback(async()=>{
   if(instrumentRef.current!==instrument||frameRef.current!==frame)return;
   const generation=++loadGeneration.current;
   setPayload({candles:[],dataset:null,quality:{state:'NO DATA'}});setDrawings([]);setSelected(null);
   const [p,d]=await Promise.all([api('/candles/'+instrument+'?timeframe='+frame),api('/drawings/'+instrument)]);
   if(generation!==loadGeneration.current||instrumentRef.current!==instrument||frameRef.current!==frame)return;
   setPayload(p);setDrawings(d);setSelected(null);setReplaying(false);setCursor(1);
 },[instrument,frame,dataRevision]);
 useEffect(()=>{if(authenticated){reload().catch(report);api('/watchlist').then(setWatchlist).catch(report)}},[authenticated,reload,report]);
 useEffect(()=>{if(authenticated&&page==='Audit Log')api('/audit').then(setLogs).catch(report)},[authenticated,page,report]);
 useEffect(()=>{if(!authenticated)return;setAlertsReady(false);Promise.all([api('/research/alert-rules'),api('/research/alert-events')]).then(([rules,events])=>{setAlertRules(rules);seenAlertIds.current=new Set(events.map((e:AlertEvent)=>e.id));setAlertsReady(true)}).catch(report)},[authenticated,alertGeneration,report]);
 const persistRef=useRef<(d:Drawing)=>Promise<void>>(async()=>{});
 persistRef.current=async d=>{const target=instrumentRef.current;try{const saved=await api('/drawings/'+target,{method:'PUT',...json(d)});if(instrumentRef.current!==target)return;setDrawings(old=>[...old.filter(x=>x.id!==saved.id),saved]);setSelected(saved);setNotice('Drawing saved to database')}catch(e){report(e)}};
 useEffect(()=>{
   if(!authenticated||page!=='Charts'||!host.current)return;
   const c=createChart(host.current,{autoSize:true,height:540,layout:{panes:{enableResize:false},background:{type:ColorType.Solid,color:light?'#ffffff':'#0c131d'},textColor:light?'#44536a':'#8291a7',attributionLogo:true},grid:{vertLines:{color:light?'#e6ebf2':'#172130'},horzLines:{color:light?'#e6ebf2':'#172130'}},rightPriceScale:{borderColor:'#263345'},timeScale:{timeVisible:true,secondsVisible:false,borderColor:'#263345'},crosshair:{mode:0}});
   const s=c.addSeries(CandlestickSeries,{upColor:'#36d8ae',downColor:'#ef7084',borderVisible:false,wickUpColor:'#36d8ae',wickDownColor:'#ef7084'});
   chart.current=c;series.current=s;
   c.subscribeCrosshairMove(p=>{const value=p.seriesData.get(s);setHovered(value&&'open' in value?{...value,time:Number(value.time),volume:null,observed_minutes:0} as Bar:null)});
   const changed=()=>setRevision(x=>x+1);c.timeScale().subscribeVisibleLogicalRangeChange(changed);
   c.subscribeClick(p=>{
     const kind=toolRef.current;if(!kind||!p.point||!p.time||(p.paneIndex??0)!==0)return;
     const price=s.coordinateToPrice(p.point.y);if(price===null||typeof p.time!=='number')return;
     const point={time:Number(p.time),price};
     if((kind==='rectangle'||kind==='trendline')&&!firstRef.current){firstRef.current=point;setFirst(point);return}
     const points=(kind==='rectangle'||kind==='trendline')?[firstRef.current!,point]:[point];
     void persistRef.current({id:crypto.randomUUID(),kind,points,text:kind==='note'?'Research note':'',version:0});
     firstRef.current=null;toolRef.current=null;setFirst(null);setTool(null);
   });
   return ()=>{chart.current=null;series.current=null;c.remove()};
 },[authenticated,page,light]);
 const visibleCandles=useMemo(()=>replaying?replayPrefix(payload.candles,cursor):payload.candles,[replaying,payload,cursor]);
 const detections=useMemo(()=>analyze(visibleCandles,2,frame),[payload,replaying,cursor,frame]);
 useEffect(()=>{
  if(!authenticated||!alertsReady||!replaying||page!=='Charts'||!payload.dataset){lastRevealed.current=null;return}
  const key=instrument+':'+frame+':'+payload.dataset.sha256;
  const previous=lastRevealed.current;lastRevealed.current={key,count:cursor};
  if(!previous||previous.key!==key||cursor<=previous.count)return;
  const snapshot=visibleCandles,fromCount=previous.count,context={instrument,timeframe:frame,source:payload.dataset.source,datasetHash:payload.dataset.sha256};
  alertQueue.current=alertQueue.current.then(async()=>{
   for(const event of evaluateAdvance(alertRules,snapshot,fromCount,snapshot.length,context,seenAlertIds.current)){
    await api('/research/alert-events',{method:'PUT',...json(event)});seenAlertIds.current.add(event.id);setLatestAlert(event);
   }
  }).catch(report);
 },[authenticated,alertsReady,replaying,page,payload,cursor,frame,instrument,alertRules,report]);
 useEffect(()=>{if(series.current){series.current.setData(visibleCandles.map(b=>({...b,time:b.time as UTCTimestamp})));chart.current?.timeScale().fitContent();setRevision(x=>x+1)}},[payload,replaying,cursor,authenticated,page,light]);
 useEffect(()=>{
  const s=series.current;if(!s)return;
  const lines=(replaying?[]:drawings).filter(d=>d.kind==='horizontal').map(d=>s.createPriceLine({price:d.points[0].price,color:'#e5b46b',lineWidth:1,lineStyle:LineStyle.Dashed,axisLabelVisible:true,title:d.text||'Manual level'}));
  return ()=>{if(series.current===s)lines.forEach(l=>s.removePriceLine(l))};
 },[drawings,authenticated,page,light,payload,replaying]);
 useEffect(()=>{
  const c=chart.current;if(!c)return;
  const cleanup=installIndicators(c,visibleCandles,payload.dataset?.volume_type||'none',studies);
  setHovered(null);setRevision(n=>n+1);
  return ()=>{if(chart.current===c)cleanup()};
 },[visibleCandles,studies,authenticated,page,light]);
 async function login(e:React.FormEvent){e.preventDefault();setError('');try{await api('/login',{method:'POST',...json({password})});setPassword('');setAuthenticated(true)}catch(e){report(e)}}
 async function upload(e:React.FormEvent<HTMLFormElement>){e.preventDefault();const target=instrument;setBusy(true);setError('');try{const data=new FormData(e.currentTarget);data.set('instrument',instrument);await api('/import',{method:'POST',body:data});if(instrumentRef.current!==target){setNotice('Dataset saved for '+target+'. Your current instrument selection was preserved.');return}setDataRevision(n=>n+1);setNotice('Dataset imported and validated');setPage('Charts')}catch(e){report(e)}finally{setBusy(false)}}
 function exportDrawings(){const url=URL.createObjectURL(new Blob([JSON.stringify(drawings,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=instrument+'-drawings.json';a.click();URL.revokeObjectURL(url)}
 async function remove(){if(!selected)return;const target=instrument;try{await api('/drawings/'+target+'/'+selected.id+'?version='+selected.version,{method:'DELETE'});if(instrumentRef.current!==target)return;setDrawings(old=>old.filter(d=>d.id!==selected.id));setSelected(null);setNotice('Drawing deleted')}catch(e){report(e)}}
 function updatePoint(i:number,key:'time'|'price',value:number){if(!selected)return;setSelected({...selected,points:selected.points.map((p,n)=>n===i?{...p,[key]:value}:p)})}
 if(checking)return <main className={'login '+(light?'light':'')}><p>Opening private workspace…</p></main>;
 if(!authenticated)return <main className={'login '+(light?'light':'')}><form onSubmit={login}><span className="badge">PRIVATE RESEARCH WORKSPACE</span><h1>Trading<br/>Strategy Lab<span className="accent">.</span></h1><p>Observe carefully. Test honestly.<br/>Wait for the strongest evidence.</p><label>Owner password<input type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} required/></label><button className="primary">Unlock terminal →</button>{error&&<p role="alert" className="error">{error}</p>}<small>Historical research & paper trading only</small></form></main>;
 const last=visibleCandles.at(-1),readout=hovered||last;
 const validVolume=volumeAvailable(visibleCandles,payload.dataset?.volume_type||'none');
 const geometry=(replaying?[]:drawings).filter(d=>d.kind!=='horizontal').map(d=>({d,p:d.points.map(p=>({x:chart.current?.timeScale().timeToCoordinate(p.time as Time),y:series.current?.priceToCoordinate(p.price)}))}));
 void revision;
 return <div className={'terminal '+(light?'light':'')}>
  <aside className="rail"><div className="brand">◈</div><b>TSL<span>RESEARCH TERMINAL</span></b><nav>{[...NAV,...(PAGES?['Backup & Restore']:[])].map((name,i)=><button key={name} className={page===name?'active':''} onClick={()=>setPage(name)}><span>{['◈','▥','◫','▤','♧','☆','⇧','⇄','≡','↓'][i]}</span>{name==='Charts'?'Research Charts':name}</button>)}</nav><div className="rail-bottom"><span className="badge">RESEARCH BUILD · V0.10</span><p>Evidence before action.</p><button onClick={toggleTheme}>{light?'Night mode':'Day mode'}</button><button disabled={PAGES} onClick={async()=>{try{await api('/logout',{method:'POST'});setAuthenticated(false)}catch(e){report(e)}}}>{PAGES?'Close tab to leave':'Lock workspace ↗'}</button></div></aside>
  <main><header><div><span className="eyebrow">{PAGES?'BROWSER-LOCAL RESEARCH WORKSPACE':'YOUR PRIVATE MARKET WORKSPACE'}</span><h1>{page==='Charts'?'Research Charts':page}</h1></div><button className="theme-toggle" onClick={toggleTheme}>{light?'☾ Night mode':'☀ Day mode'}</button><div className="header-right"><span className="status"><i/>Research only</span><span>Europe/London</span></div></header>
  {latestAlert&&<div className="banner" role="status">{latestAlert.title} · {latestAlert.payload.state} · {stamp(latestAlert.payload.observedAt)} · Historical replay only <button onClick={()=>{setPage('Research Alerts');setLatestAlert(null)}}>View event history</button><button onClick={()=>setLatestAlert(null)}>Dismiss</button></div>}{PAGES&&<div className="banner">Public app interface · Your imported data and drawings stay in this browser’s IndexedDB. No server login, cloud backup or AI connection. Use Backup & Restore to save your workspace; use Docker for the private server.</div>}{error&&<div role="alert" className="banner error" onClick={()=>setError('')}>{error} · Dismiss</div>}{notice&&<div role="status" className="banner" onClick={()=>setNotice('')}>{notice} · Dismiss</div>}
  {page!=='Market Charts'&&<div className="market-strip"><div><small>RESEARCH INSTRUMENT</small><strong>{instrument.startsWith('XAUUSD')?'XAU / USD':'NASDAQ 100'}</strong></div><div><small>LAST IMPORTED CLOSE</small><strong>{last?.close.toLocaleString('en-GB',{maximumFractionDigits:2})??'—'}</strong></div><div><small>DATA STATUS</small><strong className="amber">{payload.quality.state}</strong></div><div><small>EXECUTION</small><strong>Disabled</strong></div></div>}
  {page==='Market Charts'&&<MarketCharts light={light} onResearch={()=>setPage('Charts')}/>}
  {page==='Charts'&&<div className="chart-layout"><section className="chart-card"><div className="toolbar"><select aria-label="Instrument" value={instrument} onChange={e=>{changeInstrument(e.target.value);setFirst(null);setTool(null)}}><option value="XAUUSD-IMPORT">Gold · XAUUSD · CSV</option><option value="NDX-IMPORT">Nasdaq-100 · cash index · CSV</option>{!PAGES&&<option value="XAUUSD-TD">Gold · Twelve Data historical API</option>}</select><div className="timeframes">{FRAMES.map(f=><button className={f===frame?'chosen':''} key={f} onClick={()=>changeFrame(f)}>{f}</button>)}</div></div>
  <div className="drawing-tools">{(['horizontal','trendline','rectangle','note'] as const).map(t=><button key={t} className={tool===t?'chosen':''} onClick={()=>{setTool(tool===t?null:t);setFirst(null)}}>{t==='rectangle'?'▱ Zone':t==='horizontal'?'― Level':t==='trendline'?'╱ Trendline':'T Note'}</button>)}<button onClick={()=>{setTool(null);setFirst(null)}}>Pointer</button><button onClick={()=>chart.current?.timeScale().fitContent()}>Fit chart</button><button onClick={exportDrawings}>Export JSON</button></div>
  <details className="study-controls"><summary>Indicators · {studies.length} selected</summary><div>{STUDIES.map(name=><label key={name}><input type="checkbox" checked={studies.includes(name)} disabled={(name==='VWAP'||name==='Volume')&&!validVolume} onChange={e=>setStudies(old=>e.target.checked?[...old,name]:old.filter(s=>s!==name))}/>{name}</label>)}</div><p>Observed imported bars only; gaps are not filled. Incomplete aggregation buckets are not execution confirmations. SMA/EMA 20 · Bollinger 20 ± 2 population SD · Wilder RSI/ATR 14 · MACD 12/26/9. VWAP resets at London midnight and needs classified, complete volume; tick VWAP is a tick-weighted proxy. Volume/VWAP unavailable when volume is absent. These studies do not confirm a trade.</p></details>
  <div className="ohlc-readout" aria-label="Candle OHLC">{readout?<><span>{hovered?'Crosshair':'Latest revealed'} · {stamp(readout.time)}</span>{(['open','high','low','close'] as const).map(k=><span key={k}>{k[0].toUpperCase()} <b>{readout[k].toLocaleString('en-GB',{maximumFractionDigits:5})}</b></span>)}</>:<span>No candle available</span>}</div>
  <div className="drawing-tools replay-tools"><button disabled={!payload.candles.length} onClick={()=>{setReplaying(!replaying);setCursor(1)}}>{replaying?'Exit replay':'Start candle replay'}</button>{replaying&&<><button disabled={cursor<=1} onClick={()=>setCursor(n=>Math.max(1,n-1))}>← Previous</button><button disabled={cursor>=payload.candles.length} onClick={()=>setCursor(n=>Math.min(payload.candles.length,n+1))}>Next candle →</button><span>Revealed {cursor} / {payload.candles.length} · Drawings hidden to prevent spoilers</span></>}</div><div className="chart-wrap"><div ref={host}/><svg className="drawing-layer" width="100%" height={chart.current?.panes()[0]?.getHeight()??540} style={{overflow:'hidden'}}>{geometry.map(({d,p})=>{if(p.some(p=>p.x==null||p.y==null))return null;const a=p[0] as {x:number;y:number},b=p[1] as {x:number;y:number}|undefined;return <g key={d.id}>{d.kind==='rectangle'&&b?<rect x={Math.min(a.x,b.x)} y={Math.min(a.y,b.y)} width={Math.abs(a.x-b.x)} height={Math.abs(a.y-b.y)} fill="#e5b46b22" stroke="#e5b46b"/>:d.kind==='trendline'&&b?<line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#e5b46b"/>:<text x={a.x} y={a.y} fill="#e5b46b">{d.text}</text>}</g>})}</svg>{!payload.candles.length&&<div className="empty-chart"><div className="empty-symbol">⌁</div><h2>Your research starts with real data.</h2><p>Import authorized one-minute Gold or Nasdaq candles.<br/>No synthetic prices. No assumed signals.</p><button className="primary" onClick={()=>setPage('Data Sources')}>Import historical CSV →</button></div>}</div>
  <footer>{tool?`${tool}: click ${first?'the second':'a'} chart coordinate`:'Pan · Zoom · Crosshair'}<span>{payload.dataset?`${payload.dataset.source} · ${stamp(last?.time??payload.dataset.end)}`:'No data provider connected'}</span></footer></section>
  <aside className="inspector"><section><span className="eyebrow">RESEARCH GUARDRAILS</span><h2>Wait for evidence<span className="accent">.</span></h2><span className="state">{payload.quality.state}</span><p>{payload.quality.message||'Import a dataset to begin. Import completed one-minute bars to inspect research patterns. Live feeds and demo signals are not connected.'}</p><dl><dt>Chart source</dt><dd>{payload.dataset?.source||'Not configured'}</dd><dt>Imported bars</dt><dd>{payload.dataset?.rows.toLocaleString()||'—'}</dd><dt>Volume</dt><dd>{payload.dataset?.volume_type||'Unavailable'}</dd><dt>Gap intervals</dt><dd>{payload.dataset?.gaps??'—'}</dd></dl></section><section><h3>Completed-bar observations · v1</h3><p>WAIT — pattern formation only. No entry, MSS/CHOCH, defended retest or profitability inferred.</p>{detections.slice(-6).reverse().map((d,i)=><details key={i}><summary>{d.kind} · {d.level}</summary><p>{stamp(d.observed_at)}<br/>{d.explanation}</p></details>)}</section>{!replaying&&<section><div className="section-title"><h3>Saved drawings</h3><span>{drawings.length}</span></div><p>Manual · stored by exact UTC time and price.</p><div className="drawing-list">{drawings.map(d=><button key={d.id} onClick={()=>setSelected({...d,points:d.points.map(p=>({...p}))})}>{d.kind} <small>{d.text||d.id.slice(0,8)} · v{d.version}</small></button>)}</div>{selected&&<div className="drawing-editor"><label>Label<input value={selected.text} onChange={e=>setSelected({...selected,text:e.target.value})}/></label>{selected.points.map((p,i)=><div key={i}><label>UTC epoch seconds · point {i+1}<input type="number" value={p.time} onChange={e=>updatePoint(i,'time',+e.target.value)}/></label><label>Price<input type="number" step="any" value={p.price} onChange={e=>updatePoint(i,'price',+e.target.value)}/></label></div>)}<button onClick={()=>persistRef.current({id:selected.id,kind:selected.kind,points:selected.points,text:selected.text,version:selected.version})}>Save changes</button><button onClick={remove}>Delete</button></div>}</section>}</aside></div>}
  {(page==='Backtesting'||page==='Trading Journal')&&<Backtesting key={page} api={api} journal={page==='Trading Journal'}/>}
  {page==='Research Alerts'&&<Alerts api={api} onChanged={()=>setAlertGeneration(n=>n+1)}/>}
  {page==='Data Connection'&&<DataConnection api={api} pages={PAGES} onImported={()=>{changeInstrument('XAUUSD-TD');setDataRevision(n=>n+1);setPage('Charts');setNotice('Authorized provider candles imported. Historical research only.')}}/>}
  {page==='Backup & Restore'&&<WorkspaceBackup api={api} beforeRestore={()=>alertQueue.current}/>}
  {page==='Data Sources'&&<section className="panel"><span className="eyebrow">AUTHORIZED DATA ONLY</span><h2>Import historical candles</h2><p>One-minute bars only. Required CSV headers: <code>time,open,high,low,close</code>. Optional: <code>volume</code>.<br/>ISO 8601 timestamps must include UTC or an explicit offset. Only completed one-minute bars should be imported. Imports replace the selected instrument dataset atomically.</p><form onSubmit={upload}><label>Exact instrument<select value={instrument} disabled={busy} onChange={e=>changeInstrument(e.target.value)}><option value="XAUUSD-IMPORT">XAUUSD · Gold OTC source</option><option value="NDX-IMPORT">NDX · Nasdaq-100 cash index (not NQ or CFD)</option></select></label><label>Provider / source description<input name="source" required maxLength={160} placeholder="Provider, venue and original file reference"/></label><label>Volume classification<select name="volume_type"><option value="none">No volume</option><option value="tick">Tick volume</option><option value="exchange">Exchange volume</option></select></label><label>CSV file<input name="file" type="file" accept=".csv,text/csv" required/></label><label className="checkbox"><input name="rights_confirmed" type="checkbox" value="true" required/>I am authorized to use these data for this private research.</label><button className="primary" disabled={busy}>{busy?'Validating…':'Validate & import CSV'}</button></form><p>Maximum 12 MB / 100,000 rows per import. No data is bundled. No paid providers or brokerage accounts are connected.</p></section>}
  {page==='Watchlist'&&<section className="panel"><h2>Your research watchlist</h2>{(PAGES?['XAUUSD-IMPORT','NDX-IMPORT']:['XAUUSD-IMPORT','NDX-IMPORT','XAUUSD-TD']).map(i=><label className="checkbox" key={i}><input type="checkbox" checked={watchlist.includes(i)} onChange={async e=>{const next=e.target.checked?[...watchlist,i]:watchlist.filter(x=>x!==i);try{await api('/watchlist',{method:'PUT',...json({instruments:next})});setWatchlist(next)}catch(e){report(e)}}}/>{i}</label>)}<p>Futures and additional instruments will be enabled when their metadata and provider mappings are verified.</p></section>}
  {page==='Audit Log'&&<section className="panel"><h2>Workspace audit trail</h2><p>Imports, drawing changes, watchlist changes and logins are recorded. Secrets are excluded.</p>{logs.map(l=><details key={l.id}><summary>{stamp(l.time)} · {l.action}</summary><pre>{JSON.stringify(l.detail,null,2)}</pre></details>)}</section>}
  <div className="bottom-note"><span>◈ TRADING STRATEGY LAB</span><p>Provider displays + imported research · No order execution · AI not connected</p><a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">Charts by TradingView Lightweight Charts™</a></div>
 </main></div>
}
