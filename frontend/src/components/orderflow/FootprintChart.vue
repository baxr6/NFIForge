<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue"
import {
  createChart, createSeriesMarkers, HistogramSeries, LineSeries, type IChartApi, type IPriceLine, type ISeriesApi, type ISeriesMarkersPluginApi,
  type MouseEventParams, type SeriesMarker, type Time, type UTCTimestamp, type WhitespaceData,
} from "lightweight-charts"
import { alpha, baseOptions, css } from "@/components/charts/chartTheme"
import type { Mark, TradeOverlay } from "@/components/charts/CandleChart.vue"
import { tradeLines, tradeMarkers } from "@/components/charts/tradeMarks"
import { cvd, fundingAt, imbalance, type Bar, type Derivs, type Heat, type OiRead, type Settings, type WallEvent, type Zone } from "@/lib/orderflow"
import { FootprintSeries, type CellStyle, type FootprintItem, type FootprintOptions, type Overlays } from "./footprintSeries"

// footprint on the price pane, bar delta and cumulative delta in panes under it. data is replaced in place (zoom kept);
// the latest ~60 bars are shown at first so the numbers are readable
const props = defineProps<{
  bars: Bar[]; step: number; cellStyle: CellStyle; rows: number; settings: Settings
  showPoc: boolean; showVa: boolean; zones: Zone[]; gaps: number[]; session: boolean; title: string
  tfSec: number; heat: Heat | null; contrast: number; heatLog: boolean; heatMax: number; events: WallEvent[]; wallUsd: number; imb: Heat["imb"]; band: number
  overlays: Overlays
  oi: Map<number, OiRead> | null  // open interest pane (null = none)
  derivs: Derivs | null; showLiq: boolean  // liquidations + funding pane
  trade?: TradeOverlay; tradeMarks: Mark[]  // the bot's open trade on this pair (lines) and every trade's marks
  spotBars: Bar[] | null  // the spot pair's bars: its cumulative delta in the CVD pane
}>()
// view: what is on screen, so the book heatmap can be fetched at screen resolution
const emit = defineEmits<{
  hover: [bar: Bar | null, price: number | null]
  view: [v: { from: number; to: number; barPx: number; rowPx: number }]
  pick: [t: number]  // a bar was clicked (its time, s)
}>()

const el = ref<HTMLDivElement>()
let chart: IChartApi | null = null
let footprint: ISeriesApi<"Custom", Time, FootprintItem | WhitespaceData<Time>, FootprintOptions> | null = null
let deltaS: ISeriesApi<"Histogram"> | null = null
let cvdS: ISeriesApi<"Line"> | null = null
let spotS: ISeriesApi<"Line"> | null = null
let imbS: ISeriesApi<"Line"> | null = null
let shownFor = ""
let rev = 0
const view = new FootprintSeries()
function setExtras() {
  view.setExtras({ ...props.overlays, zones: props.zones, gaps: props.gaps, heat: props.heat, events: props.events })
  rev++
}
const green = css("--green"), red = css("--red")

const toTime = (time: number) => time as UTCTimestamp

function options(): Partial<FootprintOptions> {
  const decimals = Math.max(0, Math.min(10, Math.ceil(-Math.log10(props.step || 1) - 1e-9)))
  return {
    cellStyle: props.cellStyle, rows: props.rows, step: props.step, settings: { ...props.settings },
    showPoc: props.showPoc, showVa: props.showVa,
    tfSec: props.tfSec, contrast: props.contrast, heatLog: props.heatLog, heatMax: props.heatMax, wallUsd: props.wallUsd, rev,
    priceFormat: { type: "price", precision: decimals, minMove: 10 ** -decimals },
    colors: { up: green, down: red, text: css("--text"), dim: css("--text-dim"), poc: css("--amber"), va: css("--brand-a"), cell: css("--brand-b"), gap: css("--text-faint") },
  }
}

function setData() {
  if (!chart || !footprint) return
  footprint.applyOptions(options())
  footprint.setData(props.bars.map((bar) => ({ time: toTime(bar.t), bar: bar })))
  deltaS!.setData(props.bars.map((bar) => ({ time: toTime(bar.t), value: bar.vb - bar.vs, color: alpha(bar.vb >= bar.vs ? green : red, 0.6) })))
  const run = cvd(props.bars, props.session)
  cvdS!.setData(props.bars.map((bar, i) => ({ time: toTime(bar.t), value: run[i] })))
  setImb()
  setSpot()
  setDerivs()
  setTrades()
  // a new pair / timeframe: show the latest bars at a readable width
  const key = `${props.title}|${props.bars[0]?.t}`
  if (key !== shownFor && props.bars.length) {
    shownFor = key
    const count = props.bars.length
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, count - 22), to: count + 1 })
  }
}

