// footprint data from /api/orderflow/bars and the reads made from it: price rows (merged to any size), POC and value
// area, diagonal imbalances, stacked imbalance zones, delta / CVD, per-bar stats. pure functions, no drawing

export type Settings = {
  ratio: number  // diagonal imbalance: one side >= ratio x the other side one row away
  minVol: number  // ... and at least this much volume (base units)
  stack: number  // this many imbalances in a row = stacked
  va: number  // value area share of the bar's volume
}
export const DEFAULTS: Settings = { ratio: 3, minVol: 0, stack: 3, va: 0.7 }

// one price row: taker buys (lifted the ask) and taker sells (hit the bid)
export type Row = { i: number; vb: number; vs: number; nb: number; ns: number }

export type Bar = {
  t: number  // seconds
  o: number; h: number; l: number; c: number
  vb: number; vs: number; nb: number; ns: number
  dmin: number; dmax: number; dh: number; dl: number; qmax: number
  rows: Row[]  // ascending price, at the stored row size
  merged: Map<string, Read>  // reads per row merge factor, made when first drawn
}

// what a bar shows at one row size
export type Read = {
  rows: Row[]
  maxVol: number; maxDelta: number; maxTrades: number
  poc: number  // row index
  vah: number; val: number
  buyImb: Set<number>; sellImb: Set<number>
  stacks: { lo: number; hi: number; side: "buy" | "sell" }[]
}

export type Cover = { start: number; end: number; source: string }
export type Big = [number, number, number, number]  // ms, price, qty, taker bought
export type Data = { step: number; bigUsd: number; bars: Bar[]; big: Big[]; cover: Cover[]; pending: boolean; exchange: string; market: string }

export function parse(json: any): Data {
  const bars: Bar[] = (json.bars ?? []).map((bar: any) => {
    const rows: Row[] = Object.entries<number[]>(bar.levels ?? {})
      .map(([index, values]) => ({ i: Number(index), vb: values[0], vs: values[1], nb: values[2], ns: values[3] }))
      .sort((left, right) => left.i - right.i)
    return { t: bar.t / 1000, o: bar.o, h: bar.h, l: bar.l, c: bar.c, vb: bar.vb, vs: bar.vs, nb: bar.nb, ns: bar.ns, dmin: bar.dmin, dmax: bar.dmax,
      dh: bar.dh, dl: bar.dl, qmax: bar.qmax, rows, merged: new Map() }
  })
  return { step: json.step ?? 0, bigUsd: json.big_usd ?? 0, bars, big: json.big ?? [], cover: json.cover ?? [], pending: !!json.pending,
    exchange: json.exchange ?? "", market: json.market ?? "" }
}

// value area: from the POC, add the bigger neighbouring row until `want` volume is inside. -> [low row, high row]
function valueArea(vol: (i: number) => number, poc: number, minI: number, maxI: number, want: number): [number, number] {
  let low = poc, high = poc, inside = vol(poc)
  while (inside < want && (low > minI || high < maxI)) {
    const up = high < maxI ? vol(high + 1) : -1, down = low > minI ? vol(low - 1) : -1
    if (up >= down) { high++; inside += up } else { low--; inside += down }
  }
  return [low, high]
}

// rows of `factor` stored rows each; row i covers prices [i * factor * step, (i + 1) * factor * step)
function mergeRows(rows: Row[], factor: number): Row[] {
  if (factor === 1) return rows
  const out: Row[] = []
  for (const row of rows) {
    const index = Math.floor(row.i / factor)
    const last = out[out.length - 1]
    if (last && last.i === index) { last.vb += row.vb; last.vs += row.vs; last.nb += row.nb; last.ns += row.ns }
    else out.push({ i: index, vb: row.vb, vs: row.vs, nb: row.nb, ns: row.ns })
  }
  return out
}

