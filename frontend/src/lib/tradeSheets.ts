import { groupOrder, groups, type GroupBy } from "@/lib/analytics"
import { restCols, type Cell, type Col, type Sheet } from "@/lib/download"
import { closeTs, filledOrders, isEntry, openTs, type Order, type Trade } from "@/lib/trades"

// the downloadable tables: closed trades, their orders, open positions, analytics breakdowns. own columns first
// (in the order the pages show them), then every other field the bot sends
type T = Trade & { _bot?: string }
type Rate = { currency: string; rate: number } | null
// the display currency only converts usdt
const displayRate = (trades: T[], rate: Rate): Rate => (rate && trades.every((trade) => (trade.quote_currency ?? "USDT") === "USDT") ? rate : null)
const time = (ms: number | null | undefined): Cell => (ms ? new Date(ms) : null)
const side = (trade: T) => (trade.is_short ? "short" : "long")
const hours = (trade: T) => Math.round(((closeTs(trade) - openTs(trade)) / 3600) * 100) / 100
const pct = (ratio: number | null | undefined) => (ratio == null ? null : ratio * 100)
// trade fields shown by name, or as times
const SEEN = ["trade_id", "pair", "is_short", "leverage", "enter_tag", "exit_reason", "open_rate", "close_rate", "current_rate", "amount",
  "stake_amount", "close_profit_abs", "close_profit", "profit_abs", "profit_ratio", "funding_fees", "nr_of_successful_entries",
  "nr_of_successful_exits", "liquidation_price", "open_timestamp", "close_timestamp", "open_date", "close_date"]
const money = (label: string, field: (trade: T) => number | null | undefined, rate: Rate): Col<T>[] =>
  rate ? [[label, field], [`${label} (${rate.currency}, today's rate)`, (trade) => { const amount = field(trade); return amount == null ? null : amount * rate.rate }]] : [[label, field]]

export function closedSheet(trades: T[], rate: Rate): Sheet<T> {
  rate = displayRate(trades, rate)
  const cols: Col<T>[] = [
    ["bot", (trade) => trade._bot], ["trade_id", (trade) => trade.trade_id], ["pair", (trade) => trade.pair], ["side", side], ["leverage", (trade) => trade.leverage],
    ["entry tag", (trade) => trade.enter_tag], ["exit reason", (trade) => trade.exit_reason],
    ["opened", (trade) => time(trade.open_timestamp)], ["closed", (trade) => time(trade.close_timestamp)], ["held (hours)", hours],
    ["avg entry", (trade) => trade.open_rate], ["exit price", (trade) => trade.close_rate], ["amount", (trade) => trade.amount], ["stake", (trade) => trade.stake_amount],
    ...money("profit", (trade) => trade.close_profit_abs, rate), ["profit %", (trade) => pct(trade.close_profit)], ["funding", (trade) => trade.funding_fees],
    ["entries", (trade) => trade.nr_of_successful_entries], ["exits", (trade) => trade.nr_of_successful_exits],
  ]
  return { name: "trades", rows: trades, cols: [...cols, ...restCols(trades, SEEN)] }
}

export function openSheet(trades: (T & { _total?: number; _totalPct?: number; _liq?: number | null })[], rate: Rate): Sheet {
  rate = displayRate(trades, rate)
  const cols: Col<(typeof trades)[number]>[] = [
    ["bot", (trade) => trade._bot], ["trade_id", (trade) => trade.trade_id], ["pair", (trade) => trade.pair], ["side", side], ["leverage", (trade) => trade.leverage],
    ["entry tag", (trade) => trade.enter_tag], ["opened", (trade) => time(trade.open_timestamp)], ["held (hours)", hours],
    ["avg entry", (trade) => trade.open_rate], ["price", (trade) => trade.current_rate], ["amount", (trade) => trade.amount], ["stake", (trade) => trade.stake_amount],
    ["entries", (trade) => trade.nr_of_successful_entries],
    ...money("total profit", (trade) => trade._total, rate), ["total %", (trade) => trade._totalPct],
    ...money("current profit", (trade) => trade.profit_abs, rate), ["current %", (trade) => pct(trade.profit_ratio)],
    ["funding", (trade) => trade.funding_fees], ["liquidation price", (trade) => trade.liquidation_price], ["liq distance %", (trade) => trade._liq],
  ]
  return { name: "open positions", rows: trades, cols: [...cols, ...restCols(trades, SEEN)] }
}

// every filled order of the trades, oldest first per trade
export function ordersSheet(trades: T[]): Sheet {
  type O = Order & { _t: T }
  const rows: O[] = trades.flatMap((trade) => filledOrders(trade).map((order) => ({ ...order, _t: trade })))
  const seen = ["order_filled_timestamp", "price", "ft_order_side", "ft_order_tag", "order_type", "status", "safe_price", "average", "filled", "amount", "cost",
    "order_timestamp", "order_date", "order_filled_date", "pair"]
  const cols: Col<O>[] = [
    ["bot", (order) => order._t._bot], ["trade_id", (order) => order._t.trade_id], ["pair", (order) => order._t.pair],
    ["filled", (order) => time(order.order_filled_timestamp)], ["kind", (order) => (isEntry(order._t, order) ? "entry" : "exit")], ["side", (order) => order.ft_order_side],
    ["tag", (order) => order.ft_order_tag], ["type", (order) => order.order_type], ["status", (order) => order.status],
    ["price", (order) => order.safe_price ?? order.average], ["amount", (order) => order.filled ?? order.amount], ["cost", (order) => order.cost],
  ]
  return { name: "orders", rows, cols: [...cols, ...restCols(rows, seen)] }
}

// one breakdown table (analytics "by ..."), natural order or biggest total first
export function breakdownSheet(trades: T[], by: GroupBy, label: string, utc: boolean): Sheet {
  const rows = groups(trades, by, utc)
  const order = groupOrder(by)
  rows.sort(order ?? ((a, b) => b.total - a.total))
  type R = (typeof rows)[number]
  const cols: Col<R>[] = [
    [label, (row) => row.key], ["trades", (row) => row.n], ["won %", (row) => (row.n ? (row.wins / row.n) * 100 : null)],
    ["won % low (95 %)", (row) => pct(row.winCi?.[0])], ["won % high (95 %)", (row) => pct(row.winCi?.[1])],
    ["total", (row) => row.total], ["avg / trade", (row) => row.avg], ["avg low (95 %)", (row) => row.avgCi?.[0]], ["avg high (95 %)", (row) => row.avgCi?.[1]],
    ["profit factor", (row) => row.pf], ["worst", (row) => row.worst], ["best", (row) => row.best], ["avg held (hours)", (row) => row.holdH],
  ]
  return { name: `by ${label}`, rows, cols }
}