// open interest change per bar coloured by who is opening / closing, with the open interest as a line; liquidated
// longs (down, red) / shorts (up, green) with the settled funding rate as a line. each pane exists only while shown
let oiS: ISeriesApi<"Histogram"> | null = null, oiLine: ISeriesApi<"Line"> | null = null
let liqLong: ISeriesApi<"Histogram"> | null = null, liqShort: ISeriesApi<"Histogram"> | null = null, fundS: ISeriesApi<"Line"> | null = null
const WHO_COLOR = () => ({ "longs opening": green, "shorts opening": red, "shorts closing": alpha(green, 0.4), "longs closing": alpha(red, 0.4) })
function setDerivs() {
  if (!chart) return
  const oiByBar = props.oi, derivData = props.derivs
  if (oiByBar?.size) {
    if (!oiS) {
      const paneIndex = chart.panes().length  // a new pane at the bottom
      oiS = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false, title: "ΔOI" }, paneIndex)
      oiLine = chart.addSeries(LineSeries, { color: css("--text-dim"), lineWidth: 1, priceScaleId: "oi", priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, paneIndex)
      chart.panes()[paneIndex]?.setStretchFactor(0.14)
    }
    const col = WHO_COLOR()
    oiS.setData(props.bars.map((bar) => {
      const entry = oiByBar.get(bar.t)
      return entry?.delta == null ? { time: toTime(bar.t) } : { time: toTime(bar.t), value: entry.delta, color: col[entry.who!] }
    }))
    oiLine!.setData(props.bars.map((bar) => { const entry = oiByBar.get(bar.t); return entry ? { time: toTime(bar.t), value: entry.oi } : { time: toTime(bar.t) } }))
  } else if (oiS) { chart.removePane(oiS.getPane().paneIndex()); oiS = oiLine = null }
  if (props.showLiq && derivData && (derivData.liq.size || derivData.funding.length)) {
    if (!liqLong) {
      const paneIndex = chart.panes().length  // a new pane at the bottom
      liqLong = chart.addSeries(HistogramSeries, { color: alpha(red, 0.8), priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false, title: "liq $" }, paneIndex)
      liqShort = chart.addSeries(HistogramSeries, { color: alpha(green, 0.8), priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false }, paneIndex)
      fundS = chart.addSeries(LineSeries, { color: css("--amber"), lineWidth: 1, lineType: 1, priceScaleId: "funding", priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, paneIndex)
      chart.panes()[paneIndex]?.setStretchFactor(0.12)
    }
    liqLong.setData(props.bars.map((bar) => { const liq = derivData.liq.get(bar.t); return liq?.long ? { time: toTime(bar.t), value: -liq.long } : { time: toTime(bar.t) } }))
    liqShort!.setData(props.bars.map((bar) => { const liq = derivData.liq.get(bar.t); return liq?.short ? { time: toTime(bar.t), value: liq.short } : { time: toTime(bar.t) } }))
    fundS!.setData(props.bars.map((bar) => { const rate = fundingAt(derivData.funding, bar.t + props.tfSec); return rate == null ? { time: toTime(bar.t) } : { time: toTime(bar.t), value: rate * 100 } }))
  } else if (liqLong) { chart.removePane(liqLong.getPane().paneIndex()); liqLong = liqShort = fundS = null }
}

// the bot's trades: markers on the bars, the open trade's avg entry / stop / liquidation lines
let markerApi: ISeriesMarkersPluginApi<Time> | null = null
let priceLines: IPriceLine[] = []
function setTrades() {
  if (!footprint || !markerApi) return
  const marks = [...props.tradeMarks, ...(props.trade?.marks ?? []).map((mark) => ({ ...mark, side: props.trade!.side }))]
  // the footprint series has no candle high / low for the plugin: markers are placed at the bar's high / low price,
  // and shrunk (marker size follows the bar width, and footprint bars are wide)
  const byT = new Map(props.bars.map((bar) => [bar.t, bar]))
  markerApi.setMarkers(tradeMarkers(marks, new Set(byT.keys())).map((mark): SeriesMarker<Time> => {
    const bar = byT.get(mark.time as number)!, size = (mark.size ?? 1) * 0.35
    if (mark.position === "aboveBar") return { ...mark, size, position: "atPriceTop", price: bar.h }
    if (mark.position === "belowBar") return { ...mark, size, position: "atPriceBottom", price: bar.l }
    return { ...mark, size }
  }))
  for (const line of priceLines) footprint.removePriceLine(line)
  priceLines = props.trade ? tradeLines(footprint, props.trade) : []
}

