/** Authenticated, bounded scanner for BID-only NY regular-session M1 history.
 * Reads at most 100,000 source bars, retaining <=20,000 complete RTH minutes.
 * Scanning raw 24h CFD archives for 20 prior NY sessions needs more than
 * 20,000 raw bars; skipping outside-session quotes is not fabricating prices.
 */
import type {Bar} from './research.ts';
import type {ArchivePage,ArchiveIdentity} from './backtest-history.ts';
import {isNyRegularSessionMinute} from './ny-close-momentum.ts';

export type NyWindow={bars:Bar[];dataset:ArchiveIdentity;
 pages:number;rawBarsScanned:number;capped:boolean};
export async function loadNyCloseWindow(
 id:string,fetchPage:(before:number|null,limit:number)=>Promise<ArchivePage>,
 maxRaw=100000,maxRetained=20000,pageSize=2000
):Promise<NyWindow>{
 if(!/^[a-f0-9]{64}$/.test(id)||
    !Number.isInteger(maxRaw)||maxRaw<1||maxRaw>100000||
    !Number.isInteger(maxRetained)||maxRetained<1||maxRetained>20000||
    !Number.isInteger(pageSize)||pageSize<1||pageSize>2000)
  throw Error('Invalid source identity or read-only NY research limits');
 let cursor:number|null=null,dataset:ArchiveIdentity|null=null,
  stored:Bar[]=[],scanned=0,pages=0;
 while(scanned<maxRaw&&stored.length<maxRetained){
  const limit=Math.min(pageSize,maxRaw-scanned);
  const p=await fetchPage(cursor,limit);
  if(!p||!p.dataset||p.dataset.id!==id||
    !/^[a-f0-9]{64}$/.test(p.dataset.archive_sha256)||
    !p.dataset.provider||!p.dataset.instrument||
    (dataset&&(dataset.archive_sha256!==p.dataset.archive_sha256||
      dataset.provider!==p.dataset.provider||
      dataset.instrument!==p.dataset.instrument))||
    p.quality?.live!==false||p.quality?.price_side!=='bid'||
    !Array.isArray(p.candles)||p.candles.length>limit||
    typeof p.has_more!=='boolean')
   throw Error('Source changed or malformed historical BID-only archive page');
  if(!p.candles.length){
   if(p.has_more)throw Error('Historical archive made no progress');
   if(!dataset)throw Error('Selected historical source contains no minute candles');
   return {bars:stored,dataset,pages:pages+1,rawBarsScanned:scanned,capped:false};
  }
  let prior=-Infinity;
  for(const b of p.candles){
   if(!Number.isSafeInteger(b.time)||b.time<0||b.time%60!==0||
     b.time<=prior||(cursor!==null&&b.time>=cursor)||
     b.observed_minutes!==1||
     ![b.open,b.high,b.low,b.close].every(n=>Number.isFinite(n)&&n>0)||
     b.high<Math.max(b.open,b.close)||b.low>Math.min(b.open,b.close))
    throw Error('Overlapping, unordered or malformed historical minute data');
   prior=b.time;
  }
  if(stored.length&&p.candles.at(-1)!.time>=stored[0].time)
   throw Error('Historical archive pages overlapped');
  if(p.has_more&&p.next_before!==p.candles[0].time)
   throw Error('Historical archive cursor mismatch');
  if(!p.has_more&&p.next_before!==null)
   throw Error('Unexpected end-of-archive cursor');
  dataset=p.dataset;
  const regular=p.candles.filter(b=>isNyRegularSessionMinute(b.time));
  stored=[...regular,...stored].slice(-maxRetained);
  pages++;scanned+=p.candles.length;
  if(!p.has_more)return {bars:stored,dataset,pages,rawBarsScanned:scanned,capped:false};
  cursor=p.next_before;
 }
 return {bars:stored,dataset:dataset!,pages,rawBarsScanned:scanned,capped:true};
}
