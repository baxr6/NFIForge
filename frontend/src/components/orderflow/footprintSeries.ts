import {
  customSeriesDefaultOptions, type CustomData, type CustomSeriesOptions, type ICustomSeriesPaneRenderer,
  type ICustomSeriesPaneView, type PaneRendererCustomData, type PriceToCoordinateConverter, type Time, type WhitespaceData,
} from "lightweight-charts"
import type { CanvasRenderingTarget2D } from "fancy-canvas"
import { autoFactor, read, short, type Bar, type Big, type Heat, type Level, type Mark, type Profile, type Settings, type WallEvent, type Zone } from "@/lib/orderflow"

// the footprint as a lightweight-charts custom series: per bar a column of price rows drawn in one of five styles,
// with a thin candle on its left, POC box, value area bracket, imbalance colours and stacked imbalance zones.
// zoomed out it falls back to coloured rows without numbers, then to plain candles

export type CellStyle = "bidask" | "delta" | "volume" | "trades" | "profile"
export type FootprintItem = CustomData<Time> & { bar: Bar }

export interface FootprintOptions extends CustomSeriesOptions {
  cellStyle: CellStyle
  rows: number  // row merge factor, 0 = auto
  step: number
  settings: Settings
  showPoc: boolean
  showVa: boolean
  tfSec: number
  contrast: number
  heatLog: boolean  // heatmap brightness by log(size) instead of size
  heatMax: number  // size at full brightness; 0 = auto (the 99.5th percentile on screen)
  wallUsd: number
  rev: number  // bumped when the extras below change (they are big: kept out of the options, which get deep-merged)
  colors: { up: string; down: string; text: string; dim: string; poc: string; va: string; cell: string; gap: string }
}

const font = (px: number, bold = false) => `${bold ? "600 " : ""}${px}px 'IBM Plex Mono', monospace`
const FONT = font(11)
const FONT_B = font(11, true)

function rgba(hex: string, alpha: number): string {
  const digits = hex.replace("#", "")
  const rgb = Number.parseInt(digits.length === 3 ? digits.split("").map((char) => char + char).join("") : digits.slice(0, 6), 16)
  return `rgba(${(rgb >> 16) & 255},${(rgb >> 8) & 255},${rgb & 255},${Math.max(0, Math.min(1, alpha)).toFixed(3)})`
}

// 0..1 -> heat colour: transparent dark blue, blue, cyan, yellow, white
const STOPS: [number, number, number, number][] = [[0, 10, 30, 90], [0.3, 22, 80, 200], [0.6, 22, 200, 214], [0.85, 245, 209, 66], [1, 255, 255, 255]]
function ramp(strength: number): string {
  let index = 1
  while (index < STOPS.length - 1 && STOPS[index][0] < strength) index++
  const [fromAt, fromRed, fromGreen, fromBlue] = STOPS[index - 1], [toAt, toRed, toGreen, toBlue] = STOPS[index]
  const mix = Math.max(0, Math.min(1, (strength - fromAt) / (toAt - fromAt)))
  const alpha = 0.12 + 0.6 * strength
  return `rgba(${Math.round(fromRed + (toRed - fromRed) * mix)},${Math.round(fromGreen + (toGreen - fromGreen) * mix)},${Math.round(fromBlue + (toBlue - fromBlue) * mix)},${alpha.toFixed(2)})`
}

// drawn with the bars but too big for series options
export type Extras = {
  zones: Zone[]
  gaps: number[]  // bar times (s) that come straight after missing data
  heat: Heat | null  // the order book behind the bars
  events: WallEvent[]  // large orders: appeared / pulled / filled
  profiles: Profile[]  // volume profiles: over their own bars, or (from null) the visible range on the right edge
  split: "bidask" | "delta"  // profile rows: sells | buys, or delta
  levels: Level[]  // session (utc day) running values per bar
  dev: boolean  // ... draw its POC and value area
  vwap: boolean  // ... draw its VWAP
  bands: number  // standard deviation bands around each VWAP: 0, 1 or 2
  anchored: Level[]  // VWAP from a picked bar
  marks: Mark[]
  cot: boolean  // running delta at the bar's high / low, above / below it
  big: Big[]  // big trades as bubbles
  bigUsd: number  // bubble size scale
}
// the step 3 layers, passed to the chart as one prop
export type Overlays = Omit<Extras, "zones" | "gaps" | "heat" | "events">
export const NO_EXTRAS: Extras = {
  zones: [], gaps: [], heat: null, events: [], profiles: [], split: "bidask", levels: [], dev: false, vwap: false, bands: 0,
  anchored: [], marks: [], cot: false, big: [], bigUsd: 0,
}

