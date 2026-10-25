/**
 * Offline price-unit decomposition of declared demo fills against declared quotes.
 * Neither quotes nor fills are authenticated. Not a monetary P&L, broker adapter,
 * or order-execution permission. No contract multiplier or FX is inferred.
 */
import {auditDeclaredDemoOrderLifecycle} from './demo-order-lifecycle-audit.ts';
import type {DemoLifecycleEvent, DemoLifecycleIntent, DemoLifecycleScope} from './demo-order-lifecycle-audit.ts';

export type DemoQuoteDeviationPolicy = Readonly<{
  maxAdversePerContract: string;
  maxFavorablePerContract: string;
}>;
export type DemoQuoteDeviationRow = Readonly<{
  fillId: string;
  contracts: number;
  quoteId: string;
  sideQuotePrice: string;
  signedSlippagePriceUnits: string;
  halfSpreadPriceUnits: string;
  signedMidpointImpactPriceUnits: string;
  outsideDeclaredPolicy: boolean;
}>;
export type DemoQuoteDeviationReview = Readonly<{
  coverage: 'SELF_DECLARED_DEMO_FILLS_AND_QUOTES_ONLY';
  status: 'NO_DECLARED_FILLS'|'IN_RANGE_UNVERIFIED'|'OUT_OF_RANGE_UNVERIFIED';
  orderStatus: string;
  filledContracts: number;
  remainingContracts: number;
  rows: readonly DemoQuoteDeviationRow[];
  totalSignedSlippagePriceUnits: string|null;
  totalHalfSpreadPriceUnits: string|null;
  totalSignedMidpointImpactPriceUnits: string|null;
  warnings: readonly string[];
  mayExecuteOrder: false;
}>;

const SIX = 1_000_000n;
const DECIMAL = /^(?:0|[1-9][0-9]{0,7})(?:\.[0-9]{1,6})?$/;
function micro(value: unknown, label: string): bigint {
  if(typeof value!=='string'||!DECIMAL.test(value))throw Error('Invalid '+label+' decimal');
  const [whole,frac='']=value.split('.');
  return BigInt(whole)*SIX+BigInt(frac.padEnd(6,'0')||'0');
}
function fixed(value: bigint, scale: bigint, places: number): string {
  const neg=value<0n;
  const abs=neg?-value:value;
  return (neg?'-':'')+String(abs/scale)+'.'+String(abs%scale).padStart(places,'0');
}
function exactPolicy(value: unknown): asserts value is DemoQuoteDeviationPolicy {
  if(!value||typeof value!=='object'||Array.isArray(value)||
    Object.keys(value).length!==2||
    Object.keys(value).some(k=>k!=='maxAdversePerContract'&&k!=='maxFavorablePerContract'))
    throw Error('Invalid demo quote deviation policy schema');
}

/** Calls the strict lifecycle validator first; never silently repairs input events. */
export function auditDeclaredDemoQuoteDeviations(
  scope: DemoLifecycleScope,
  intent: DemoLifecycleIntent,
  events: readonly DemoLifecycleEvent[],
  policy: DemoQuoteDeviationPolicy
): DemoQuoteDeviationReview {
  const lifecycle=auditDeclaredDemoOrderLifecycle(scope,intent,events);
  exactPolicy(policy);
  const adverseCap=micro(policy.maxAdversePerContract,'adverse cap');
  const favorableCap=micro(policy.maxFavorablePerContract,'favorable cap');
  let slippage=0n, halfSpreadTwice=0n, outOfRange=false;
  const rows: DemoQuoteDeviationRow[]=[];
  for(const event of events){
    if(event.kind!=='FILL')continue;
    const bid=micro(event.quoteBid,'bid');
    const ask=micro(event.quoteAsk,'ask');
    const fill=micro(event.price,'fill price');
    const quoteSide=intent.side==='BUY'?ask:bid;
    const direction=intent.side==='BUY'?1n:-1n;
    const perContract=direction*(fill-quoteSide);
    const outside=perContract>adverseCap||-perContract>favorableCap;
    const qty=BigInt(event.contracts);
    const slip=perContract*qty;
    const spreadTwice=(ask-bid)*qty;
    slippage+=slip;
    halfSpreadTwice+=spreadTwice;
    outOfRange ||= outside;
    rows.push({fillId:event.fillId,contracts:event.contracts,quoteId:event.quoteId,
      sideQuotePrice:fixed(quoteSide,SIX,6),
      signedSlippagePriceUnits:fixed(slip,SIX,6),
      halfSpreadPriceUnits:fixed(spreadTwice*5n,10n*SIX,7),
      signedMidpointImpactPriceUnits:fixed((spreadTwice+2n*slip)*5n,10n*SIX,7),
      outsideDeclaredPolicy:outside});
  }
  const any=rows.length>0;
  return {
    coverage:'SELF_DECLARED_DEMO_FILLS_AND_QUOTES_ONLY',
    status:!any?'NO_DECLARED_FILLS':outOfRange?'OUT_OF_RANGE_UNVERIFIED':'IN_RANGE_UNVERIFIED',
    orderStatus:lifecycle.status,filledContracts:lifecycle.filledContracts,
    remainingContracts:lifecycle.remainingContracts,rows,
    totalSignedSlippagePriceUnits:any?fixed(slippage,SIX,6):null,
    totalHalfSpreadPriceUnits:any?fixed(halfSpreadTwice*5n,10n*SIX,7):null,
    totalSignedMidpointImpactPriceUnits:any?fixed((halfSpreadTwice+2n*slippage)*5n,10n*SIX,7):null,
    warnings:[
      'Declared quotes may be indicative, delayed, incomplete, or non-executable; no source authentication is performed.',
      'Price-unit x contracts values are not currency costs without a verified contract multiplier, FX, fees and financing.',
      'Unreported fills remain unknown. Policy comparisons are research flags, never evidence of execution quality or permission.',
      'Favorable slippage is signed negative; half-spread is nonnegative; no profitable trading advantage is established.'
    ],
    mayExecuteOrder:false
  };
}
