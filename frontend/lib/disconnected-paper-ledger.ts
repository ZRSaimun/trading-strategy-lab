/**
 * Disconnected paper-marking journal. Every price is CALLER-SUPPLIED and
 * UNAUTHENTICATED; replay never submits orders, requests quotes or persists data.
 * Single position, no leverage, cash-denominated P&L, conservative bid/ask.
 * Numerical estimates are NOT an accounting or broker reconciliation ledger.
 */
export type PaperSource={instrument:string;provider:string;venue:string;sourceId:string;currency:string};
type Base={seq:number;at:number};
export type PaperQuote=Base&{kind:'QUOTE';source:PaperSource;bid:number;ask:number};
export type PaperOpen=Base&{kind:'OPEN';id:string;side:'LONG'|'SHORT';quantity:number;fee:number;slippageBps:number;quoteSeq:number};
export type PaperClose=Base&{kind:'CLOSE';id:string;fee:number;slippageBps:number;quoteSeq:number};
export type PaperEvent=PaperQuote|PaperOpen|PaperClose;
export type PaperPolicy={startingCash:number;maxNotional:number;maxQuoteAgeSeconds:number;markSlippageBps:number};
export type PaperPosition={id:string;side:'LONG'|'SHORT';quantity:number;entryPrice:number;entryFee:number;entryAt:number;entryQuoteSeq:number};
export type PaperClosedTrade={id:string;side:'LONG'|'SHORT';quantity:number;entryPrice:number;exitPrice:number;entryAt:number;exitAt:number;netPnl:number;fees:number};
export type PaperSnapshot={seq:number;at:number;equity:number;realizedNet:number;unrealizedNet:number;drawdownCash:number};
export type PaperReplay={
 mode:'UNVERIFIED_LOCAL_RESEARCH';live:false;ordersSubmitted:0;quoteAuthenticated:false;persisted:false;
 source:PaperSource;quotes:number;closedTrades:PaperClosedTrade[];openPosition:PaperPosition|null;
 realizedNet:number;unrealizedNet:number;equity:number;peakEquity:number;
 maxDrawdownCash:number;maxDrawdownPct:number;winRate:number|null;totalFees:number;
 snapshots:PaperSnapshot[];
};
const safeTime=(n:number)=>Number.isSafeInteger(n)&&n>=0;
const positive=(n:number)=>Number.isFinite(n)&&n>0&&n<=1e9;
const nonnegative=(n:number)=>Number.isFinite(n)&&n>=0&&n<=1e6;
const key=(s:PaperSource)=>JSON.stringify([s.instrument,s.provider,s.venue,s.sourceId,s.currency]);
const sourceValid=(s:PaperSource)=>s&&[s.instrument,s.provider,s.venue,s.sourceId,s.currency].every(x=>typeof x==='string'&&x.trim().length>0&&x.length<=100);
const priceAt=(side:'LONG'|'SHORT',action:'OPEN'|'CLOSE'|'MARK',q:PaperQuote,bps:number)=>{
 const buy=action==='OPEN'?side==='LONG':side==='SHORT';
 return (buy?q.ask:q.bid)*(1+(buy?1:-1)*bps/10000);
};
/** Replays contiguous, time-ordered events. All order decisions are external,
 * simulated and non-executable. Requires explicit two-sided quote observations. */
