'use client';

import {useEffect,useState} from 'react';
import {appendArchiveListing,fetchArchiveListingPage,type ArchiveListing} from '../lib/archive-discovery';
import type {ArchivePage} from '../lib/backtest-history';
import {loadNyCloseWindow} from '../lib/ny-close-history';
import {studyNyCloseMomentum,type CloseMomentumStudy} from '../lib/ny-close-momentum';

type API=(path:string,init?:RequestInit)=>Promise<any>;
const fmt=(n:number|null,decimals=2)=>n===null?'—':n.toLocaleString('en-GB',{maximumFractionDigits:decimals});
export default function NyCloseResearch({api,pages}:{api:API;pages:boolean}){
 const [archives,setArchives]=useState<ArchiveListing[]>([]);
 const [selected,setSelected]=useState('');
 const [costBps,setCostBps]=useState('1.8');
 const [loading,setLoading]=useState(false);
 const [listingBusy,setListingBusy]=useState(false);
 const [listingError,setListingError]=useState('');
 const [error,setError]=useState('');
 const [result,setResult]=useState<CloseMomentumStudy|null>(null);
 const [capped,setCapped]=useState(false);
 useEffect(()=>{
  if(pages)return;
  let active=true;
  setListingBusy(true);
  (async()=>{
   let page=await fetchArchiveListingPage(fetch,0);
   let list=page.items;
   while(page.hasMore&&list.length<1000){
    page=await fetchArchiveListingPage(fetch,page.nextOffset!,undefined,page.snapshot!);
    list=appendArchiveListing(list,page);
   }
   if(!active)return;
   setArchives(list);setSelected(old=>list.some(a=>a.id===old)?old:list[0]?.id||'');
   setListingError(list.length>=1000&&page.hasMore?
    'Archive list capped at 1,000 entries. Refine archive inventory before relying on discovery.':
    page.legacyPossiblyTruncated?'Legacy server only exposes first 200 source files.':'');
  })().catch(e=>{if(active)setListingError(e instanceof Error?e.message:String(e))})
   .finally(()=>{if(active)setListingBusy(false)});
  return ()=>{active=false};
 },[pages]);
 async function run(){
  setError('');setResult(null);setLoading(true);
  try{
   const archive=archives.find(x=>x.id===selected);
   if(!archive)throw Error('Select one ready completed ZIP archive first');
   const cost=Number(costBps);
   if(!Number.isFinite(cost)||cost<=0||cost>1000)throw Error('Specify a positive illustrative round-trip CFD cost in basis points (at most 1,000)');
   const window=await loadNyCloseWindow(selected,async(before,limit)=>{
    const q=new URLSearchParams({timeframe:'1m',limit:String(limit)});
    if(before!==null)q.set('before',String(before));
    return await api('/history/'+encodeURIComponent(selected)+'/candles?'+q) as ArchivePage;
   });
   if(archive.provider!==window.dataset.provider||
      archive.instrument!==window.dataset.instrument||
      (archive.archive_sha256&&archive.archive_sha256!==window.dataset.archive_sha256))
    throw Error('Source identity differs between archive inventory and candles');
   setCapped(window.capped);
   setResult(studyNyCloseMomentum(window.bars,{
    instrument:window.dataset.instrument,provider:window.dataset.provider,
    archiveId:window.dataset.id,archiveSha256:window.dataset.archive_sha256,
    priceSide:'bid',assumedRoundTripBps:cost,
   }));
  }catch(e){setError(e instanceof Error?e.message:String(e))}
  finally{setLoading(false)}
 }
 if(pages)return <section className="panel research-panel"><h2>NY Close Momentum Research</h2>
  <p>Requires the authenticated server's source-isolated historical ZIP archives. The browser-local Pages mode cannot safely claim access to private historical files.</p></section>;
 return <section className="panel research-panel">
  <span className="eyebrow">INTRADAY MOMENTUM HYPOTHESIS · NO LIVE EXECUTION</span>
  <h2>New York Close Momentum Research</h2>
  <p>Independent historical study inspired by the SPY/ETF intraday momentum literature. Uses completed <strong>one-minute BID-only measurements</strong> to examine a <strong>15:30–16:00 New York time holding window</strong>; it does not scalp one-minute signals or assume the findings transfer to CFDs.</p>
  <div className="backtest-settings">
   <label>Exact imported historical source
    <select value={selected} onChange={e=>{setSelected(e.target.value);setResult(null)}}>
     {!archives.length&&<option value="">No completed archives</option>}
     {archives.map(a=><option value={a.id} key={a.id}>{a.instrument} · {a.provider} · {a.format} · {a.id.slice(0,10)}</option>)}
    </select>
   </label>
   <label>Assumed total round-trip friction (bps)
    <input type="number" min="0.01" max="1000" step="any" value={costBps}
     onChange={e=>{setCostBps(e.target.value);setResult(null)}}/>
   </label>
  </div>
  <p>Data read: bounded scan of up to 100,000 raw one-minute source bars, retaining at most 20,000 NY regular-session minute bars. No market data is written back to the archive.</p>
  <p>Eligibility: complete US equity 09:30–16:00 ET historical session, first-half-hour direction agrees with price change from the previous session close to 15:30, and the first-half-hour high/low range exceeds the median of the previous 20 complete sessions. All signals are determined at 15:30 ET. This is an experimental session proxy, not a verified strategy for XAUUSD, NSXUSD or WTI.</p>
  <button className="primary" disabled={loading||listingBusy||!selected} onClick={()=>void run()}>{loading?'Researching complete NY sessions…':listingBusy?'Discovering imported archives…':'Run historical NY close experiment'}</button>
  {listingError&&<p role="alert" className="error">{listingError}</p>}
  {error&&<p role="alert" className="error">{error}</p>}
  {result&&<>
   <p><strong>Source: </strong>{result.source.instrument} · {result.source.provider} · archive {result.source.archiveId.slice(0,12)} · BID only<br/>
    Complete NY sessions: {result.completeSessions} / {result.totalObservedSessions}<br/>
    Agreement candidates: {result.candidateDays} · High-volatility eligible sessions: {result.volatilityGatedDays}</p>
   {capped&&<p role="alert" className="banner">WINDOW LIMIT: Scanned up to 100,000 recent raw minute bars, retaining up to 20,000 NY regular-session bars. This is not a full multi-year archive evaluation.</p>}
   <h3>Illustrative net results by cost assumption</h3>
   <div className="table-wrap"><table><thead><tr><th>Round-trip cost</th><th>Volatility-gated trades</th><th>Gated mean net bps</th><th>Gated win %</th><th>Gated profit factor</th><th>Without volatility gate: mean net bps</th></tr></thead><tbody>
    {result.costs.map((s,i)=><tr key={i}><td>{fmt(s.roundTripBps)} bps</td>
     <td>{s.trades}</td><td>{fmt(s.averageNetBps)}</td><td>{fmt(s.winRatePct)}</td>
     <td>{fmt(s.profitFactor)}</td><td>{fmt(result.ungatedCosts[i].averageNetBps)}</td></tr>)}
   </tbody></table></div>
   <h3>Data exclusions and limitations</h3>
   <p>{Object.entries(result.rejected).map(([key,value])=>key+': '+value).join(' · ')||'No recorded exclusions'}</p>
   <ul>{result.warnings.map((w,i)=><li key={i}>{w}</li>)}</ul>
   <p>Zero trades, a good mean return, or a high gross profit factor do not establish reliability. The results still require independently held-out evaluation, broker-specific two-sided quotes and risk analysis before any paper-trading decisions.</p>
  </>}
 </section>;
}
