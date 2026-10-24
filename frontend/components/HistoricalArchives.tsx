'use client';

import {useCallback,useEffect,useRef,useState} from 'react';
import {createChart,CandlestickSeries,ColorType,type IChartApi,type ISeriesApi,type UTCTimestamp} from 'lightweight-charts';

type Archive={id:string;provider:string;instrument:string;format:string;state:string;accepted:number;rejected:number;zero_volume:number};
type Candle={time:number;open:number;high:number;low:number;close:number;volume:number|null;observed_minutes:number};
type Page={candles:Candle[];has_more:boolean;next_before:number|null;quality:{state:string;message:string}};
const FRAMES=['1m','3m','5m','15m','30m','1H','2H','4H','1D','1W','1M'];

/** Browse verified completed source-isolated ZIP datasets without changing legacy charts. */
export default function HistoricalArchives({light,pages}:{light:boolean;pages:boolean}){
 const [datasets,setDatasets]=useState<Archive[]>([]);
 const [selected,setSelected]=useState('');
 const [frame,setFrame]=useState('1H');
 const [bars,setBars]=useState<Candle[]>([]);
 const [nextBefore,setNextBefore]=useState<number|null>(null);
 const [loading,setLoading]=useState(false);
 const [error,setError]=useState('');
 const [quality,setQuality]=useState('');
 const chartHost=useRef<HTMLDivElement>(null);
 const chartRef=useRef<IChartApi|null>(null);
 const candleSeries=useRef<ISeriesApi<'Candlestick'>|null>(null);
 const generation=useRef(0);
 const archive=datasets.find(x=>x.id===selected);

 useEffect(()=>{
  if(pages)return;
  const controller=new AbortController();
  fetch('/api/history/datasets',{credentials:'same-origin',signal:controller.signal})
   .then(async r=>{if(!r.ok)throw Error('Historical storage unavailable ('+r.status+'). Install the archive schema before browsing.');return r.json()})
   .then((data:Archive[])=>{setDatasets(data);setSelected(old=>old||data[0]?.id||'')})
   .catch(e=>{if(!controller.signal.aborted)setError(String(e))});
  return ()=>controller.abort();
 },[pages]);

 const fetchPage=useCallback(async(cursor:number|null,replace:boolean,requestId:number)=>{
  if(!selected)return;
  setLoading(true);
  try{
   const q=new URLSearchParams({timeframe:frame,limit:'2000'});
   if(cursor!==null)q.set('before',String(cursor));
   const response=await fetch('/api/history/'+encodeURIComponent(selected)+'/candles?'+q.toString(),{credentials:'same-origin'});
   if(!response.ok)throw Error('Historical candles request failed ('+response.status+')');
   const data:Page=await response.json();
   if(requestId!==generation.current)return;
   setBars(current=>replace?data.candles:[...data.candles,...current]);
   setNextBefore(data.next_before);
   setQuality(data.quality?.message||'Observed bid OHLC only');
   setError('');
  }catch(e){
   if(requestId===generation.current)setError(String(e));
  }finally{
   if(requestId===generation.current)setLoading(false);
  }
 },[selected,frame]);

 useEffect(()=>{
  generation.current++;
  setBars([]);
  setNextBefore(null);
  setError('');
  if(selected&&!pages)void fetchPage(null,true,generation.current);
 },[selected,frame,pages,fetchPage]);

 useEffect(()=>{
  if(!chartHost.current||pages)return;
  const chart=createChart(chartHost.current,{
   height:480,autoSize:true,
   layout:{background:{type:ColorType.Solid,color:light?'#ffffff':'#0c131d'},
           textColor:light?'#344256':'#a7b4c7'},
   grid:{vertLines:{color:light?'#edf0f5':'#1f2b3a'},
         horzLines:{color:light?'#edf0f5':'#1f2b3a'}},
   timeScale:{timeVisible:true,secondsVisible:false},
  });
  const series=chart.addSeries(CandlestickSeries,{
   upColor:'#27b597',downColor:'#e05f75',borderVisible:false,
   wickUpColor:'#27b597',wickDownColor:'#e05f75',
  });
  chartRef.current=chart;candleSeries.current=series;
  return ()=>{chartRef.current=null;candleSeries.current=null;chart.remove()};
 },[light,pages]);

 useEffect(()=>{
  const series=candleSeries.current;
  if(!series)return;
  series.setData(bars.map(({time,open,high,low,close})=>({
   time:time as UTCTimestamp,open,high,low,close
  })));
  chartRef.current?.timeScale().fitContent();
 },[bars,light]);

 if(pages)return <section className="chart-card" style={{padding:22}}>
  <h2>Historical Archives</h2>
  <p>This feature requires the authenticated private server. GitHub Pages stores its data in your browser instead.</p>
 </section>;

 return <section className="chart-card" style={{padding:22}}>
  <div className="toolbar" style={{display:'flex',gap:12,flexWrap:'wrap'}}>
   <label>Imported dataset
    <select value={selected} onChange={e=>setSelected(e.target.value)} aria-label="Historical dataset">
     {!datasets.length&&<option value="">No completed archive datasets</option>}
     {datasets.map(d=><option key={d.id} value={d.id}>{d.instrument} · {d.provider} · {d.format.toUpperCase()} · {d.id.slice(0,8)}</option>)}
    </select>
   </label>
   <label>Timeframe
    <select value={frame} onChange={e=>setFrame(e.target.value)} aria-label="Historical timeframe">
     {FRAMES.map(f=><option key={f} value={f}>{f}</option>)}
    </select>
   </label>
  </div>
  {archive&&<p style={{opacity:0.8}}>
   Source-isolated dataset · {archive.accepted.toLocaleString()} accepted M1 candles · {archive.rejected.toLocaleString()} excluded rows
   {archive.zero_volume>0?' · zero-volume entries retained':''}
  </p>}
  {error&&<p role="alert" className="error">{error}</p>}
  <div ref={chartHost} style={{minHeight:480,width:'100%'}} role="img" aria-label="Read-only historical candlestick chart"/>
  <p>{quality||'Historical research only. Imported bid bars are not a live executable quote feed.'}</p>
  <div style={{display:'flex',alignItems:'center',gap:12,flexWrap:'wrap'}}>
   <button type="button" disabled={loading||nextBefore===null}
    onClick={()=>{if(nextBefore!==null)void fetchPage(nextBefore,false,generation.current)}}>
    {loading?'Loading…':nextBefore===null?'No older page':'Load older candles'}
   </button>
   <span>{bars.length.toLocaleString()} displayed bars · {nextBefore!==null?'Older data available':'End of this archive'}</span>
  </div>
  <p style={{opacity:0.75}}>
   Each source archive is deliberately isolated. Overlapping provider feeds, futures contracts and other ZIP files are not silently merged.
  </p>
 </section>;
}
