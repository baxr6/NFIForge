// an open trade's two profits, as freqtrade reports them:
// total = the whole trade, partial exits included; current = the part still open
export function totalProfit(trade: Record<string, any>): { abs: number; pct: number } {
  return { abs: trade.total_profit_abs ?? trade.profit_abs ?? 0, pct: (trade.total_profit_ratio ?? trade.profit_ratio ?? 0) * 100 }
}
export function currentProfit(trade: Record<string, any>): { abs: number; pct: number } {
  return { abs: trade.profit_abs ?? 0, pct: (trade.profit_ratio ?? 0) * 100 }
}
