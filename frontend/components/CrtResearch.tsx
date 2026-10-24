'use client';

import {useEffect,useState} from 'react';
import {appendArchiveListing,fetchArchiveListingPage,type ArchiveListing} from '../lib/archive-discovery';
import {screenCrtHypotheses,completeAggregateWindow,type ScreenResult,type Gate} from '../lib/crt-quant-filters';
import type {Bar} from '../lib/research';
import {auditCrtCrossTimeframe,certifiedCrtFourHourBars} from '../lib/crt-timeframe-audit';

type API=(path:string,init?:RequestInit)=>Promise<any>;
type HistoryPage={
 dataset:{id:string;archive_sha256:string;instrument:string;provider:string};
 quality:{live:boolean;price_side:string};
 candles:Bar[];has_more:boolean;
};
const textGate=(s:Gate)=>s==='PASS'?'Pass':s==='FAIL'?'Reject':'No verified evidence';
const date=(s:number)=>new Date(s*1000).toISOString().replace('T',' ').slice(0,16)+' UTC';
export default function CrtResearch({api,pages}:{api:API;pages:boolean}){
 const [archives,setArchives]=useState<ArchiveListing[]>([]);
 const [selected,setSelected]=useState('');
 const [status,setStatus]=useState('');
 const [busy,setBusy]=useState(false);
 const [discoveryBusy,setDiscoveryBusy]=useState(false);
 const [result,setResult]=useState<ScreenResult|null>(null);
 const [coverage,setCoverage]=useState('');
 const [depth,setDepth]=useState('0.40'),[displacement,setDisplacement]=useState('1.5');
 useEffect(()=>{
  if(pages)return;
  let active=true;setDiscoveryBusy(true);
  (async()=>{
   let page=await fetchArchiveListingPage(fetch,0),items=page.items;
   while(page.hasMore&&items.length<1000){
    page=await fetchArchiveListingPage(fetch,page.nextOffset!,undefined,page.snapshot!);
    items=appendArchiveListing(items,page);
   }
   if(!active)return;
   setArchives(items);
   setSelected(old=>items.some(i=>i.id===old)?old:items[0]?.id||'');
   if(page.hasMore||page.legacyPossiblyTruncated)setStatus('Archive listing is incomplete; older or additional files may not be shown.');
  })().catch(e=>{if(active)setStatus(e instanceof Error?e.message:String(e))})
   .finally(()=>{if(active)setDiscoveryBusy(false)});
  return ()=>{active=false};
 },[pages]);
 async function run(){
  setBusy(true);setStatus('');setResult(null);
  try{
   const archive=archives.find(a=>a.id===selected);
   if(!archive)throw Error('Select one READY source archive');
   const max=Number(depth),mult=Number(displacement);
   if(!Number.isFinite(max)||max<=0||max>1||!Number.isFinite(mult)||mult<1||mult>10)
    throw Error('Use a sweep threshold between 0 and 1 and a positive displacement multiple between 1 and 10');
   const frames=['4H','15m','1D'] as const;
   const pages=await Promise.all(frames.map(async frame=>{
    const q=new URLSearchParams({timeframe:frame,limit:'2000'});
    const p=await api('/history/'+encodeURIComponent(selected)+'/candles?'+q) as HistoryPage;
    if(!p.dataset||p.dataset.id!==selected||
      p.dataset.provider!==archive.provider||
      p.dataset.instrument!==archive.instrument||
      !/^[a-f0-9]{64}$/.test(p.dataset.archive_sha256)||
      (archive.archive_sha256&&p.dataset.archive_sha256!==archive.archive_sha256)||
      p.quality?.live!==false||p.quality?.price_side!=='bid'||!Array.isArray(p.candles))
     throw Error('Archive, price side, or source identity changed between timeframe requests');
    return p;
   }));
   const hashes=new Set(pages.map(p=>p.dataset.archive_sha256));
   if(hashes.size!==1)throw Error('Timeframes belong to different archive versions; refusing to mix');
   const fifteenWindow=completeAggregateWindow(pages[1].candles,900);
   const fourHourWindow=completeAggregateWindow(pages[0].candles,14400);
   const fifteen=fifteenWindow.bars;
   if(fifteen.length<40)throw Error('At least 40 observed 15-minute bars are needed to review CRT confirmation');
   // Ignore sweep references outside the available 15m time window.
   const cutoff=fifteen[0].time-2*14400;
   const h4=fourHourWindow.bars.filter(b=>b.time>=cutoff);
   const audit=auditCrtCrossTimeframe(h4,fifteen);
   if(audit.checkedFourHourBars===0)
    throw Error('No fully overlapping 4H/15m candles to verify. Load a longer source-isolated 15m history window.');
   // A matching archive SHA does not certify each timeframe bucket. Only
   // compare two adjacent 4H bars if BOTH were independently reconciled to
   // all sixteen source-matched, completed 15m candles. An uncheckable edge
   // may otherwise create a false CRT sweep against a verified bar.
   const certifiedH4=certifiedCrtFourHourBars(h4,audit);
   const report=screenCrtHypotheses({
    source:{datasetId:selected,archiveSha256:pages[0].dataset.archive_sha256,
     instrument:archive.instrument,provider:archive.provider,priceSide:'bid',
     volumeType:'unverified',volumeVerified:false},
    fourHour:certifiedH4,fifteenMinute:fifteen,daily:pages[2].candles,
    sweepMaxFraction:max,displacementMultiple:mult,
   });
   setResult(report);
   setCoverage('Loaded '+h4.length+' 4H, '+fifteen.length+' 15m, and '+pages[2].candles.length+
    ' 1D aggregate bars from one archive. Excluded '+
    (fourHourWindow.excludedBoundaryBars+fifteenWindow.excludedBoundaryBars)+
    ' incomplete 4H/15m boundary buckets (not synthesized). Cross-checked '+
    audit.checkedFourHourBars+' 4H bars against their 16 observed 15m bars; '+
    audit.uncheckableFourHourBars+' outside the shared window (excluded from CRT candidates, not certified). '+(pages.some(p=>p.has_more)?
    'At least one timeframe is a capped recent window.':'No older pages reported for these requests.'));
  }catch(e){setStatus(e instanceof Error?e.message:String(e))}
  finally{setBusy(false)}
 }
 if(pages)return <section className="panel"><h2>CRT &amp; ICT Quantitative Research</h2>
  <p>Requires the authenticated private server and one source-isolated imported historical archive. Browser-only mode cannot access or verify those files.</p></section>;
 const rows=result?.candidates.slice(-80).reverse()??[];
 return <section className="panel research-panel">
  <span className="eyebrow">MULTI-TIMEFRAME RESEARCH · NEVER LIVE TRADING</span>
  <h2>4H CRT / 15-Minute Confirmation Screen</h2>
  <p>Test proposed mathematical filters against actual completed historical candles from one source. Nothing is assumed profitable. The screen identifies rejected, confirmed and <strong>unverifiable</strong> conditions separately.</p>
  <div className="backtest-settings">
   <label>Verified archive identity<select value={selected} disabled={busy} onChange={e=>{setSelected(e.target.value);setResult(null)}}>
    {!archives.length&&<option value="">No completed historical archives</option>}
    {archives.map(a=><option key={a.id} value={a.id}>{a.instrument} · {a.provider} · {a.id.slice(0,9)}</option>)}
   </select></label>
   <label>Maximum 4H manipulation wick / reference range<input type="number" step="0.05" min="0.05" max="1"
    value={depth} onChange={e=>{setDepth(e.target.value);setResult(null)}}/></label>
   <label>15m shift candle range / previous 20-bar median<input type="number" step="0.1" min="1" max="10"
    value={displacement} onChange={e=>{setDisplacement(e.target.value);setResult(null)}}/></label>
  </div>
  <button className="primary" disabled={busy||discoveryBusy||!selected} onClick={()=>void run()}>
   {busy?'Comparing completed multi-timeframe candles…':'Run 4H CRT research screen'}
  </button>
  <p>Method: adjacent fully observed UTC 4H candles; manipulation closes back within Candle 1; proposed 40% maximum sweep depth. Only after Candle 2 closes, find the first 15m directional swing break in the next 4H block and compare its range with the preceding 20 complete 15m bars. Daily trend uses only earlier UTC daily candles with all 1,440 source minutes observed; partial or shortened days are excluded without a verified session calendar.</p>
  <p>Volume and 4H order-block evidence are **not automatically trusted** from HistData BID-only archives. A high-impact news/calendar gate cannot pass without authorized, timestamped economic events. No research candidate can authorize execution.</p>
  {status&&<p role="alert" className="error">{status}</p>}
  {result&&<>
   <h3>Loaded-window results</h3><p>{coverage}<br/>
    Historical 4H adjacent pairs reviewed: {result.analyzedSweepPairs}. Unambiguous range sweeps: {result.candidates.length}. Showing the most recent {rows.length}.</p>
   {!rows.length&&<p>No observed unambiguous 4H range sweep/reclaim met the pattern definition in the loaded window; this does not mean no trades ever existed.</p>}
   <div className="table-wrap"><table><thead><tr><th>Sweep closed (UTC)</th><th>Side</th><th>Outside wick</th><th>Depth</th><th>15m structure</th><th>Displacement</th><th>Daily trend proxy</th><th>Volume</th><th>4H zone</th><th>News</th></tr></thead><tbody>
    {rows.map((r,i)=><tr key={r.sweepCloseAt+'-'+i}><td>{date(r.sweepCloseAt)}</td>
     <td>{r.direction}</td><td>{(r.sweepDepthFraction*100).toFixed(1)}%</td>
     <td>{textGate(r.gates.sweepDepth)}</td><td>{textGate(r.gates.structureShift)}</td>
     <td>{textGate(r.gates.displacement)}</td><td>{textGate(r.gates.dailyTrend)}</td>
     <td>{textGate(r.gates.volume)}</td><td>{textGate(r.gates.matchingZone)}</td>
     <td>{textGate(r.gates.newsCalendar)}</td></tr>)}
   </tbody></table></div>
   <p>{result.warning}</p>
   <details><summary>Why some gates remain unavailable</summary>
    <p>No exchange-certified two-sided quotes, formally validated order blocks, source-certified volume, exact CFD trading sessions or revision-aware news calendars have been supplied. Historical pattern counts are not fills or a profitability backtest.</p>
   </details>
  </>}
 </section>;
}
