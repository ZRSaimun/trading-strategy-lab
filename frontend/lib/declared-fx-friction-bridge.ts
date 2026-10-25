/** Offline, point-in-time FX translation of already revalidated, self-declared quote/fill costs.
 * Neither the CFD multiplier nor FX observations are authenticated broker evidence.
 * This module never contacts a provider, places orders or calculates trading returns.
 */
import {auditDeclaredQuoteExecutions, type QuoteExecutionScope, type DeclaredOrder,
  type DeclaredQuote, type DeclaredFill} from './declared-quote-execution-audit.ts';

export type FxFrictionPolicy = Readonly<{
  accountCurrency:string;
  /** Null for native-currency costs; otherwise a pinned, declared FX data source. */
  fxSourceId:string|null;
  fxBatchSha256:string|null;
  maxFxAgeMs:number|null;
}>;
export type DeclaredFillFx = Readonly<{
  fillId:string; fxQuoteId:string; sourceId:string; batchSha256:string;
  fromCurrency:string; toCurrency:string;
  /** Account currency units per one quote-currency unit, at or before the fill. */
  rate:string; observedAt:number; recordedAt:number;
}>;
export type FxFrictionRow = Readonly<{
  fillId:string; fxQuoteId:string|null; rate:string;
  quoteFrictionCurrency:string;
  halfSpreadAccountCurrency:string; slippageAccountCurrency:string;
  commissionAccountCurrency:string; totalFrictionAccountCurrency:string;
}>;
export type FxFrictionReview = Readonly<{
  coverage:'SELF_DECLARED_POINT_IN_TIME_FX_AND_FILL_COSTS_ONLY';
  status:'NO_DECLARED_FILLS'|'PARTIAL_DECLARED'|'COMPLETE_DECLARED';
  quoteCurrency:string; accountCurrency:string;
  observedFrictionAccountCurrency:string|null;
  completeFrictionAccountCurrency:string|null;
  rows:readonly FxFrictionRow[];
  warnings:readonly string[]; mayExecuteOrder:false;
}>;
const ID=/^[A-Za-z0-9._:-]{1,120}$/;
const CUR=/^[A-Z]{3}$/;
const SHA=/^[a-f0-9]{64}$/;
const DEC6=/^(?:0|[1-9][0-9]{0,7})(?:\.[0-9]{1,6})?$/;
const SIGNED13=/^-?(?:0|[1-9][0-9]{0,12})(?:\.[0-9]{1,13})?$/;
const UNIT13=10_000_000_000_000n;
const UNIT6=1_000_000n;
const UNIT19=UNIT13*UNIT6;
const TIME=(n:unknown):n is number=>typeof n==='number'&&Number.isSafeInteger(n)&&n>=0;
function exact(x:unknown,fields:readonly string[],label:string):void {
  if(!x||typeof x!=='object'||Array.isArray(x)||Object.keys(x).length!==fields.length||
    Object.keys(x).some(k=>!fields.includes(k)))throw Error('Invalid '+label+' schema');
}
function rate6(x:unknown):bigint {
  if(typeof x!=='string'||!DEC6.test(x))throw Error('Invalid FX rate decimal');
  const [whole,frac='']=x.split('.');
  const rate=BigInt(whole)*UNIT6+BigInt(frac.padEnd(6,'0')||'0');
  if(rate===0n)throw Error('Zero FX rate');
  return rate;
}
function cash13(x:unknown):bigint {
  if(typeof x!=='string'||!SIGNED13.test(x))throw Error('Invalid quote-currency friction');
  const negative=x.startsWith('-');
  const [whole,frac='']=(negative?x.slice(1):x).split('.');
  const value=BigInt(whole)*UNIT13+BigInt(frac.padEnd(13,'0')||'0');
  return negative?-value:value;
}
function money19(x:bigint):string {
  const negative=x<0n,abs=negative?-x:x;
  return (negative?'-':'')+String(abs/UNIT19)+'.'+String(abs%UNIT19).padStart(19,'0');
}
/** Requires one FX observation for EACH declared fill when currencies differ.
 * A quote first recorded after its fill is rejected, even if its claimed observation was earlier.
 * Does not substitute a later daily close, future FX fixing or a guessed parity rate.
 */
