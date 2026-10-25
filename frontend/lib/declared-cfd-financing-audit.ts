/** Offline, self-declared CFD financing receipt completeness review.
 * Never fetches broker data, infers rollovers, or calculates strategy P&L.
 */
export type FinancingScope = Readonly<{
  provider:string; venue:string; instrument:string; accountAlias:string;
  positionId:string; settlementCurrency:string; statementSha256:string;
  openedAt:number; closedAt:number; asOf:number;
  requiredRolloverTimes:readonly number[];
}>;
export type FinancingReceipt = Readonly<{
  receiptId:string; provider:string; venue:string; instrument:string;
  accountAlias:string; positionId:string; settlementCurrency:string;
  statementSha256:string; rolloverAt:number; recordedAt:number;
  /** Signed settlement-currency cash charge: positive=debit, negative=credit. */
  amountCurrency:string;
}>;
export type FinancingAudit = Readonly<{
  status:'MATCHED_DECLARED'|'MISSING_DECLARED_EVENTS'|'NO_DECLARED_EVENTS';
  coverage:'SELF_DECLARED_SCHEDULE_AND_RECEIPTS_ONLY';
  requiredEvents:number; matchedEvents:number; missingRolloverTimes:readonly number[];
  /** Null unless every declared rollover has one matching receipt. */
  totalChargeCurrency:string|null;
  warnings:readonly string[];
}>;
const SHA=/^[a-f0-9]{64}$/;
const ID=/^[A-Za-z0-9._:-]{1,120}$/;
const CUR=/^[A-Z]{3}$/;
const TIME=(n:unknown):n is number=>typeof n==='number'&&Number.isSafeInteger(n)&&n>=0;
const TXT=(s:unknown):s is string=>typeof s==='string'&&s.length>0&&s.length<=120&&s.trim()===s;
const RECEIPT_KEYS=['receiptId','provider','venue','instrument','accountAlias','positionId',
  'settlementCurrency','statementSha256','rolloverAt','recordedAt','amountCurrency'];
const SCOPE_KEYS=['provider','venue','instrument','accountAlias','positionId',
  'settlementCurrency','statementSha256','openedAt','closedAt','asOf','requiredRolloverTimes'];
function exact(x:unknown,keys:readonly string[],label:string):void {
  if(!x||typeof x!=='object'||Array.isArray(x)||
    Object.keys(x).length!==keys.length||Object.keys(x).some(k=>!keys.includes(k)))
    throw Error(`Invalid ${label} schema`);
}
function cents(s:unknown):bigint {
  if(typeof s!=='string'||! /^(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,2})?$|^-(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,2})?$/.test(s)||s==='-0'||s==='-0.0'||s==='-0.00')
    throw Error('Invalid signed decimal financing charge');
  const negative=s.startsWith('-');
  const [whole,fraction='']=(negative?s.slice(1):s).split('.');
  const n=BigInt(whole)*100n+BigInt(fraction.padEnd(2,'0')||'0');
  return negative?-n:n;
}
function money(value:bigint):string {
  const negative=value<0n;
  const n=negative?-value:value;
  return `${negative?'-':''}${n/100n}.${String(n%100n).padStart(2,'0')}`;
}
/** Checks declared receipt completeness, NOT whether a broker supplied all real rollovers.
 * Missing declared events withhold totals. Extra/unmatched receipts fail closed.
 */
export function auditDeclaredCfdFinancing(
  scope:FinancingScope, receipts:readonly FinancingReceipt[]
):FinancingAudit {
  exact(scope,SCOPE_KEYS,'financing scope');
  if(![scope.provider,scope.venue,scope.instrument,scope.accountAlias].every(TXT)||
     !ID.test(scope.positionId)||!CUR.test(scope.settlementCurrency)||
     !SHA.test(scope.statementSha256)||
     ![scope.openedAt,scope.closedAt,scope.asOf].every(TIME)||
     scope.openedAt>=scope.closedAt||scope.closedAt>scope.asOf||
     !Array.isArray(scope.requiredRolloverTimes)||scope.requiredRolloverTimes.length>5000)
    throw Error('Invalid financing source, interval or declared schedule');
  let previous=-1;
  for(const t of scope.requiredRolloverTimes){
    if(!TIME(t)||t<=previous||t<scope.openedAt||t>=scope.closedAt)
      throw Error('Invalid, unsorted or duplicate declared rollover timestamp');
    previous=t;
  }
  if(!Array.isArray(receipts)||receipts.length>5000)
    throw Error('Unbounded financing receipts');
  const required=new Set(scope.requiredRolloverTimes);
  const found=new Map<number,bigint>();
  const ids=new Set<string>();
  for(const r of receipts){
    exact(r,RECEIPT_KEYS,'financing receipt');
    if(!ID.test(r.receiptId)||ids.has(r.receiptId)||
       r.provider!==scope.provider||r.venue!==scope.venue||
       r.instrument!==scope.instrument||r.accountAlias!==scope.accountAlias||
       r.positionId!==scope.positionId||r.settlementCurrency!==scope.settlementCurrency||
       r.statementSha256!==scope.statementSha256||
       !TIME(r.rolloverAt)||!required.has(r.rolloverAt)||found.has(r.rolloverAt)||
       !TIME(r.recordedAt)||r.recordedAt<r.rolloverAt||r.recordedAt>scope.asOf)
      throw Error('Duplicate, unmatched, future or cross-source financing receipt');
    const amount=cents(r.amountCurrency);
    ids.add(r.receiptId);found.set(r.rolloverAt,amount);
  }
  const missing=scope.requiredRolloverTimes.filter(t=>!found.has(t));
  const status=scope.requiredRolloverTimes.length===0?'NO_DECLARED_EVENTS':
    missing.length?'MISSING_DECLARED_EVENTS':'MATCHED_DECLARED';
  const total=status==='MATCHED_DECLARED'?
    money([...found.values()].reduce((a,b)=>a+b,0n)):null;
  return {status,coverage:'SELF_DECLARED_SCHEDULE_AND_RECEIPTS_ONLY',
    requiredEvents:required.size,matchedEvents:found.size,
    missingRolloverTimes:missing,totalChargeCurrency:total,
    warnings:[
      'Rollover schedule and statement digest are caller declarations, not authenticated broker evidence.',
      'An omitted rollover is undetectable without an independent broker calendar and complete statement.',
      'Charges are settlement-currency cash amounts only; no price P&L, FX conversion, margin or financing forecast is calculated.',
      'Matched declared receipts do not establish executable CFD costs, demo execution fidelity or profitability.'
    ]};
}