export function read(bar: Bar, factor: number, settings: Settings): Read {
  const key = `${factor}|${settings.ratio}|${settings.minVol}|${settings.stack}|${settings.va}`
  const hit = bar.merged.get(key)
  if (hit) return hit
  const rows = mergeRows(bar.rows, factor)
  let maxVol = 0, maxDelta = 0, maxTrades = 0, poc = rows[0]?.i ?? 0, pocVol = -1, total = 0
  const byI = new Map<number, Row>()
  for (const row of rows) {
    const rowVol = row.vb + row.vs
    total += rowVol
    byI.set(row.i, row)
    maxVol = Math.max(maxVol, rowVol); maxDelta = Math.max(maxDelta, Math.abs(row.vb - row.vs)); maxTrades = Math.max(maxTrades, row.nb + row.ns)
    if (rowVol > pocVol) { pocVol = rowVol; poc = row.i }
  }
  const vol = (i: number) => { const row = byI.get(i); return row ? row.vb + row.vs : 0 }
  const [low, high] = valueArea(vol, poc, rows[0]?.i ?? poc, rows[rows.length - 1]?.i ?? poc, total * settings.va)
  // diagonal imbalances: buying at a row vs selling one row lower; selling at a row vs buying one row higher
  const buyImb = new Set<number>(), sellImb = new Set<number>()
  for (const row of rows) {
    const below = byI.get(row.i - 1), above = byI.get(row.i + 1)
    if (row.vb >= settings.minVol && row.vb > 0 && row.vb >= settings.ratio * (below?.vs ?? 0) && (below?.vs ?? 0) > 0) buyImb.add(row.i)
    if (row.vs >= settings.minVol && row.vs > 0 && row.vs >= settings.ratio * (above?.vb ?? 0) && (above?.vb ?? 0) > 0) sellImb.add(row.i)
  }
  const stacks: Read["stacks"] = []
  for (const [set, side] of [[buyImb, "buy"], [sellImb, "sell"]] as const) {
    const sorted = [...set].sort((a, b) => a - b)
    let start = 0
    for (let index = 1; index <= sorted.length; index++) {
      if (index === sorted.length || sorted[index] !== sorted[index - 1] + 1) {
        if (index - start >= settings.stack) stacks.push({ lo: sorted[start], hi: sorted[index - 1], side })
        start = index
      }
    }
  }
  const out: Read = { rows, maxVol, maxDelta, maxTrades, poc, vah: high, val: low, buyImb, sellImb, stacks }
  bar.merged.set(key, out)
  return out
}

// stacked imbalance zones, carried right until price trades back through them (buy zone: a low below it; sell zone:
// a high above it). prices, not row indexes, so they survive a row size change
export type Zone = { from: number; to: number | null; lo: number; hi: number; side: "buy" | "sell" }
export function zones(bars: Bar[], factor: number, step: number, settings: Settings): Zone[] {
  const open: Zone[] = [], done: Zone[] = []
  const size = step * factor
  for (const bar of bars) {
    for (let index = open.length - 1; index >= 0; index--) {
      const zone = open[index]
      if ((zone.side === "buy" && bar.l < zone.lo) || (zone.side === "sell" && bar.h > zone.hi)) { zone.to = bar.t; done.push(zone); open.splice(index, 1) }
    }
    for (const stack of read(bar, factor, settings).stacks) open.push({ from: bar.t, to: null, lo: stack.lo * size, hi: (stack.hi + 1) * size, side: stack.side })
  }
  return [...done, ...open]
}

// cumulative delta: running, or restarting each utc day (session)
export function cvd(bars: Bar[], session: boolean): number[] {
  let run = 0, day = -1
  return bars.map((bar) => {
    const barDay = Math.floor(bar.t / 86400)
    if (session && barDay !== day) { run = 0; day = barDay }
    run += bar.vb - bar.vs
    return run
  })
}

// ===========================================================================
// PROFILES, SESSION LEVELS, VWAP, BAR MARKS
// ===========================================================================
const day = (time: number) => Math.floor(time / 86400)

// a volume profile over some bars: rows summed at `factor`, POC, value area, high / low volume nodes
export type Profile = {
  from: number | null  // first bar time (s); null = the visible range, drawn on the right edge
  to: number | null  // last bar time (s)
  size: number  // row size (price)
  rows: Row[]  // ascending price
  maxVol: number; maxDelta: number
  poc: number; vah: number; val: number  // row indexes
  hvn: number[]; lvn: number[]  // row indexes
}