export function reviewDeclaredFxFriction(
  scope:QuoteExecutionScope,orders:readonly DeclaredOrder[],
  quotes:readonly DeclaredQuote[],fills:readonly DeclaredFill[],
  policy:FxFrictionPolicy,fx:readonly DeclaredFillFx[]
):FxFrictionReview {
  // Revalidate the complete source-bound quote, order and fill population first.
  const audit=auditDeclaredQuoteExecutions(scope,orders,quotes,fills);
  exact(policy,['accountCurrency','fxSourceId','fxBatchSha256','maxFxAgeMs'],'FX policy');
  if(typeof policy.accountCurrency!=='string'||!CUR.test(policy.accountCurrency))
    throw Error('Invalid account currency');
  const native=policy.accountCurrency===scope.quoteCurrency;
  if(native){
    if(policy.fxSourceId!==null||policy.fxBatchSha256!==null||policy.maxFxAgeMs!==null)
      throw Error('Native-currency conversion must not declare an FX feed');
  }else if(typeof policy.fxSourceId!=='string'||!ID.test(policy.fxSourceId)||
    typeof policy.fxBatchSha256!=='string'||!SHA.test(policy.fxBatchSha256)||
    !TIME(policy.maxFxAgeMs)||policy.maxFxAgeMs===0||policy.maxFxAgeMs>300_000){
    throw Error('Invalid or unbounded FX source/freshness policy');
  }
  if(!Array.isArray(fx)||fx.length>5000||(native&&fx.length!==0))
    throw Error('Invalid FX observation population');
  const byFill=new Map<string,{id:string;rate:bigint}>();
  const quoteIdentity=new Map<string,string>();
  const fillById=new Map(fills.map(fill=>[fill.fillId,fill]));
  for(const row of fx){
    exact(row,['fillId','fxQuoteId','sourceId','batchSha256','fromCurrency','toCurrency',
      'rate','observedAt','recordedAt'],'FX observation');
    const fill=fillById.get(row.fillId);
    if(!fill||byFill.has(row.fillId)||typeof row.fxQuoteId!=='string'||!ID.test(row.fxQuoteId)||
      row.sourceId!==policy.fxSourceId||row.batchSha256!==policy.fxBatchSha256||
      row.fromCurrency!==scope.quoteCurrency||row.toCurrency!==policy.accountCurrency||
      !TIME(row.observedAt)||!TIME(row.recordedAt)||row.recordedAt<row.observedAt||
      row.observedAt>fill.filledAt||row.recordedAt>fill.filledAt||
      fill.filledAt-row.observedAt>policy.maxFxAgeMs!)
      throw Error('Missing, duplicate, stale, late-recorded or cross-source FX observation');
    const parsedRate=rate6(row.rate);
    const identity=JSON.stringify([row.sourceId,row.batchSha256,row.fromCurrency,
      row.toCurrency,row.rate,row.observedAt,row.recordedAt]);
    const previous=quoteIdentity.get(row.fxQuoteId);
    if(previous!==undefined&&previous!==identity)
      throw Error('Conflicting FX quote identity across fills');
    quoteIdentity.set(row.fxQuoteId,identity);
    byFill.set(row.fillId,{id:row.fxQuoteId,rate:parsedRate});
  }
  if(!native&&byFill.size!==fills.length)
    throw Error('Missing FX observations for declared fills');
  const rows:FxFrictionRow[]=[];
  let observed=0n;
  for(const friction of audit.fillFriction){
    const fxRow=native?null:byFill.get(friction.fillId);
    if(!native&&!fxRow)throw Error('Missing FX observation for fill');
    const rate=fxRow?.rate??UNIT6;
    const spread=cash13(friction.halfSpreadCurrency)*rate;
    const slip=cash13(friction.slippageCurrency)*rate;
    const commission=cash13(friction.commissionCurrency)*rate;
    const total=cash13(friction.totalFrictionCurrency)*rate;
    if(spread+slip+commission!==total)throw Error('Inconsistent quote friction components');
    observed+=total;
    rows.push({fillId:friction.fillId,fxQuoteId:fxRow?.id??null,
      rate:money19(rate*UNIT13),quoteFrictionCurrency:friction.totalFrictionCurrency,
      halfSpreadAccountCurrency:money19(spread),slippageAccountCurrency:money19(slip),
      commissionAccountCurrency:money19(commission),totalFrictionAccountCurrency:money19(total)});
  }
  return {coverage:'SELF_DECLARED_POINT_IN_TIME_FX_AND_FILL_COSTS_ONLY',
    status:audit.status,quoteCurrency:scope.quoteCurrency,accountCurrency:policy.accountCurrency,
    observedFrictionAccountCurrency:rows.length?money19(observed):null,
    completeFrictionAccountCurrency:audit.status==='COMPLETE_DECLARED'&&
      audit.completeFrictionCurrency!==null?money19(observed):null,
    rows,warnings:[
      'All quote, fill, multiplier and FX source evidence is caller-declared and unauthenticated.',
      'Point-in-time FX conversion is not proof of an executable rate, actual settlement FX, fees, financing or broker accounting.',
      'Observed costs on partial fills are NOT full-order costs; incomplete fills withhold complete friction.',
      'No trading return, profit expectation, real risk cap, order routing or execution permission is established.'
    ],mayExecuteOrder:false};
}
