/** Strict, read-only paging for source-isolated historical strategy research.
 * Never concatenate different archive identities or pretend the limited window
 * represents a complete multi-year backtest.
 */
import type {Bar} from './research.ts';

export type ArchiveIdentity={id:string;provider:string;instrument:string;archive_sha256:string};
export type ArchivePage={dataset:ArchiveIdentity;candles:Bar[];has_more:boolean;next_before:number|null;quality:{live:boolean;price_side:string}};
export type ArchiveWindow={bars:Bar[];dataset:ArchiveIdentity;capped:boolean;pages:number};
const FRAMES=new Set(['1m','5m','15m','1H']);

function validatePage(page:ArchivePage,id:string,previous:ArchiveIdentity|null,before:number|null,limit:number){
 if(!page||!page.dataset||page.dataset.id!==id||!page.dataset.archive_sha256||
    (previous&&(page.dataset.archive_sha256!==previous.archive_sha256||
      page.dataset.provider!==previous.provider||page.dataset.instrument!==previous.instrument)))
  throw Error('Archive identity changed during paging; refusing to mix historical datasets');
 if(page.quality?.live!==false||page.quality?.price_side!=='bid')
  throw Error('Expected historical bid-only candles, not live or executable prices');
 if(!Array.isArray(page.candles)||page.candles.length>limit||typeof page.has_more!=='boolean')
  throw Error('Malformed historical archive page');
 let last=-Infinity;
 for(const b of page.candles){
  if(!Number.isSafeInteger(b.time)||b.time<=last||(before!==null&&b.time>=before)||
     ![b.open,b.high,b.low,b.close,b.observed_minutes].every(Number.isFinite)||
     b.high<Math.max(b.open,b.close)||b.low>Math.min(b.open,b.close)||
     b.observed_minutes<1||!Number.isInteger(b.observed_minutes))
   throw Error('Overlapping, unordered or malformed historical archive candles');
  last=b.time;
 }
 if(page.has_more&&(page.candles.length===0||page.next_before!==page.candles[0].time))
  throw Error('Invalid historical pagination cursor');
 if(!page.has_more&&page.next_before!==null)
  throw Error('Unexpected historical pagination cursor');
}

/** Up to 20k aggregate bars; API pages never exceed 2k. Output oldest first. */
export async function loadArchiveWindow(
 id:string,frame:string,fetchPage:(before:number|null,limit:number)=>Promise<ArchivePage>,
 maxBars=20000,pageSize=2000
):Promise<ArchiveWindow>{
 if(!/^[a-f0-9]{64}$/.test(id)||!FRAMES.has(frame))
  throw Error('Unsupported archive identity or simulation timeframe');
 if(!Number.isInteger(maxBars)||maxBars<1||maxBars>20000||
    !Number.isInteger(pageSize)||pageSize<1||pageSize>2000)
  throw Error('Archive history limits must be positive and at most 20,000/2,000 candles');
 let bars:Bar[]=[],before:number|null=null,dataset:ArchiveIdentity|null=null,pages=0;
 while(bars.length<maxBars){
  const limit=Math.min(pageSize,maxBars-bars.length);
  const page=await fetchPage(before,limit);
  validatePage(page,id,dataset,before,limit);
  if(!page.candles.length){
   if(!bars.length)throw Error('Archive contains no candles at this timeframe');
   return {bars,dataset:dataset!,capped:false,pages:pages+1};
  }
  if(bars.length&&page.candles.at(-1)!.time>=bars[0].time)
   throw Error('Archive pages overlap; refusing duplicate or mixed candles');
  dataset=page.dataset;
  bars=[...page.candles,...bars];
  pages++;
  if(!page.has_more)return {bars,dataset,capped:false,pages};
  before=page.next_before;
 }
 return {bars,dataset:dataset!,capped:true,pages};
}