export function profile(bars: Bar[], factor: number, step: number, settings: Settings, from: number | null = null, to: number | null = null): Profile | null {
  const byI = new Map<number, Row>()
  for (const bar of bars) {
    for (const row of read(bar, factor, settings).rows) {
      const existing = byI.get(row.i)
      if (existing) { existing.vb += row.vb; existing.vs += row.vs; existing.nb += row.nb; existing.ns += row.ns } else byI.set(row.i, { ...row })
    }
  }
  if (!byI.size) return null
  const rows = [...byI.values()].sort((a, b) => a.i - b.i)
  let maxVol = 0, maxDelta = 0, poc = rows[0].i, total = 0
  for (const row of rows) {
    const rowVol = row.vb + row.vs
    total += rowVol
    if (rowVol > maxVol) { maxVol = rowVol; poc = row.i }
    maxDelta = Math.max(maxDelta, Math.abs(row.vb - row.vs))
  }
  const vol = (i: number) => { const row = byI.get(i); return row ? row.vb + row.vs : 0 }
  const low = rows[0].i, high = rows[rows.length - 1].i
  const [val, vah] = valueArea(vol, poc, low, high, total * settings.va)
  return { from, to, size: step * factor, rows, maxVol, maxDelta, poc, vah, val, ...nodes(vol, low, high, poc) }
}

// one profile per utc day, each spanning its own bars
export function dayProfiles(bars: Bar[], factor: number, step: number, settings: Settings): Profile[] {
  const out: Profile[] = []
  let start = 0
  for (let end = 1; end <= bars.length; end++) {
    if (end < bars.length && day(bars[end].t) === day(bars[start].t)) continue
    const dayProfile = profile(bars.slice(start, end), factor, step, settings, bars[start].t, bars[end - 1].t)
    if (dayProfile) out.push(dayProfile)
    start = end
  }
  return out
}

// high / low volume nodes: peaks and troughs of the smoothed profile. a peak is the highest row within ~1/12 of the
// profile's height and above the average row; a trough the lowest within that span, under half the average, and
// between two peaks (a thin tail is no trough)
function nodes(vol: (i: number) => number, low: number, high: number, poc: number): { hvn: number[]; lvn: number[] } {
  const rowCount = high - low + 1
  if (rowCount < 7) return { hvn: [], lvn: [] }
  const smoothRadius = Math.max(1, Math.round(rowCount / 40)), peakRadius = Math.max(2, Math.round(rowCount / 12))
  const raw = Array.from({ length: rowCount }, (_, offset) => vol(low + offset))
  const smoothed = raw.map((_, index) => {
    let sum = 0, samples = 0
    for (let j = Math.max(0, index - smoothRadius); j <= Math.min(rowCount - 1, index + smoothRadius); j++) { sum += raw[j]; samples++ }
    return sum / samples
  })
  const mean = raw.reduce((a, b) => a + b, 0) / rowCount
  const peaks: number[] = [], troughs: number[] = []
  for (let index = 0; index < rowCount; index++) {
    let isMax = true, isMin = true
    for (let j = Math.max(0, index - peakRadius); j <= Math.min(rowCount - 1, index + peakRadius); j++) {
      if (j === index) continue
      if (smoothed[j] > smoothed[index] || (smoothed[j] === smoothed[index] && j < index)) isMax = false
      if (smoothed[j] < smoothed[index] || (smoothed[j] === smoothed[index] && j < index)) isMin = false
    }
    if (isMax && smoothed[index] >= mean) peaks.push(index)
    if (isMin && smoothed[index] <= mean * 0.5) troughs.push(index)
  }
  const first = peaks[0], last = peaks[peaks.length - 1]
  return {
    hvn: peaks.map((peak) => low + peak).filter((row) => row !== poc),
    lvn: peaks.length >= 2 ? troughs.filter((trough) => trough > first && trough < last).map((trough) => low + trough) : [],
  }
}

