import {backtest,type Config,type StrategyId} from './backtest.ts';
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
export function runCostStress(bars: Bar[], strategy: StrategyId, base: Config): CostStressRow[] {
 if (![base.spread, base.slippage, base.commission].every(Number.isFinite) ||
     base.spread < 0 || base.slippage < 0 || base.commission < 0)
  throw Error('Cost assumptions must be finite, nonnegative numbers');
 if (base.spread === 0 && base.slippage === 0 && base.commission === 0)
  throw Error('Enter at least one nonzero source-specific cost before running a cost stress test');
 return COST_MULTIPLIERS.map(multiplier => {
  const config = {...base,
   spread: base.spread * multiplier,
   slippage: base.slippage * multiplier,
   commission: base.commission * multiplier,
  };
  const {metrics} = backtest(bars, strategy, config);
  return {
   multiplier, spread: config.spread, slippage: config.slippage,
   commission: config.commission, trades: metrics.trades,
   rejected: metrics.rejected, netReturn: metrics.netReturn,
   maxDrawdownPercent: metrics.maxDrawdownPercent,
   expectancy: metrics.expectancy, averageR: metrics.averageR,
  };
 });
}