export function replayDisconnectedPaperLedger(
 events:readonly PaperEvent[],source:PaperSource,policy:PaperPolicy,
):PaperReplay{
 if(!sourceValid(source)||!policy||!positive(policy.startingCash)||!positive(policy.maxNotional)||
    !Number.isSafeInteger(policy.maxQuoteAgeSeconds)||policy.maxQuoteAgeSeconds<0||policy.maxQuoteAgeSeconds>3600||
    !nonnegative(policy.markSlippageBps)||policy.markSlippageBps>500||
    !Array.isArray(events)||events.length>20000)
  throw Error('Invalid disconnected paper configuration');
 const sourceId=key(source);
 let lastAt=-1,latest:PaperQuote|null=null,quotes=0,realized=0,fees=0;
 let position:PaperPosition|null=null,peak=policy.startingCash,maxDd=0,maxDdPct=0,unrealized=0,equity=policy.startingCash;
 const ids=new Set<string>(),closed:PaperClosedTrade[]=[],snapshots:PaperSnapshot[]=[];
 for(let i=0;i<events.length;i++){
  const e=events[i];
  if(!e||!safeTime(e.seq)||e.seq!==i+1||!safeTime(e.at)||e.at<lastAt)
   throw Error('Noncontiguous or nonmonotonic paper event journal');
  lastAt=e.at;
  if(e.kind==='QUOTE'){
   if(!sourceValid(e.source)||key(e.source)!==sourceId||!positive(e.bid)||!positive(e.ask)||
      e.bid>=e.ask||(latest!==null&&e.at<=latest.at))
    throw Error('Mixed, crossed, invalid or revised paper quote');
   latest=e;quotes++;
  }else if(e.kind==='OPEN'||e.kind==='CLOSE'){
   if(!latest||!safeTime(e.quoteSeq)||e.quoteSeq!==latest.seq||
      e.at<latest.at||e.at-latest.at>policy.maxQuoteAgeSeconds||
      !nonnegative(e.fee)||!nonnegative(e.slippageBps)||e.slippageBps>500||
      !/^[A-Za-z0-9_-]{1,80}$/.test(e.id))
    throw Error('Missing, stale or invalid quote-bound paper event');
   if(e.kind==='OPEN'){
    if(position||ids.has(e.id)||!['LONG','SHORT'].includes(e.side)||!positive(e.quantity))
     throw Error('Duplicate id, overlapping position or invalid quantity');
    const entry=priceAt(e.side,'OPEN',latest,e.slippageBps),notional=entry*e.quantity;
    if(!Number.isFinite(notional)||notional>policy.maxNotional||
       notional+e.fee>policy.startingCash+realized)
     throw Error('Paper cash/notional limit exceeded; leverage is disabled');
    position={id:e.id,side:e.side,quantity:e.quantity,entryPrice:entry,
      entryFee:e.fee,entryAt:e.at,entryQuoteSeq:latest.seq};
    ids.add(e.id);fees+=e.fee;
   }else{
    if(!position||position.id!==e.id||latest.seq<=position.entryQuoteSeq)
     throw Error('Missing position, wrong id or no subsequent quote');
    const exit=priceAt(position.side,'CLOSE',latest,e.slippageBps);
    const gross=(position.side==='LONG'?exit-position.entryPrice:position.entryPrice-exit)*position.quantity;
    const net=gross-position.entryFee-e.fee;
    if(!Number.isFinite(net))throw Error('Invalid paper close calculation');
    realized+=net;fees+=e.fee;
    closed.push({id:position.id,side:position.side,quantity:position.quantity,
      entryPrice:position.entryPrice,exitPrice:exit,entryAt:position.entryAt,
      exitAt:e.at,netPnl:net,fees:position.entryFee+e.fee});
    position=null;
   }
  }else throw Error('Unsupported paper journal event');
  unrealized=0;
  if(position&&latest){
   const mark=priceAt(position.side,'MARK',latest,policy.markSlippageBps);
   unrealized=(position.side==='LONG'?mark-position.entryPrice:position.entryPrice-mark)*position.quantity-position.entryFee;
  }
  equity=policy.startingCash+realized+unrealized;
  if(!Number.isFinite(equity))throw Error('Nonfinite paper equity');
  peak=Math.max(peak,equity);
  maxDd=Math.max(maxDd,peak-equity);
  maxDdPct=Math.max(maxDdPct,peak>0?(peak-equity)/peak:0);
  snapshots.push({seq:e.seq,at:e.at,equity,realizedNet:realized,
    unrealizedNet:unrealized,drawdownCash:peak-equity});
 }
 return {mode:'UNVERIFIED_LOCAL_RESEARCH',live:false,ordersSubmitted:0,
  quoteAuthenticated:false,persisted:false,source:{...source},quotes,
  closedTrades:closed.map(t=>({...t})),openPosition:position?{...position}:null,
  realizedNet:realized,unrealizedNet:unrealized,equity,peakEquity:peak,
  maxDrawdownCash:maxDd,maxDrawdownPct:maxDdPct,
  winRate:closed.length?closed.filter(t=>t.netPnl>0).length/closed.length:null,
  totalFees:fees,snapshots};
}