// per bar: the running POC, value area and VWAP with its standard deviation over the session (utc day) or from the
// first bar given (anchored). prices; lines break where `seg` changes
export type Level = { t: number; seg: number; poc: number; vah: number; val: number; vwap: number; sd: number }
export function developing(bars: Bar[], factor: number, step: number, settings: Settings, daily: boolean): Level[] {
  const size = step * factor
  const out: Level[] = []
  let byI = new Map<number, number>(), seg = Number.NaN, poc = 0, pocVol = -1, minI = 0, maxI = 0, volume = 0, priceVolume = 0, priceSqVolume = 0
  for (const bar of bars) {
    const barSeg = daily ? day(bar.t) : 0
    if (barSeg !== seg) { seg = barSeg; byI = new Map(); pocVol = -1; volume = priceVolume = priceSqVolume = 0; minI = Infinity; maxI = -Infinity }
    for (const row of read(bar, factor, settings).rows) {
      const rowVol = row.vb + row.vs, rowTotal = (byI.get(row.i) ?? 0) + rowVol
      byI.set(row.i, rowTotal)
      if (rowTotal > pocVol) { pocVol = rowTotal; poc = row.i }
      if (row.i < minI) minI = row.i
      if (row.i > maxI) maxI = row.i
      const price = (row.i + 0.5) * size
      volume += rowVol; priceVolume += rowVol * price; priceSqVolume += rowVol * price * price
    }
    if (!volume) continue
    const vwap = priceVolume / volume
    const [low, high] = valueArea((i) => byI.get(i) ?? 0, poc, minI, maxI, volume * settings.va)
    out.push({ t: bar.t, seg, poc: (poc + 0.5) * size, vah: (high + 1) * size, val: low * size, vwap, sd: Math.sqrt(Math.max(0, priceSqVolume / volume - vwap * vwap)) })
  }
  return out
}

// marks on single bars, all read from the bar's own price rows (at `factor`):
export type MarkKind = "ua-high" | "ua-low" | "exh-high" | "exh-low" | "abs-high" | "abs-low" | "div-bear" | "div-bull"
export const MARK_INFO: Record<MarkKind, string> = {
  "ua-high": "unfinished auction at the high: buyers and sellers both traded the top row; the line runs until price trades above it",
  "ua-low": "unfinished auction at the low: buyers and sellers both traded the bottom row; the line runs until price trades below it",
  "exh-high": "exhaustion at the high: buying in the top row was under 5% of the bar's average row, right above a row with at least half an average row of buying (buyers ran out)",
  "exh-low": "exhaustion at the low: selling in the bottom row was under 5% of the bar's average row, right under a row with at least half an average row of selling (sellers ran out)",
  "abs-high": "absorption at the high: 35%+ of the bar's buying hit its top fifth of rows, buyers led there, yet it closed in its lower half",
  "abs-low": "absorption at the low: 35%+ of the bar's selling hit its bottom fifth of rows, sellers led there, yet it closed in its upper half",
  "div-bear": "delta divergence: a high above the last 20 bars while cumulative delta is lower than at that earlier high",
  "div-bull": "delta divergence: a low below the last 20 bars while cumulative delta is higher than at that earlier low",
}
export type Mark = { t: number; price: number; kind: MarkKind; to?: number | null }  // to: unfinished auction filled at this bar (null = open)
export const LOOKBACK = 20

