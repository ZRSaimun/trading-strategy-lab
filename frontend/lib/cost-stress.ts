import {backtest,ENGINE,STRATEGIES,type Report} from './backtest.ts';
import type {Bar} from './research.ts';

export const COST_MULTIPLIERS = [1, 2, 3] as const;
export type CostMultiplier = typeof COST_MULTIPLIERS[number];
export type CostStressRow = {
 multiplier: CostMultiplier;
 spread: number;
 slippage: number;
 commission: number;
 trades: number;
 rejected: number;
 netReturn: number;
 maxDrawdownPercent: number;
 expectancy: number;
 averageR: number;
};

/**
 * Re-run a saved strategy against the SAME historical candles at progressively
 * worse assumed trading costs. The base settings must come from the saved run,
 * not from the currently editable form. This is sensitivity analysis, NOT an
 * independent sample, broker fill verification, or evidence of future profit.
 *
 * Stops, targets, position sizing and entry validity are recomputed for each
 * cost level; subtracting a flat fee from a finished report is not equivalent.
 */
export function runCostStress(bars: Bar[], saved: Report): CostStressRow[] {
 const strategy = STRATEGIES.find(s => s.id === saved.strategy);
 if (saved.engine !== ENGINE || !strategy || saved.ruleVersion !== strategy.version)
  throw Error('Saved strategy or simulator version is incompatible with the current engine');
 const base = saved.config;
 if (saved.bars !== bars.length || saved.start !== bars[0]?.time ||
     saved.end !== (bars.at(-1)?.time ?? NaN) + base.barSeconds)
  throw Error('Saved candle snapshot does not match the historical report coverage');
 if (![base.spread, base.slippage, base.commission].every(Number.isFinite) ||
     base.spread < 0 || base.slippage < 0 || base.commission < 0)
  throw Error('Cost assumptions must be finite, nonnegative numbers');
 if (base.spread === 0 && base.slippage === 0 && base.commission === 0)
  throw Error('Enter at least one nonzero source-specific cost before running a cost stress test');
 const baseline = backtest(bars, saved.strategy, base);
 if (baseline.metrics.trades !== saved.metrics.trades ||
     baseline.metrics.rejected !== saved.metrics.rejected ||
     !Number.isFinite(saved.metrics.netReturn) ||
     Math.abs(baseline.metrics.netReturn - saved.metrics.netReturn) > 1e-7)
  throw Error('Saved baseline is not reproducible with these candles and settings');
 return COST_MULTIPLIERS.map(multiplier => {
  const config = {...base,
   spread: base.spread * multiplier,
   slippage: base.slippage * multiplier,
   commission: base.commission * multiplier,
  };
  const {metrics} = multiplier === 1 ? baseline : backtest(bars, saved.strategy, config);
  return {
   multiplier, spread: config.spread, slippage: config.slippage,
   commission: config.commission, trades: metrics.trades,
   rejected: metrics.rejected, netReturn: metrics.netReturn,
   maxDrawdownPercent: metrics.maxDrawdownPercent,
   expectancy: metrics.expectancy, averageR: metrics.averageR,
  };
 });
}