// spot cumulative delta on the perp's bars only (spot bars elsewhere would add empty slots to the time axis)
function setSpot() {
  if (!spotS) return
  const spot = props.spotBars ?? []
  const have = new Set(props.bars.map((bar) => bar.t))
  const run = cvd(spot, props.session)
  spotS.setData(spot.map((bar, i) => ({ b: bar, v: run[i] })).filter((point) => have.has(point.b.t)).map((point) => ({ time: toTime(point.b.t), value: point.v })))
}

function setImb() {
  if (!imbS) return
  const have = new Set(props.bars.map((bar) => bar.t))
  imbS.setData(props.imb.filter((row) => have.has(row.t)).map((row) => {
    const value = imbalance(row.v, props.band)
    return value == null ? { time: toTime(row.t) } : { time: toTime(row.t), value: value * 100 }
  }))
}

function emitView() {
  const range = chart?.timeScale().getVisibleLogicalRange()
  const count = props.bars.length
  if (!range || !count || !footprint) return
  const from = props.bars[Math.max(0, Math.floor(range.from))]?.t ?? props.bars[0].t
  const to = props.bars[Math.min(count - 1, Math.ceil(range.to))]?.t ?? props.bars[count - 1].t
  const barPx = chart!.timeScale().width() / Math.max(1, range.to - range.from)
  const lastClose = props.bars[count - 1].c
  const rowPx = Math.abs((footprint.priceToCoordinate(lastClose) ?? 0) - (footprint.priceToCoordinate(lastClose + props.step) ?? 0))
  emit("view", { from, to, barPx, rowPx })
}

onMounted(() => {
  chart = createChart(el.value!, { ...baseOptions(), rightPriceScale: { visible: true, borderVisible: false, scaleMargins: { top: 0.05, bottom: 0.05 } } })
  setExtras()
  footprint = chart.addCustomSeries(view, { priceLineVisible: true, lastValueVisible: true })
  deltaS = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false, title: "delta" }, 1)
  cvdS = chart.addSeries(LineSeries, { color: css("--brand-b"), lineWidth: 2, priceFormat: { type: "volume" }, priceLineVisible: false, title: "CVD" }, 2)
  spotS = chart.addSeries(LineSeries, { color: css("--amber"), lineWidth: 1, priceFormat: { type: "volume" }, priceLineVisible: false, title: "spot CVD" }, 2)
  imbS = chart.addSeries(LineSeries, { color: css("--amber"), lineWidth: 1, priceFormat: { type: "price", precision: 0, minMove: 1 }, priceLineVisible: false, title: "book %" }, 3)
  const panes = chart.panes()
  panes[1]?.setStretchFactor(0.16)
  panes[2]?.setStretchFactor(0.16)
  panes[3]?.setStretchFactor(0.12)
  let timer = 0
  chart.timeScale().subscribeVisibleLogicalRangeChange(() => { clearTimeout(timer); timer = window.setTimeout(emitView, 150) })
  chart.subscribeCrosshairMove((params: MouseEventParams) => {
    const item = params.seriesData.get(footprint!) as FootprintItem | undefined
    const price = params.point && params.paneIndex === 0 ? footprint!.coordinateToPrice(params.point.y) : null
    emit("hover", item?.bar ?? null, price)
  })
  markerApi = createSeriesMarkers(footprint, [])
  chart.subscribeClick((params: MouseEventParams) => { if (params.time != null) emit("pick", params.time as number) })
  setData()
  setTimeout(emitView, 50)
})

watch(() => [props.bars, props.session], setData)
watch(() => [props.cellStyle, props.rows, props.settings, props.showPoc, props.showVa, props.step, props.contrast, props.heatLog, props.heatMax],
  () => footprint?.applyOptions(options()), { deep: true })
// big arrays: replaced, never changed in place, so a shallow watch is enough
watch(() => [props.zones, props.gaps, props.heat, props.events, props.wallUsd, props.overlays], () => { setExtras(); footprint?.applyOptions(options()) })
watch(() => [props.imb, props.band], setImb)
watch(() => [props.oi, props.derivs, props.showLiq], setDerivs)
watch(() => props.spotBars, setSpot)
watch(() => [props.trade, props.tradeMarks], setTrades)

onBeforeUnmount(() => chart?.remove())
</script>

<template>
  <div class="relative w-full h-full min-h-0">
    <div ref="el" class="absolute inset-0" />
    <div class="absolute left-3 top-2 z-10 text-[11px] num pointer-events-none text-ink font-semibold bg-panel/80 rounded px-1.5 py-0.5">{{ title }}</div>
  </div>
</template>
