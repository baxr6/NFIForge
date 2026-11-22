import { filledOrders, isEntry, type Order, type Trade } from "@/lib/trades"

// ===========================================================================
// SHOCK: what the open book does if every coin moves m (0.1 = +10 %) from here. a trade that crosses its
// liquidation price loses all the margin left in it; fees and funding left out
// ===========================================================================
export function shock(open: Trade[], move: number) {
  let change = 0
  const liquidated: string[] = []
  for (const trade of open) {
    const price = trade.current_rate, amount = trade.amount
    if (!price || !amount) continue
    const dir = trade.is_short ? -1 : 1
    const shockedPrice = price * (1 + move)
    const liq = trade.liquidation_price
    if (liq && (dir > 0 ? shockedPrice <= liq : shockedPrice >= liq)) {
      change -= (trade.stake_amount ?? 0) + (trade.profit_abs ?? 0)
      liquidated.push(trade.pair.split("/")[0])
    } else change += dir * amount * (shockedPrice - price)
  }
  return { change, liquidated }
}

// ===========================================================================
// LADDER: a trade's filled orders grouped by the level they belong to (nfi grind tags, manual adds), with the
// margin put in and taken out at each
// ===========================================================================
export type Level = { level: string; buys: number; marginIn: number; sells: number; marginOut: number }

function levelOf(order: Order, entry: boolean, first: boolean): string {
  if (first) return "first entry"
  // nfi exit tags carry extra numbers after the tag ("grind_2_exit 53")
  const tag = String(order.ft_order_tag ?? "").trim().split(/\s+/)[0]
  const grind = /^grind_(\d+)_(entry|exit)$/.exec(tag)
  if (grind) return `grind ${grind[1]}`
  const derisk = /^derisk_level_(\d+)$/.exec(tag)
  if (derisk) return `derisk ${derisk[1]}`
  if (tag === "buyback_1_entry" || tag === "buyback_1_exit") return "buyback"
  if (tag === "rebuy_entry") return "rebuy"
  if (tag === "force_entry") return "manual add"
  if (tag === "force_exit") return "manual exit"
  return entry ? "add" : tag ? `exit ${tag}` : "partial exit"
}

export function ladder(trade: Trade): Level[] {
  const lev = trade.leverage || 1
  const out = new Map<string, Level>()
  const orders = filledOrders(trade)
  orders.forEach((order, index) => {
    const entry = isEntry(trade, order)
    // the closing order of a closed trade isn't a level
    if (!entry && !trade.is_open && index === orders.length - 1) return
    const name = levelOf(order, entry, index === 0)
    const level = out.get(name) ?? { level: name, buys: 0, marginIn: 0, sells: 0, marginOut: 0 }
    const margin = ((order.filled ?? order.amount ?? 0) * (order.safe_price ?? 0)) / lev
    if (entry) { level.buys++; level.marginIn += margin } else { level.sells++; level.marginOut += margin }
    out.set(name, level)
  })
  return [...out.values()]
}

// short form for a table cell: "g1×2 · g3 · bb"
const SHORT: Record<string, string> = { buyback: "bb", rebuy: "rebuy", "manual add": "man", add: "add" }
export function ladderShort(trade: Trade): string {
  return ladder(trade)
    .filter((level) => level.buys && level.level !== "first entry")
    .map((level) => `${level.level.startsWith("grind ") ? `g${level.level.slice(6)}` : SHORT[level.level] ?? level.level}${level.buys > 1 ? `×${level.buys}` : ""}`)
    .join(" · ")
}
