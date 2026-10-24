/** Read-only comparison of simulated paper orders to independently supplied demo fills.
 * No broker client, authentication, execution route, or real-money capability.
 * Source fields and statement digest are declarations, NOT verified provenance.
 */
import type {PaperIdentity, PaperOrder, PaperSide} from './paper-execution.ts';

export type DemoFill = Readonly<{
  executionId:string; brokerOrderId:string; clientOrderId:string;
  instrument:string; provider:string; venue:string; accountAlias:string;
  statementSha256:string; currency:string;
  leg:'ENTRY'|'EXIT'; side:PaperSide; units:number; price:number;
  executedAt:number; receivedAt:number; feeCurrency:number;
}>;
export type DemoSource = Readonly<{
  brokerOrderId:string; accountAlias:string; statementSha256:string; currency:string;
}>;
export type DemoComparison = Readonly<{
  status:'INCOMPLETE'|'TIMING_MISMATCH'|'COMPARABLE_UNVERIFIED';
  coverage:'DECLARED_SOURCE_ONLY_FINANCING_UNKNOWN';
  uniqueFills:number; entryUnits:number; exitUnits:number;
  paperNetPnlCurrency:number; demoGrossPnlCurrency:number|null;
  demoKnownNetPnlCurrency:number|null; knownNetDeltaCurrency:number|null;
  maxExecutionSkewSeconds:number|null;
}>;
const fillKeys=['executionId','brokerOrderId','clientOrderId','instrument','provider','venue',
  'accountAlias','statementSha256','currency','leg','side','units','price','executedAt','receivedAt','feeCurrency'];
const positive=(v:number)=>typeof v==='number'&&Number.isFinite(v)&&v>0;
const nonnegative=(v:number)=>typeof v==='number'&&Number.isFinite(v)&&v>=0;
const time=(v:number)=>Number.isSafeInteger(v)&&v>=0;
const text=(v:string,max:number)=>typeof v==='string'&&v.trim().length>0&&v.length<=max;
const close=(a:number,b:number)=>Number.isFinite(a)&&Number.isFinite(b)&&
  Math.abs(a-b)<=16*Number.EPSILON*Math.max(Math.abs(a),Math.abs(b),Number.MIN_VALUE);
const opposite=(side:PaperSide):PaperSide=>side==='BUY'?'SELL':'BUY';
const sameFill=(a:DemoFill,b:DemoFill)=>fillKeys.every(k=>a[k as keyof DemoFill]===b[k as keyof DemoFill]);

/** Only compare same-source, complete, timely demo fills. Never infer a fill from OHLC.
 * All quantities and fees are declared inputs; financing, FX and authenticity remain unknown.
 */
