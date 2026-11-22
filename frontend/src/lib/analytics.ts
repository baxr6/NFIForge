import { wilson } from "@/lib/format"
import { closeTs, exitFamily, exitGroup, openTs, type Trade } from "@/lib/trades"

// stats over closed trades for the Analytics page; pure functions, times bucketed in utc or local time

const pnl = (trade: Trade) => trade.close_profit_abs ?? 0

// ===========================================================================
// SUMMARY
// ===========================================================================
export type Stats = {
  n: number; wins: number; total: number; avg: number
  avgCi: [number, number] | null; winCi: [number, number] | null
  pf: number | null; worst: number; best: number; holdH: number
}

export function stats(trades: Trade[]): Stats {
  const count = trades.length
  const profits = trades.map(pnl)
  const wins = profits.filter((profit) => profit > 0).length
  const total = profits.reduce((sum, profit) => sum + profit, 0)
  const avg = count ? total / count : 0
  // 95 % range for the average trade (normal approx, needs a few trades to mean anything)
  const stdDev = count > 1 ? Math.sqrt(profits.reduce((sum, profit) => sum + (profit - avg) ** 2, 0) / (count - 1)) : 0
  const half = count > 1 ? (1.96 * stdDev) / Math.sqrt(count) : 0
  const gain = profits.filter((profit) => profit > 0).reduce((sum, profit) => sum + profit, 0)
  const loss = -profits.filter((profit) => profit < 0).reduce((sum, profit) => sum + profit, 0)
  return {
    n: count, wins, total, avg,
    avgCi: count > 1 ? [avg - half, avg + half] : null,
    winCi: wilson(wins, count),
    pf: loss > 0 ? gain / loss : null,
    worst: count ? Math.min(...profits) : 0,
    best: count ? Math.max(...profits) : 0,
    holdH: count ? trades.reduce((sum, trade) => sum + (closeTs(trade) - openTs(trade)), 0) / count / 3600 : 0,
  }
}

// realised equity (sum of closed P&L) and how far it sits below its own high, one point per close. with the account
// size at the start (base) the drawdown is also given as % of the account at its high
export function curve(trades: Trade[], base = 0) {
  const byTime = new Map<number, number>()
  for (const trade of trades) {
    const closedAt = Math.floor(closeTs(trade))
    byTime.set(closedAt, (byTime.get(closedAt) ?? 0) + pnl(trade))
  }
  const eq: { time: number; value: number }[] = []
  const dd: { time: number; value: number }[] = []
  const ddPct: { time: number; value: number }[] = []
  let run = 0, peak = 0, maxDd = 0, maxDdPct = 0, deepAt = 0, peakAt = 0, longest = 0, longFrom = 0, longTo = 0
  for (const [time, profit] of [...byTime].sort((a, b) => a[0] - b[0])) {
    if (!peakAt) peakAt = time
    run += profit
    if (run >= peak) {
      // back at (or above) the high: the time under water ends here
      if (time - peakAt > longest && peak > run - profit) { longest = time - peakAt; longFrom = peakAt; longTo = time }
      peak = run
      peakAt = time
    }
    eq.push({ time, value: +run.toFixed(4) })
    dd.push({ time, value: +(run - peak).toFixed(4) })
    const pct = base + peak > 0 ? ((run - peak) / (base + peak)) * 100 : 0
    ddPct.push({ time, value: +pct.toFixed(3) })
    if (run - peak < maxDd) { maxDd = run - peak; deepAt = time }
    maxDdPct = Math.min(maxDdPct, pct)
  }
  // still under water now
  const now = Date.now() / 1000
  const under = run < peak ? now - peakAt : 0
  if (under > longest) { longest = under; longFrom = peakAt; longTo = 0 }
  return { eq, dd, ddPct, maxDd, maxDdPct, deepAt, under, longest, longFrom, longTo, now: run - peak }
}

// ===========================================================================
// TIME BUCKETS
// ===========================================================================
const pad = (value: number) => String(value).padStart(2, "0")