class Renderer implements ICustomSeriesPaneRenderer {
  data: PaneRendererCustomData<Time, FootprintItem> | null = null
  opts: FootprintOptions | null = null
  extras: Extras = NO_EXTRAS

  draw(target: CanvasRenderingTarget2D, priceToY: PriceToCoordinateConverter): void {
    target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => this.paint(ctx, priceToY, mediaSize.width))
  }

  private paint(ctx: CanvasRenderingContext2D, priceToY: PriceToCoordinateConverter, width: number): void {
    const data = this.data, opts = this.opts, extras = this.extras
    if (!data || !opts || !data.visibleRange || !opts.step) return
    const spacing = data.barSpacing * (data.conflationFactor || 1)
    const barWidth = Math.max(1, spacing * 0.92)
    const yAt = (price: number) => priceToY(price) as number
    const first = data.bars[data.visibleRange.from]?.originalData.bar
    if (!first) return
    // row height in px at the visible price (a log scale changes it a little along the axis; the first bar decides)
    const rowPx = Math.abs(yAt(first.c) - yAt(first.c + opts.step))
    const text = barWidth >= 46
    const factor = opts.rows || autoFactor(rowPx, text ? 13 : 2.5)
    const size = opts.step * factor
    const showText = text && rowPx * factor >= 11
    const cells = barWidth >= 5 && rowPx * factor >= 1.2
    const colors = opts.colors
    // bar time -> x, for things that sit inside a bar (heatmap columns, order events)
    const bars = data.bars
    const xAt = (time: number): number | null => {
      let low = 0, high = bars.length - 1
      if (high < 0 || time < bars[0].originalData.bar.t) return null
      while (low < high) { const mid = (low + high + 1) >> 1; if (bars[mid].originalData.bar.t <= time) low = mid; else high = mid - 1 }
      const found = bars[low], foundTime = found.originalData.bar.t
      if (time >= foundTime + opts.tfSec) return null  // in a hole between bars
      return found.x - spacing / 2 + ((time - foundTime) / opts.tfSec) * spacing
    }
    if (extras.heat) this.heat(ctx, yAt, extras.heat, xAt, spacing / opts.tfSec, opts, width)
    // bar time -> centre x, for things that span bars
    const centres = new Map<number, number>()
    for (const item of data.bars) centres.set(item.originalData.bar.t, item.x)

    // stacked imbalance zones behind everything
    if (extras.zones.length) {
      for (const zone of extras.zones) {
        const x0 = centres.get(zone.from), x1 = zone.to == null ? width : centres.get(zone.to)
        if (x0 == null || x1 == null || x1 < 0 || x0 > width) continue
        const top = yAt(zone.hi), bottom = yAt(zone.lo)
        ctx.fillStyle = rgba(zone.side === "buy" ? colors.up : colors.down, zone.to == null ? 0.13 : 0.06)
        ctx.fillRect(x0 - barWidth / 2, top, x1 - x0 + barWidth / 2, bottom - top)
      }
    }

    // missing data: a dashed line before the first bar after a gap
    if (extras.gaps.length) {
      const gaps = new Set(extras.gaps)
      ctx.save()
      ctx.setLineDash([3, 4])
      ctx.strokeStyle = colors.gap
      ctx.fillStyle = colors.gap
      ctx.font = FONT
      for (let index = data.visibleRange.from; index < data.visibleRange.to; index++) {
        const item = data.bars[index]
        if (!item || !gaps.has(item.originalData.bar.t)) continue
        const gapX = Math.round(item.x - spacing / 2) + 0.5
        ctx.beginPath(); ctx.moveTo(gapX, 0); ctx.lineTo(gapX, 4000); ctx.stroke()
        ctx.fillText("no data", gapX + 3, 12)
      }
      ctx.restore()
    }

    for (const profile of extras.profiles) if (profile.from != null) this.profile(ctx, yAt, profile, extras.split, (centres.get(profile.from) ?? -1e9) - spacing / 2, (centres.get(profile.to ?? profile.from) ?? -1e9) + spacing / 2, false, colors)
    if (extras.levels.length) {
      if (extras.dev) {
        this.line(ctx, yAt, centres, spacing, extras.levels, (level) => level.poc, colors.poc, [4, 3])
        this.line(ctx, yAt, centres, spacing, extras.levels, (level) => level.vah, colors.va, [2, 3])
        this.line(ctx, yAt, centres, spacing, extras.levels, (level) => level.val, colors.va, [2, 3])
      }
      if (extras.vwap) this.vwap(ctx, yAt, centres, spacing, extras.levels, extras.bands, colors.cell)
    }
    if (extras.anchored.length) this.vwap(ctx, yAt, centres, spacing, extras.anchored, extras.bands, colors.text)
    const marksAt = new Map<number, Mark[]>()
    for (const mark of extras.marks) {
      const atBar = marksAt.get(mark.t)
      if (atBar) atBar.push(mark); else marksAt.set(mark.t, [mark])
      if (mark.kind === "ua-high" || mark.kind === "ua-low") {
        // the unfinished level runs right until price trades through it
        const x0 = centres.get(mark.t), x1 = mark.to == null ? width : centres.get(mark.to)
        if (x0 == null || x1 == null || x1 < 0 || x0 > width) continue
        ctx.save(); ctx.setLineDash([2, 3]); ctx.strokeStyle = rgba(colors.poc, mark.to == null ? 0.8 : 0.35); ctx.lineWidth = 1
        const lineY = Math.round(yAt(mark.price)) + 0.5
        ctx.beginPath(); ctx.moveTo(x0, lineY); ctx.lineTo(x1, lineY); ctx.stroke(); ctx.restore()
      }
    }

    for (let index = data.visibleRange.from; index < data.visibleRange.to; index++) {
      const item = data.bars[index]
      if (!item) continue
      const bar = item.originalData.bar
      const left = item.x - barWidth / 2
      // marks start outside the bar's rows (and under its delta / volume numbers)
      const yHigh = cells ? yAt((Math.floor(bar.h / size) + 1) * size) - 4 : yAt(bar.h) - 5
      const yLow = cells ? yAt(Math.floor(bar.l / size) * size) + (showText ? 30 : 4) : yAt(bar.l) + 4
      this.ends(ctx, bar, item.x, marksAt.get(bar.t) ?? [], extras.cot && showText, yHigh, yLow, colors)
      const up = bar.c >= bar.o
      if (!cells) {
        this.candle(ctx, yAt, bar, item.x, Math.max(1, barWidth * 0.7), up ? colors.up : colors.down)
        continue
      }
      const reading = read(bar, factor, opts.settings)
      const candleWidth = Math.max(2, Math.min(6, barWidth * 0.08))  // the thin candle on the left
      this.candle(ctx, yAt, bar, left + candleWidth / 2, candleWidth, up ? colors.up : colors.down)
      const x0 = left + candleWidth + 2, x1 = left + barWidth, cellW = x1 - x0
      if (cellW < 2) continue
      const fontPx = showText ? this.fit(ctx, opts.cellStyle, reading, cellW) : 0
      ctx.save()
      ctx.beginPath(); ctx.rect(x0, 0, cellW, 100000); ctx.clip()
      for (const row of reading.rows) {
        const top = yAt((row.i + 1) * size), bottom = yAt(row.i * size)
        const height = Math.max(1, bottom - top - (showText ? 1 : 0))
        this.cell(ctx, opts.cellStyle, row, reading, x0, top, cellW, height, fontPx, colors)
      }
      ctx.restore()
      if (opts.showVa) {
        ctx.fillStyle = rgba(colors.va, 0.85)
        const top = yAt((reading.vah + 1) * size), bottom = yAt(reading.val * size)
        ctx.fillRect(x1 - 2, top, 2, bottom - top)
      }
      if (opts.showPoc) {
        ctx.strokeStyle = colors.poc
        ctx.lineWidth = 1.5
        const top = yAt((reading.poc + 1) * size), bottom = yAt(reading.poc * size)
        ctx.strokeRect(x0 + 0.75, top + 0.75, cellW - 1.5, Math.max(1, bottom - top - 1.5))
      }
      if (showText) {
        // under the bar: delta and volume
        const delta = bar.vb - bar.vs
        const textY = yAt(Math.floor(bar.l / size) * size) + 13
        ctx.font = FONT_B
        ctx.textAlign = "center"
        ctx.fillStyle = delta >= 0 ? colors.up : colors.down
        ctx.fillText(`${delta >= 0 ? "+" : ""}${short(delta)}`, x0 + cellW / 2, textY)
        ctx.font = FONT
        ctx.fillStyle = colors.dim
        ctx.fillText(short(bar.vb + bar.vs), x0 + cellW / 2, textY + 13)
      }
    }
    for (const profile of extras.profiles) if (profile.from == null) this.profile(ctx, yAt, profile, extras.split, width - Math.min(160, width * 0.22), width, true, colors)
    if (extras.big.length) this.bubbles(ctx, yAt, extras.big, xAt, extras.bigUsd, width, colors)
    if (extras.events.length) this.walls(ctx, yAt, extras.events, xAt, opts.wallUsd, colors)
  }

  // a volume profile between x0 and x1: rows grow from x0 (from x1 leftwards on the right edge), POC row in amber,
  // value area edges, high volume nodes solid and low volume nodes dashed across it
  private profile(ctx: CanvasRenderingContext2D, yAt: (price: number) => number, profile: Profile, split: Extras["split"], x0: number, x1: number,
    right: boolean, colors: FootprintOptions["colors"]) {
    const span = x1 - x0
    if (span < 4 || x1 < 0) return
    const len = span * (right ? 1 : 0.85)
    const startX = (length: number) => (right ? x1 - length : x0)
    ctx.save()
    for (const row of profile.rows) {
      const top = yAt((row.i + 1) * profile.size), height = Math.max(1, yAt(row.i * profile.size) - top - (yAt(row.i * profile.size) - top > 3 ? 1 : 0))
      const poc = row.i === profile.poc, inVa = row.i >= profile.val && row.i <= profile.vah, alpha = inVa ? 0.42 : 0.24
      if (split === "delta") {
        const barLength = ((row.vb - row.vs) / (profile.maxDelta || 1)) * len, absLength = Math.abs(barLength)
        ctx.fillStyle = poc ? rgba(colors.poc, 0.7) : rgba(barLength >= 0 ? colors.up : colors.down, alpha)
        ctx.fillRect(startX(absLength), top, absLength, height)
      } else {
        const sellLength = (row.vs / (profile.maxVol || 1)) * len, buyLength = (row.vb / (profile.maxVol || 1)) * len
        if (poc) { ctx.fillStyle = rgba(colors.poc, 0.7); ctx.fillRect(startX(sellLength + buyLength), top, sellLength + buyLength, height); continue }
        ctx.fillStyle = rgba(colors.down, alpha); ctx.fillRect(right ? x1 - sellLength - buyLength : x0, top, sellLength, height)
        ctx.fillStyle = rgba(colors.up, alpha); ctx.fillRect(right ? x1 - buyLength : x0 + sellLength, top, buyLength, height)
      }
    }
    const across = (price: number, color: string, dash: number[]) => {
      const lineY = Math.round(yAt(price)) + 0.5
      ctx.setLineDash(dash); ctx.strokeStyle = color
      ctx.beginPath(); ctx.moveTo(right ? x1 - len : x0, lineY); ctx.lineTo(right ? x1 : x0 + len, lineY); ctx.stroke()
    }
    ctx.lineWidth = 1
    across((profile.vah + 1) * profile.size, rgba(colors.va, 0.9), [])
    across(profile.val * profile.size, rgba(colors.va, 0.9), [])
    for (const node of profile.hvn) across((node + 0.5) * profile.size, rgba(colors.text, 0.45), [])
    for (const node of profile.lvn) across((node + 0.5) * profile.size, rgba(colors.dim, 0.7), [3, 3])
    ctx.restore()
  }

  // a running value as a step line through the bars; a new segment (session) starts a new line
  private line(ctx: CanvasRenderingContext2D, yAt: (price: number) => number, centres: Map<number, number>, spacing: number, levels: Level[],
    pick: (level: Level) => number, color: string, dash: number[], width = 1) {
    ctx.save()
    ctx.setLineDash(dash); ctx.strokeStyle = color; ctx.lineWidth = width
    ctx.beginPath()
    let seg = Number.NaN
    for (const level of levels) {
      const centre = centres.get(level.t)
      if (centre == null) continue
      const lineY = yAt(pick(level))
      if (level.seg !== seg) { ctx.moveTo(centre - spacing / 2, lineY); seg = level.seg } else ctx.lineTo(centre - spacing / 2, lineY)
      ctx.lineTo(centre + spacing / 2, lineY)
    }
    ctx.stroke()
    ctx.restore()
  }

  private vwap(ctx: CanvasRenderingContext2D, yAt: (price: number) => number, centres: Map<number, number>, spacing: number, levels: Level[],
    bands: number, color: string) {
    for (let band = 1; band <= bands; band++) {
      this.line(ctx, yAt, centres, spacing, levels, (level) => level.vwap + band * level.sd, rgba(color, 0.55), [5, 4])
      this.line(ctx, yAt, centres, spacing, levels, (level) => level.vwap - band * level.sd, rgba(color, 0.55), [5, 4])
    }
    this.line(ctx, yAt, centres, spacing, levels, (level) => level.vwap, color, [], 1.5)
  }

  // above the high / below the low: running delta at that moment (COT), then the bar's marks
  private ends(ctx: CanvasRenderingContext2D, bar: Bar, centre: number, marks: Mark[], cot: boolean, yHigh: number, yLow: number,
    colors: FootprintOptions["colors"]) {
    let yHi = yHigh, yLo = yLow
    ctx.save()
    ctx.textAlign = "center"
    if (cot) {
      ctx.font = FONT
      ctx.fillStyle = bar.dh >= 0 ? colors.up : colors.down; ctx.fillText(`${bar.dh >= 0 ? "+" : ""}${short(bar.dh)}`, centre, yHi); yHi -= 13
      ctx.fillStyle = bar.dl >= 0 ? colors.up : colors.down; ctx.fillText(`${bar.dl >= 0 ? "+" : ""}${short(bar.dl)}`, centre, yLo + 9); yLo += 13
    }
    for (const mark of marks) {
      const high = mark.kind.endsWith("high") || mark.kind === "div-bear"
      const markY = high ? yHi - 4 : yLo + 4
      if (high) yHi -= 10; else yLo += 10
      const radius = 3.5
      ctx.beginPath()
      if (mark.kind.startsWith("ua")) { ctx.strokeStyle = colors.poc; ctx.lineWidth = 1.5; ctx.arc(centre, markY, radius, 0, 2 * Math.PI); ctx.stroke(); continue }
      if (mark.kind.startsWith("exh")) {  // triangle pointing back into the bar
        ctx.fillStyle = colors.dim
        const direction = high ? 1 : -1
        ctx.moveTo(centre - radius, markY - direction * radius); ctx.lineTo(centre + radius, markY - direction * radius); ctx.lineTo(centre, markY + direction * radius)
      } else if (mark.kind.startsWith("abs")) { ctx.fillStyle = colors.va; ctx.rect(centre - radius, markY - radius, 2 * radius, 2 * radius) }
      else { ctx.fillStyle = mark.kind === "div-bear" ? colors.down : colors.up; ctx.moveTo(centre, markY - radius - 1); ctx.lineTo(centre + radius + 1, markY); ctx.lineTo(centre, markY + radius + 1); ctx.lineTo(centre - radius - 1, markY) }
      ctx.fill()
    }
    ctx.restore()
  }

  // big trades: circles sized by value (area ~ value), green bought / red sold
  private bubbles(ctx: CanvasRenderingContext2D, yAt: (price: number) => number, big: Big[], xAt: (time: number) => number | null, usd: number,
    width: number, colors: FootprintOptions["colors"]) {
    ctx.save()
    ctx.lineWidth = 1
    for (const [ms, price, qty, buy] of big) {
      const centre = xAt(ms / 1000)
      if (centre == null || centre < -20 || centre > width + 20) continue
      const radius = Math.max(3, Math.min(18, 4 * Math.sqrt((price * qty) / (usd || price * qty))))
      ctx.beginPath(); ctx.arc(centre, yAt(price), radius, 0, 2 * Math.PI)
      ctx.fillStyle = rgba(buy ? colors.up : colors.down, 0.3); ctx.fill()
      ctx.strokeStyle = rgba(buy ? colors.up : colors.down, 0.9); ctx.stroke()
    }
    ctx.restore()
  }

  // the book: each column's resting size per row, dark blue -> cyan -> yellow -> white (bookmap style)
  private heat(ctx: CanvasRenderingContext2D, yAt: (price: number) => number, heat: Heat, xAt: (time: number) => number | null,
    pxPerSec: number, opts: FootprintOptions, width: number) {
    const size = heat.step
    if (!size) return
    const full = opts.heatMax > 0 ? opts.heatMax : heat.scale
    const level = opts.heatLog ? (amount: number) => Math.log1p(amount) / Math.log1p(full) : (amount: number) => amount / full
    for (const col of heat.cols) {
      const x = xAt(col.t)
      if (x == null) continue
      const colWidth = Math.max(1, col.span * pxPerSec + 0.5)
      if (x + colWidth < 0 || x > width) continue
      for (const side of [col.b, col.a]) {
        for (let i = 0; i < side.length; i++) {
          const amount = side[i]
          if (!amount) continue
          const strength = Math.min(1, Math.max(0, level(amount)) ** (1 / opts.contrast))
          if (strength < 0.03) continue
          const top = yAt((col.lo + i + 1) * size), bottom = yAt((col.lo + i) * size)
          ctx.fillStyle = ramp(strength)
          ctx.fillRect(x, top, colWidth, Math.max(1, bottom - top))
        }
      }
    }
  }

  // large orders: ○ appeared, × pulled, ● filled; bigger for bigger orders; green bid, red ask
  private walls(ctx: CanvasRenderingContext2D, yAt: (price: number) => number, events: WallEvent[], xAt: (time: number) => number | null,
    usd: number, colors: FootprintOptions["colors"]) {
    ctx.save()
    ctx.lineWidth = 1.5
    for (const [ms, price, qty, side, kind] of events) {
      const x = xAt(ms / 1000)
      if (x == null) continue
      const y = yAt(price)
      const radius = Math.max(2.5, Math.min(9, 3 * Math.sqrt((price * qty) / (usd || price * qty))))
      const col = side ? colors.up : colors.down
      ctx.strokeStyle = col; ctx.fillStyle = col
      if (kind === "appear") { ctx.beginPath(); ctx.arc(x, y, radius, 0, 2 * Math.PI); ctx.stroke() }
      else if (kind === "filled") { ctx.beginPath(); ctx.arc(x, y, radius, 0, 2 * Math.PI); ctx.fill() }
      else {
        ctx.strokeStyle = colors.poc
        ctx.beginPath(); ctx.moveTo(x - radius, y - radius); ctx.lineTo(x + radius, y + radius); ctx.moveTo(x + radius, y - radius); ctx.lineTo(x - radius, y + radius); ctx.stroke()
      }
    }
    ctx.restore()
  }

  // the biggest font (11 down to 8 px) at which every row's numbers fit the column; 0 = none fits
  private fit(ctx: CanvasRenderingContext2D, style: CellStyle, reading: ReturnType<typeof read>, width: number): number {
    let left = "", right = "", one = ""
    for (const row of reading.rows) {
      if (style === "bidask" || style === "trades") {
        const [sellText, buyText] = style === "trades" ? [String(row.ns), String(row.nb)] : [short(row.vs), short(row.vb)]
        if (sellText.length > left.length) left = sellText
        if (buyText.length > right.length) right = buyText
      } else {
        const label = style === "delta" ? `+${short(row.vb - row.vs)}` : short(row.vb + row.vs)
        if (label.length > one.length) one = label
      }
    }
    for (const px of [11, 10, 9, 8]) {
      ctx.font = font(px, true)
      const need = one ? ctx.measureText(one).width + 6 : 2 * Math.max(ctx.measureText(left).width, ctx.measureText(right).width) + 14
      if (need <= width) return px
    }
    return 0
  }

  private candle(ctx: CanvasRenderingContext2D, yAt: (price: number) => number, bar: Bar, x: number, width: number, color: string) {
    ctx.fillStyle = color
    const highY = yAt(bar.h), lowY = yAt(bar.l), openY = yAt(bar.o), closeY = yAt(bar.c)
    ctx.fillRect(Math.round(x) - 0.5, highY, 1, lowY - highY)
    ctx.fillRect(x - width / 2, Math.min(openY, closeY), width, Math.max(1, Math.abs(openY - closeY)))
  }

  private cell(ctx: CanvasRenderingContext2D, style: CellStyle, row: Bar["rows"][number], reading: ReturnType<typeof read>,
    x: number, top: number, width: number, height: number, px: number, colors: FootprintOptions["colors"]) {
    const text = px > 0 && height >= px - 1
    const regular = font(px), bold = font(px, true)
    const vol = row.vb + row.vs, delta = row.vb - row.vs
    const buyImb = reading.buyImb.has(row.i), sellImb = reading.sellImb.has(row.i)
    const mid = top + height / 2 + px * 0.35
    if (style === "profile") {
      const sellWidth = (row.vs / (reading.maxVol || 1)) * width, buyWidth = (row.vb / (reading.maxVol || 1)) * width
      ctx.fillStyle = rgba(colors.down, 0.55); ctx.fillRect(x, top, sellWidth, height)
      ctx.fillStyle = rgba(colors.up, 0.55); ctx.fillRect(x + sellWidth, top, buyWidth, height)
      if (text) { ctx.font = regular; ctx.textAlign = "left"; ctx.fillStyle = colors.text; ctx.fillText(short(vol), x + 2, mid) }
    } else if (style === "volume") {
      ctx.fillStyle = rgba(colors.cell, 0.12); ctx.fillRect(x, top, width, height)
      ctx.fillStyle = rgba(colors.cell, 0.5); ctx.fillRect(x, top, (vol / (reading.maxVol || 1)) * width, height)
      if (text) { ctx.font = regular; ctx.textAlign = "right"; ctx.fillStyle = colors.text; ctx.fillText(short(vol), x + width - 3, mid) }
    } else {
      // bid x ask, trades and delta: background by the row's delta
      const alpha = 0.05 + 0.33 * (Math.abs(delta) / (reading.maxDelta || 1))
      ctx.fillStyle = rgba(delta >= 0 ? colors.up : colors.down, alpha)
      ctx.fillRect(x, top, width, height)
      if (text) {
        ctx.font = regular
        if (style === "delta") {
          ctx.textAlign = "center"; ctx.fillStyle = colors.text
          ctx.fillText(`${delta > 0 ? "+" : ""}${short(delta)}`, x + width / 2, mid)
        } else {
          const [left, right] = style === "trades" ? [row.ns, row.nb] : [row.vs, row.vb]
          const centreX = x + width / 2
          ctx.textAlign = "center"; ctx.fillStyle = colors.dim; ctx.fillText("×", centreX, mid)
          ctx.textAlign = "right"; ctx.font = sellImb ? bold : regular; ctx.fillStyle = sellImb ? colors.down : colors.text
          ctx.fillText(style === "trades" ? String(left) : short(left), centreX - 6, mid)
          ctx.textAlign = "left"; ctx.font = buyImb ? bold : regular; ctx.fillStyle = buyImb ? colors.up : colors.text
          ctx.fillText(style === "trades" ? String(right) : short(right), centreX + 6, mid)
        }
      }
    }
    // imbalances without numbers: a coloured edge (sells on the left, buys on the right)
    if (!text || style === "profile" || style === "volume" || style === "delta") {
      if (sellImb) { ctx.fillStyle = colors.down; ctx.fillRect(x, top, 2, height) }
      if (buyImb) { ctx.fillStyle = colors.up; ctx.fillRect(x + width - 2, top, 2, height) }
    }
  }
}