export function marks(bars: Bar[], factor: number, settings: Settings, run: number[]): Mark[] {
  const out: Mark[] = []
  bars.forEach((bar, index) => {
    const rows = read(bar, factor, settings).rows
    const rowCount = rows.length
    if (!rowCount) return
    const top = rows[rowCount - 1], bottom = rows[0]
    if (top.vb > 0 && top.vs > 0) out.push({ t: bar.t, price: bar.h, kind: "ua-high", to: bars.slice(index + 1).find((later) => later.h > bar.h)?.t ?? null })
    if (bottom.vb > 0 && bottom.vs > 0) out.push({ t: bar.t, price: bar.l, kind: "ua-low", to: bars.slice(index + 1).find((later) => later.l < bar.l)?.t ?? null })
    if (rowCount >= 5) {
      // the aggressive side only: buyers at the high, sellers at the low (about 3-13% of bars on 5m-1h)
      const avgB = bar.vb / rowCount, avgS = bar.vs / rowCount
      if (top.vb <= 0.05 * avgB && rows[rowCount - 2].vb >= 0.5 * avgB && avgB > 0) out.push({ t: bar.t, price: bar.h, kind: "exh-high" })
      if (bottom.vs <= 0.05 * avgS && rows[1].vs >= 0.5 * avgS && avgS > 0) out.push({ t: bar.t, price: bar.l, kind: "exh-low" })
    }
    if (rowCount >= 6) {
      const mid = (bar.h + bar.l) / 2
      const edge = Math.max(2, Math.ceil(rowCount / 5))
      const up = rows.slice(rowCount - edge), down = rows.slice(0, edge)
      const sum = (subset: Row[], pick: (row: Row) => number) => subset.reduce((total, row) => total + pick(row), 0)
      const upB = sum(up, (row) => row.vb), dnS = sum(down, (row) => row.vs)
      if (bar.vb > 0 && upB >= 0.35 * bar.vb && upB > sum(up, (row) => row.vs) && bar.c <= mid) out.push({ t: bar.t, price: bar.h, kind: "abs-high" })
      if (bar.vs > 0 && dnS >= 0.35 * bar.vs && dnS > sum(down, (row) => row.vb) && bar.c >= mid) out.push({ t: bar.t, price: bar.l, kind: "abs-low" })
    }
    if (index >= 5) {
      let hiK = index - 1, loK = index - 1
      for (let j = Math.max(0, index - LOOKBACK); j < index; j++) {
        if (bars[j].h > bars[hiK].h) hiK = j
        if (bars[j].l < bars[loK].l) loK = j
      }
      if (bar.h > bars[hiK].h && run[index] < run[hiK]) out.push({ t: bar.t, price: bar.h, kind: "div-bear" })
      if (bar.l < bars[loK].l && run[index] > run[loK]) out.push({ t: bar.t, price: bar.l, kind: "div-bull" })
    }
  })
  return out
}

// the bar stats table
export function stats(bar: Bar, reading: Read, size: number, big: Big[], tfSec: number) {
  const vol = bar.vb + bar.vs, delta = bar.vb - bar.vs, trades = bar.nb + bar.ns
  const inBar = big.filter((trade) => trade[0] / 1000 >= bar.t && trade[0] / 1000 < bar.t + tfSec)
  const bigVol = inBar.reduce((sum, trade) => sum + trade[2], 0)
  return {
    volume: vol, delta, deltaPct: vol ? (delta / vol) * 100 : 0,
    dmin: bar.dmin, dmax: bar.dmax, dh: bar.dh, dl: bar.dl,
    buys: bar.nb, sells: bar.ns, trades, avgSize: trades ? vol / trades : 0, maxSize: bar.qmax,
    poc: (reading.poc + 0.5) * size, vah: (reading.vah + 1) * size, val: reading.val * size,
    buyImb: reading.buyImb.size, sellImb: reading.sellImb.size, stacks: reading.stacks.length,
    bigCount: inBar.length, bigShare: vol ? (bigVol / vol) * 100 : 0,
  }
}

// row merge for "auto": the smallest nice factor that gives rows at least `px` tall
const FACTORS = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000]
export function autoFactor(rowPx: number, px: number): number {
  for (const factor of FACTORS) if (rowPx * factor >= px) return factor
  return FACTORS[FACTORS.length - 1]
}

// short volume numbers for cells: 1.2k, 34, 5.6, 0.52, 0.012
export function short(value: number): string {
  const magnitude = Math.abs(value)
  if (magnitude >= 1e9) return (value / 1e9).toFixed(1) + "B"
  if (magnitude >= 1e6) return (value / 1e6).toFixed(1) + "M"
  if (magnitude >= 1e4) return (value / 1e3).toFixed(0) + "k"
  if (magnitude >= 1e3) return (value / 1e3).toFixed(1) + "k"
  if (magnitude >= 100) return value.toFixed(0)
  if (magnitude >= 10) return value.toFixed(1).replace(/\.0$/, "")
  if (magnitude >= 1) return value.toFixed(2).replace(/0$/, "").replace(/\.0?$/, "")
  if (magnitude === 0) return "0"
  return value.toPrecision(2)
}