function parts(ms: number, utc: boolean) {
  const date = new Date(ms)
  return utc
    ? { y: date.getUTCFullYear(), m: date.getUTCMonth(), d: date.getUTCDate(), wd: date.getUTCDay(), h: date.getUTCHours() }
    : { y: date.getFullYear(), m: date.getMonth(), d: date.getDate(), wd: date.getDay(), h: date.getHours() }
}

export const dayKey = (ms: number, utc: boolean) => { const date = parts(ms, utc); return `${date.y}-${pad(date.m + 1)}-${pad(date.d)}` }

// weeks start monday, labelled by that monday
function weekKey(ms: number, utc: boolean) {
  const date = parts(ms, utc)
  const back = (date.wd + 6) % 7
  const mon = new Date(Date.UTC(date.y, date.m, date.d - back))
  return `${mon.getUTCFullYear()}-${pad(mon.getUTCMonth() + 1)}-${pad(mon.getUTCDate())}`
}

export type Period = "day" | "week" | "month"

export function byPeriod(trades: Trade[], period: Period, utc: boolean) {
  const key = (ms: number) => (period === "day" ? dayKey(ms, utc) : period === "week" ? weekKey(ms, utc) : dayKey(ms, utc).slice(0, 7))
  const buckets = new Map<string, { total: number; n: number }>()
  for (const trade of trades) {
    const bucketKey = key(trade.close_timestamp)
    const bucket = buckets.get(bucketKey) ?? { total: 0, n: 0 }
    bucket.total += pnl(trade); bucket.n++
    buckets.set(bucketKey, bucket)
  }
  return [...buckets].sort((a, b) => a[0].localeCompare(b[0])).map(([periodKey, bucket]) => ({ key: periodKey, ...bucket }))
}

// ===========================================================================
// GROUPS
// ===========================================================================
export type GroupBy = "tag" | "exit" | "exitDetail" | "pair" | "side" | "weekday" | "hour" | "hold"

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

// hold-time buckets, also used by the histogram
export const HOLDS: [number, string][] = [[1, "< 1h"], [4, "1–4h"], [12, "4–12h"], [24, "12–24h"], [72, "1–3d"], [168, "3–7d"], [720, "7–30d"], [Infinity, "30d +"]]
export const holdBucket = (trade: Trade) => HOLDS.find(([hours]) => (closeTs(trade) - openTs(trade)) / 3600 < hours)![1]

export function groupKey(trade: Trade, by: GroupBy, utc: boolean): string {
  switch (by) {
    case "tag": return (trade.enter_tag ?? "").trim() || "(none)"
    case "exit": return exitFamily(trade.exit_reason) || "(none)"
    case "exitDetail": return exitGroup(trade.exit_reason) || "(none)"
    case "pair": return trade.pair.split("/")[0]
    case "side": return trade.is_short ? "short" : "long"
    case "weekday": return DAYS[parts(trade.open_timestamp, utc).wd]
    case "hour": return `${pad(parts(trade.open_timestamp, utc).h)}:00`
    case "hold": return holdBucket(trade)
  }
}

export function groups(trades: Trade[], by: GroupBy, utc: boolean) {
  const byKey = new Map<string, Trade[]>()
  for (const trade of trades) {
    const key = groupKey(trade, by, utc)
    const group = byKey.get(key)
    if (group) group.push(trade)
    else byKey.set(key, [trade])
  }
  return [...byKey].map(([key, members]) => ({ key, ...stats(members) }))
}

// natural order for groups that have one (days, hours, hold buckets), else biggest total first
export function groupOrder(by: GroupBy): ((a: { key: string }, b: { key: string }) => number) | null {
  if (by === "weekday") return (left, right) => ((DAYS.indexOf(left.key) + 6) % 7) - ((DAYS.indexOf(right.key) + 6) % 7)
  if (by === "hour") return (a, b) => a.key.localeCompare(b.key)
  if (by === "hold") return (left, right) => HOLDS.findIndex(([, label]) => label === left.key) - HOLDS.findIndex(([, label]) => label === right.key)
  return null
}