export function comparePaperWithDemoFills(
  identity:PaperIdentity, paper:PaperOrder, source:DemoSource, paperSettlementCurrency:string,
  asOf:number, maxExecutionSkewSeconds:number, fills:readonly DemoFill[]
):DemoComparison {
  if(identity.priceSide!=='bid-ask'||!text(identity.instrument,160)||!text(identity.provider,160)||
     !text(identity.venue,160)||!positive(identity.pointValue)||paper.instrument!==identity.instrument||
     paper.status!=='CLOSED'||(paper.side!=='BUY'&&paper.side!=='SELL')||
     !text(paper.clientOrderId,80)||!positive(paper.units)||!positive(paper.entry!)||!positive(paper.exit!)||
     !nonnegative(paper.commissionPerUnitSide)||!nonnegative(paper.costs!)||
     !Number.isFinite(paper.pnl)||!time(paper.submittedAt)||!time(paper.expiresAt)||
     !time(paper.entryObservedAt!)||!time(paper.entryReceivedAt!)||
     !time(paper.exitObservedAt!)||!time(paper.exitReceivedAt!)||
     paper.expiresAt<=paper.submittedAt||paper.entryObservedAt!<=paper.submittedAt||
     paper.entryReceivedAt!<paper.entryObservedAt!||paper.entryReceivedAt!>=paper.expiresAt||
     paper.exitObservedAt!<=paper.entryObservedAt!||
     paper.exitReceivedAt!<paper.exitObservedAt!||
     paper.exitReceivedAt!<=paper.entryReceivedAt!||!time(asOf)||asOf<paper.exitReceivedAt!||
     !time(maxExecutionSkewSeconds)||!text(source.brokerOrderId,120)||
     !text(source.accountAlias,120)||!text(source.currency,12)||
     !text(paperSettlementCurrency,12)||paperSettlementCurrency!==source.currency||
     !/^[a-fA-F0-9]{64}$/.test(source.statementSha256))
    throw Error('Invalid closed paper order or declared demo comparison source');
  const expectedCosts=2*paper.commissionPerUnitSide*paper.units;
  const paperGross=(paper.side==='BUY'?paper.exit!-paper.entry!:paper.entry!-paper.exit!)*paper.units*identity.pointValue;
  if(!Number.isFinite(expectedCosts)||!Number.isFinite(paperGross)||
     !close(paper.costs!,expectedCosts)||!close(paper.pnl!,paperGross-expectedCosts))
    throw Error('Paper P&L or commission does not reconcile');
  const unique=new Map<string,DemoFill>();
  for(const f of fills){
    if(!f||typeof f!=='object'||Object.keys(f).sort().join('|')!==[...fillKeys].sort().join('|')||
       !text(f.executionId,120)||f.brokerOrderId!==source.brokerOrderId||
       f.clientOrderId!==paper.clientOrderId||f.instrument!==identity.instrument||
       f.provider!==identity.provider||f.venue!==identity.venue||
       f.accountAlias!==source.accountAlias||f.statementSha256!==source.statementSha256||
       f.currency!==source.currency||(f.leg!=='ENTRY'&&f.leg!=='EXIT')||
       f.side!==(f.leg==='ENTRY'?paper.side:opposite(paper.side))||
       !positive(f.units)||!positive(f.price)||!nonnegative(f.feeCurrency)||
       !time(f.executedAt)||!time(f.receivedAt)||f.executedAt>f.receivedAt||
       f.executedAt<paper.submittedAt||f.receivedAt>asOf)
      throw Error('Invalid, future, unmatched or unprovenanced demo fill');
    const prior=unique.get(f.executionId);
    if(prior){if(!sameFill(prior,f))throw Error('Conflicting duplicate demo execution ID');continue;}
    unique.set(f.executionId,{...f});
  }
  const ordered=[...unique.values()].sort((a,b)=>a.executedAt-b.executedAt||
    (a.leg===b.leg?0:a.leg==='ENTRY'?-1:1)||a.receivedAt-b.receivedAt||
    a.executionId.localeCompare(b.executionId));
  let entryUnits=0,exitUnits=0,entryValue=0,exitValue=0,fees=0,maxSkew:number|null=null;
  for(const f of ordered){
    if(f.leg==='ENTRY'){
      entryUnits+=f.units;entryValue+=f.price*f.units;
    }else{
      exitUnits+=f.units;exitValue+=f.price*f.units;
      if(exitUnits>entryUnits&&!close(exitUnits,entryUnits))throw Error('Demo exit exceeds preceding entry fills');
    }
    fees+=f.feeCurrency;
    const skew=Math.abs(f.receivedAt-(f.leg==='ENTRY'?paper.entryReceivedAt!:paper.exitReceivedAt!));
    maxSkew=Math.max(maxSkew??0,skew);
    if(!Number.isFinite(entryUnits)||!Number.isFinite(exitUnits)||
       !Number.isFinite(entryValue)||!Number.isFinite(exitValue)||!Number.isFinite(fees)||
       entryUnits>paper.units&&!close(entryUnits,paper.units)||
       exitUnits>paper.units&&!close(exitUnits,paper.units))
      throw Error('Demo quantity, price or fee arithmetic exceeds paper bounds');
  }
  const base={coverage:'DECLARED_SOURCE_ONLY_FINANCING_UNKNOWN' as const,
    uniqueFills:unique.size,entryUnits,exitUnits,paperNetPnlCurrency:paper.pnl!,
    maxExecutionSkewSeconds:maxSkew};
  if(!close(entryUnits,paper.units)||!close(exitUnits,paper.units))
    return {...base,status:'INCOMPLETE',demoGrossPnlCurrency:null,
      demoKnownNetPnlCurrency:null,knownNetDeltaCurrency:null};
  if(maxSkew!==null&&maxSkew>maxExecutionSkewSeconds)
    return {...base,status:'TIMING_MISMATCH',demoGrossPnlCurrency:null,
      demoKnownNetPnlCurrency:null,knownNetDeltaCurrency:null};
  const gross=(paper.side==='BUY'?exitValue-entryValue:entryValue-exitValue)*identity.pointValue;
  const net=gross-fees,delta=net-paper.pnl!;
  if(!Number.isFinite(gross)||!Number.isFinite(net)||!Number.isFinite(delta))
    throw Error('Non-finite demo P&L arithmetic');
  return {...base,status:'COMPARABLE_UNVERIFIED',demoGrossPnlCurrency:gross,
    demoKnownNetPnlCurrency:net,knownNetDeltaCurrency:delta};
}