// ===========================================================================
// ORDER BOOK (/api/orderflow/heat)
// ===========================================================================
export const BANDS = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05]  // imbalance distances from the mid (backend book.BANDS)

export type HeatCol = { t: number; span: number; lo: number; b: number[]; a: number[] }  // t, span in s; rows from lo
export type WallEvent = [number, number, number, number, string]  // ms, price, amount, 1 bid / 0 ask, appear|pulled|filled
export type Heat = {
  step: number  // row size of the columns
  cols: HeatCol[]
  scale: number  // 99.5th percentile of the sizes: full brightness
  imb: { t: number; v: (number | null)[] }[]  // per bar: [bid, ask] value per band
  events: WallEvent[]
  wallUsd: number
}

export function parseHeat(json: any): Heat {
  const cols: HeatCol[] = (json.cols ?? []).map((column: any) => ({ t: column.t / 1000, span: column.span / 1000, lo: column.lo, b: column.b, a: column.a }))
  const sizes: number[] = []
  for (const column of cols) for (const size of [...column.b, ...column.a]) if (size > 0) sizes.push(size)
  sizes.sort((left, right) => left - right)
  return {
    step: json.step ?? 0, cols, scale: sizes[Math.floor(sizes.length * 0.995)] ?? 1,
    imb: (json.imb ?? []).map((entry: any) => ({ t: entry.t / 1000, v: entry.v })), events: json.events ?? [], wallUsd: json.wall_usd ?? 0,
  }
}

// bid share of the value within a band, -1 (all asks) .. +1 (all bids)
export function imbalance(values: (number | null)[], band: number): number | null {
  const bid = values[2 * band], ask = values[2 * band + 1]
  return bid == null || ask == null || bid + ask <= 0 ? null : (bid - ask) / (bid + ask)
}


// ===========================================================================
// OPEN INTEREST, LIQUIDATIONS, FUNDING (/api/orderflow/derivs; perpetuals)
// ===========================================================================
export type Derivs = {
  oi: Map<number, number>  // bar time (s) -> open interest at the bar's end (base units)
  liq: Map<number, { long: number; short: number; n: number }>  // value of longs / shorts liquidated in the bar
  funding: [number, number][]  // settled rates (s, rate per period), oldest first
}

export function parseDerivs(json: any): Derivs {
  return {
    oi: new Map((json.oi ?? []).map(([time, value]: number[]) => [time / 1000, value])),
    liq: new Map((json.liq ?? []).map(([time, long, short, count]: number[]) => [time / 1000, { long, short, n: count }])),
    funding: (json.funding ?? []).map(([time, rate]: number[]) => [time / 1000, rate]),
  }
}

// the open interest change of a bar read with its price move: who is opening or closing
export type OiWho = "longs opening" | "shorts opening" | "shorts closing" | "longs closing"
export type OiRead = { oi: number; delta: number | null; who: OiWho | null }
export function oiReads(bars: Bar[], oi: Map<number, number>): Map<number, OiRead> {
  const out = new Map<number, OiRead>()
  let prev: number | null = null
  for (const bar of bars) {
    const value = oi.get(bar.t)
    if (value == null) continue
    const delta = prev == null ? null : value - prev, up = bar.c >= bar.o
    const who: OiWho | null = delta == null ? null : delta >= 0 ? (up ? "longs opening" : "shorts opening") : (up ? "shorts closing" : "longs closing")
    out.set(bar.t, { oi: value, delta, who })
    prev = value
  }
  return out
}

// the last settled funding rate at or before t (s)
export function fundingAt(funding: [number, number][], time: number): number | null {
  let latest: number | null = null
  for (const [settledAt, rate] of funding) { if (settledAt > time) break; latest = rate }
  return latest
}
