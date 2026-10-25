/** Read-only CFD cost envelope over self-declared quote/fill and financing evidence.
 * No broker connection, orders, profit estimates or risk approvals.
 */
import {auditDeclaredQuoteExecutions, type QuoteExecutionScope, type DeclaredOrder,
  type DeclaredQuote, type DeclaredFill} from './declared-quote-execution-audit.ts';
import {auditDeclaredCfdFinancing, type FinancingScope,
  type FinancingReceipt} from './declared-cfd-financing-audit.ts';
import {assertDeclaredCfdTemporalConsistency} from './declared-cfd-temporal-consistency.ts';

export type CostStress = Readonly<{
  id:string;
  /** Incremental one-sided costs in settlement currency; never re-add base costs. */
  extraHalfSpreadCurrency:string;
  extraSlippageCurrency:string;
  extraCommissionCurrency:string;
  extraFinancingCurrency:string;
}>;
export type CostScenarioReview = Readonly<{
  id:string; stressedCostCurrency:string|null;
  status:'INCOMPLETE_DECLARED_EVIDENCE'|'WITHIN_DECLARED_COST_BUDGET'|'EXCEEDS_DECLARED_COST_BUDGET';
}>;
export type DeclaredCostEnvelope = Readonly<{
  coverage:'SELF_DECLARED_OFFLINE_COST_EVIDENCE_ONLY';
  baseCostCurrency:string|null;
  declaredCostBudgetCurrency:string;
  scenarios:readonly CostScenarioReview[];
  warnings:readonly string[];
}>;
const ID=/^[A-Za-z0-9._:-]{1,100}$/;
const UNIT=10_000_000_000_000n;
function exact(x:unknown,keys:readonly string[],label:string):void {
  if(!x||typeof x!=='object'||Array.isArray(x)||Object.keys(x).length!==keys.length||
    Object.keys(x).some(k=>!keys.includes(k))) throw Error('Invalid '+label+' schema');
}
function cashCents(x:unknown,label:string):bigint {
  if(typeof x!=='string'||! /^(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,2})?$/.test(x))
    throw Error('Invalid '+label+' cash amount');
  const [whole,frac='']=x.split('.');
  return (BigInt(whole)*100n+BigInt(frac.padEnd(2,'0')||'0'))*(UNIT/100n);
}
function signedCash13(x:unknown):bigint {
  if(typeof x!=='string'||! /^-?(?:0|[1-9][0-9]{0,12})(?:\.[0-9]{1,13})?$/.test(x))
    throw Error('Invalid declared quote friction amount');
  const negative=x.startsWith('-');
  const [whole,frac='']=(negative?x.slice(1):x).split('.');
  const n=BigInt(whole)*UNIT+BigInt(frac.padEnd(13,'0')||'0');
  return negative?-n:n;
}
function signedFinancingCents(x:unknown):bigint {
  if(typeof x!=='string'||! /^-?(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,2})?$/.test(x))
    throw Error('Invalid declared financing amount');
  const negative=x.startsWith('-');
  const n=cashCents(negative?x.slice(1):x,'financing');
  return negative?-n:n;
}
function money13(value:bigint):string {
  const negative=value<0n, n=negative?-value:value;
  return (negative?'-':'')+(n/UNIT)+'.'+String(n%UNIT).padStart(13,'0');
}
/** Revalidate raw records. Incomplete fills or rollovers must never imply zero cost.
 * A cost budget is NOT a trade loss cap or evidence of profitability.
 */
export function reviewDeclaredCfdCostEnvelope(
  quoteScope:QuoteExecutionScope, orders:readonly DeclaredOrder[],
  quotes:readonly DeclaredQuote[], fills:readonly DeclaredFill[],
  financingScope:FinancingScope, financingReceipts:readonly FinancingReceipt[],
  declaredCostBudgetCurrency:string, stresses:readonly CostStress[]
):DeclaredCostEnvelope {
  const quoteAudit=auditDeclaredQuoteExecutions(quoteScope,orders,quotes,fills);
  const financingAudit=auditDeclaredCfdFinancing(financingScope,financingReceipts);
  if(quoteScope.provider!==financingScope.provider || quoteScope.venue!==financingScope.venue ||
     quoteScope.instrument!==financingScope.instrument ||
     quoteScope.accountAlias!==financingScope.accountAlias ||
     quoteScope.quoteCurrency!==financingScope.settlementCurrency)
    throw Error('Cross-source or cross-currency CFD cost evidence cannot be combined');
  assertDeclaredCfdTemporalConsistency(quoteScope,orders,fills,financingScope);
  const budget=cashCents(declaredCostBudgetCurrency,'budget');
  if(!Array.isArray(stresses)||stresses.length===0||stresses.length>12)
    throw Error('A bounded nonempty stress grid is required');
  const seen=new Set<string>();
  const parsed=stresses.map(s=>{
    exact(s,['id','extraHalfSpreadCurrency','extraSlippageCurrency',
      'extraCommissionCurrency','extraFinancingCurrency'],'stress');
    if(!ID.test(s.id)||seen.has(s.id)) throw Error('Invalid or duplicate stress ID');
    seen.add(s.id);
    return {id:s.id,extra:
      cashCents(s.extraHalfSpreadCurrency,'spread stress')+
      cashCents(s.extraSlippageCurrency,'slippage stress')+
      cashCents(s.extraCommissionCurrency,'commission stress')+
      cashCents(s.extraFinancingCurrency,'financing stress')};
  });
  const complete=quoteAudit.status==='COMPLETE_DECLARED' &&
    financingAudit.status==='MATCHED_DECLARED' &&
    quoteAudit.completeFrictionCurrency!==null &&
    financingAudit.totalChargeCurrency!==null;
  const base=complete?
    signedCash13(quoteAudit.completeFrictionCurrency!)+
    signedFinancingCents(financingAudit.totalChargeCurrency!):null;
  return {coverage:'SELF_DECLARED_OFFLINE_COST_EVIDENCE_ONLY',
    baseCostCurrency:base===null?null:money13(base),
    declaredCostBudgetCurrency:money13(budget),
    scenarios:parsed.map(s=>{
      const stressed=base===null?null:base+s.extra;
      return {id:s.id,stressedCostCurrency:stressed===null?null:money13(stressed),
        status:stressed===null?'INCOMPLETE_DECLARED_EVIDENCE' as const:
          stressed>budget?'EXCEEDS_DECLARED_COST_BUDGET' as const:
            'WITHIN_DECLARED_COST_BUDGET' as const};
    }),warnings:[
      'Quote/fill/rollover evidence and source identities are caller declarations, not authenticated broker records.',
      'One-sided fill friction already includes half-spread, slippage and commission; stresses must not double-count base costs.',
      'No trading P&L, margin, FX, market liquidity, real risk cap, broker schedule completeness or profitability is measured.',
      'Incomplete fill or rollover evidence withholds ALL base and stressed totals; no zero-cost substitution.',
      'Temporal checks only constrain declared order/fill times to the declared position window; they do not prove orders belong to that position.'
    ]};
}