export class FootprintSeries implements ICustomSeriesPaneView<Time, FootprintItem, FootprintOptions> {
  private r = new Renderer()

  // new extras: call, then bump the rev option so the chart repaints
  setExtras(extras: Extras): void { this.r.extras = extras }

  renderer(): ICustomSeriesPaneRenderer { return this.r }

  update(data: PaneRendererCustomData<Time, FootprintItem>, opts: FootprintOptions): void {
    this.r.data = data
    this.r.opts = opts
  }

  priceValueBuilder(item: FootprintItem): number[] { return [item.bar.l, item.bar.h, item.bar.c] }

  isWhitespace(item: FootprintItem | WhitespaceData<Time>): item is WhitespaceData<Time> { return !(item as FootprintItem).bar }

  defaultOptions(): FootprintOptions {
    return {
      ...customSeriesDefaultOptions, cellStyle: "bidask", rows: 0, step: 0,
      settings: { ratio: 3, minVol: 0, stack: 3, va: 0.7 }, showPoc: true, showVa: true,
      tfSec: 60, contrast: 1, heatLog: false, heatMax: 0, wallUsd: 0, rev: 0,
      colors: { up: "#3ddc84", down: "#f0566a", text: "#e4eaf1", dim: "#8695a7", poc: "#f0a83c", va: "#8b5cf6", cell: "#3ea1ff", gap: "#4e5a6b" },
    }
  }
}
