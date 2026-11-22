import type { Mark, TradeOverlay } from "@/components/charts/CandleChart.vue"

export type Trade = Record<string, any>
export type Order = Record<string, any>

// entry orders are buys for longs and sells for shorts
export const isEntry = (trade: Trade, order: Order) => (order.ft_order_side === "buy") !== !!trade.is_short

export const filledOrders = (trade: Trade): Order[] =>
  ((trade.orders ?? []) as Order[]).filter((order) => (order.filled ?? 0) > 0).sort((left, right) => (left.order_filled_timestamp ?? 0) - (right.order_filled_timestamp ?? 0))

export const openTs = (trade: Trade) => (trade.open_timestamp ?? 0) / 1000
export const closeTs = (trade: Trade) => (trade.close_timestamp ? trade.close_timestamp / 1000 : Date.now() / 1000)

// chart overlay: first entry, grind/dca adds sized by cost, exits; times snapped to the candle size
export function overlay(trade: Trade, candleSec: number): TradeOverlay {
  const snap = (millis: number) => Math.floor(millis / 1000 / candleSec) * candleSec
  let first = true
  const marks = filledOrders(trade).map((order) => {
    const entry = isEntry(trade, order)
    const kind = entry ? (first ? "entry" : "dca") : "exit"
    if (entry) first = false
    const tag = (order.ft_order_tag ?? "").replace(/_entry$/, "").replace(/_/g, " ")
    return { time: snap(order.order_filled_timestamp ?? trade.open_timestamp), kind: kind as "entry" | "dca" | "exit", text: kind === "entry" ? trade.enter_tag : tag || undefined, stake: order.cost }
  })
  return {
    side: trade.is_short ? "short" : "long",
    avgEntry: trade.open_rate,
    liquidation: trade.is_open ? trade.liquidation_price ?? undefined : undefined,
    stop: trade.is_open ? stopBeforeLiq(trade) : undefined,
    openTime: snap(trade.open_timestamp),
    closeTime: trade.close_timestamp ? snap(trade.close_timestamp) : undefined,
    marks,
  }
}

// the stop, when it would fire before liquidation (NFI's -99 % stop sits past it and says nothing)
function stopBeforeLiq(trade: Trade): number | undefined {
  const stop = trade.stop_loss_abs, liq = trade.liquidation_price, entry = trade.open_rate
  if (!stop || !entry) return undefined
  if (!liq) return stop
  return Math.abs(stop - entry) < Math.abs(liq - entry) ? stop : undefined
}

// every trade of a pair as chart marks, for those not drawn as the open overlay: labels only on the first entry (tag)
// and final exit (trade %); grind adds and partial exits stay unlabelled
export function pairMarks(closed: Trade[], open: Trade[], candleSec: number): Mark[] {
  const out: Mark[] = closed.flatMap((trade) => {
    const tradeOverlay = overlay(trade, candleSec)
    const last = tradeOverlay.marks.map((mark) => mark.kind).lastIndexOf("exit")
    const pctTxt = `${(trade.close_profit ?? 0) >= 0 ? "+" : ""}${((trade.close_profit ?? 0) * 100).toFixed(1)}%`
    return tradeOverlay.marks.map((mark, index) => ({ ...mark, side: tradeOverlay.side, text: index === last ? pctTxt : mark.kind === "entry" ? mark.text : undefined }))
  })
  for (const trade of open) {
    const tradeOverlay = overlay(trade, candleSec)
    out.push(...tradeOverlay.marks.map((mark) => ({ ...mark, side: tradeOverlay.side, text: mark.kind === "entry" ? mark.text : undefined })))
  }
  return out
}

// best and worst price move while the trade was open, vs the average entry, flipped for shorts
export function excursion(trade: Trade, candles: { time: number; high: number; low: number }[]) {
  const life = candles.filter((candle) => candle.time >= openTs(trade) - 1 && candle.time <= closeTs(trade))
  if (!life.length || !trade.open_rate) return null
  const high = Math.max(...life.map((candle) => candle.high)), low = Math.min(...life.map((candle) => candle.low))
  const up = (high / trade.open_rate - 1) * 100, down = (low / trade.open_rate - 1) * 100
  const mfe = trade.is_short ? -down : up, mae = trade.is_short ? -up : down
  const lev = trade.leverage ?? 1
  return { mfe, mae, mfeLev: mfe * lev, maeLev: mae * lev }
}

export const exitGroup = (reason: string | null | undefined) => (reason ?? "").replace(/\s*\(.*$/, "").replace(/_\d+d$/, "_Nd").replace(/_\d+pct$/, "_N%")

export function duration(trade: Trade): string {
  const seconds = closeTs(trade) - openTs(trade)
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  if (seconds < 172800) return `${(seconds / 3600).toFixed(1)}h`
  return `${(seconds / 86400).toFixed(1)}d`
}

// coarser exit for charts: drops NFI's trailing codes (exit_long_rebuy_d_3_100 -> exit_long_rebuy)
export const exitFamily = (reason: string | null | undefined) => exitGroup(reason).replace(/(_(\d+|[a-z]|N%|Nd))+$/i, "")
