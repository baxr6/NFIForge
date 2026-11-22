<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue"
import {
  BaselineSeries, CandlestickSeries, createChart, createSeriesMarkers, HistogramSeries, LineSeries,
  type IChartApi, type ISeriesApi, type ISeriesMarkersPluginApi, type MouseEventParams, type Time, type UTCTimestamp,
} from "lightweight-charts"
import { decimals } from "@/lib/format"
import { alpha, baseOptions, css } from "./chartTheme"
import { tradeLines, tradeMarkers } from "./tradeMarks"

export type Candle = { time: number; open: number; high: number; low: number; close: number; volume: number }
export type Mark = { time: number; kind: "entry" | "dca" | "exit" | "signal"; side: "long" | "short"; text?: string; stake?: number }
export type TradeOverlay = {
  side: "long" | "short"
  avgEntry: number
  liquidation?: number
  stop?: number
  openTime: number
  closeTime?: number
  marks: Omit<Mark, "side">[]
  levels?: { price: number; text: string }[]
}
// indicator line: pane 0 = on the price, 2+ = own panes under volume (1)
export type Line = { name: string; color: string; pane: number; data: { time: number; value: number | null }[] }

// candles + volume pane + indicator lines/panes + trade overlays (entry/dca/exit marks, avg entry, liquidation,
// profit/loss zone); candle and line data update in place so zoom survives live refreshes
const props = withDefaults(defineProps<{
  candles: Candle[]; trade?: TradeOverlay; marks?: Mark[]; lines?: Line[]; height?: number | "fill"; title?: string
}>(), { height: 420, title: "", marks: () => [], lines: () => [] })

const el = ref<HTMLDivElement>()
const readout = ref<{ o: number; h: number; l: number; c: number; v: number; chg: number; ind: { name: string; color: string; v: number }[] } | null>(null)
let chart: IChartApi | null = null
let candleS: ISeriesApi<"Candlestick"> | null = null
let volS: ISeriesApi<"Histogram"> | null = null
let markerApi: ISeriesMarkersPluginApi<Time> | null = null
const lineS = new Map<string, ISeriesApi<"Line">>()
const green = css("--green"), red = css("--red")

const toTime = (time: number) => time as UTCTimestamp
const lineData = (line: Line) => line.data.map((point) => (point.value == null || !Number.isFinite(point.value) ? { time: toTime(point.time) } : { time: toTime(point.time), value: point.value }))

function setData() {
  const last = props.candles[props.candles.length - 1]?.close ?? 0
  const precision = decimals(last)
  const priceFormat = { type: "price" as const, precision, minMove: 10 ** -precision }
  candleS!.applyOptions({ priceFormat })
  for (const line of props.lines) if (!line.pane) lineS.get(line.name)?.applyOptions({ priceFormat })
  candleS!.setData(props.candles.map((candle) => ({ ...candle, time: toTime(candle.time) })))
  volS!.setData(props.candles.map((candle) => ({ time: toTime(candle.time), value: candle.volume, color: alpha(candle.close >= candle.open ? green : red, 0.35) })))
  for (const line of props.lines) lineS.get(line.name)?.setData(lineData(line))
  const tradeMarks = (props.trade?.marks ?? []).map((mark) => ({ ...mark, side: props.trade!.side }))
  markerApi!.setMarkers(tradeMarkers([...tradeMarks, ...props.marks], new Set(props.candles.map((candle) => candle.time))))
}

onMounted(() => {
  chart = createChart(el.value!, baseOptions())
  candleS = chart.addSeries(CandlestickSeries, {
    upColor: alpha(green, 0.9), downColor: alpha(red, 0.9), borderVisible: false,
    wickUpColor: alpha(green, 0.75), wickDownColor: alpha(red, 0.75), priceLineColor: css("--line-bright"),
  })
  // volume in its own pane, coloured by candle direction
  volS = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false }, 1)
  for (const line of props.lines) {
    lineS.set(line.name, chart.addSeries(LineSeries, { color: line.color, lineWidth: line.pane ? 1 : 2, priceLineVisible: false, lastValueVisible: line.pane > 0, crosshairMarkerVisible: false, title: line.pane ? line.name : "" }, line.pane))
  }
  const panes = chart.panes()
  panes[1]?.setStretchFactor(0.22)
  for (let i = 2; i < panes.length; i++) panes[i].setStretchFactor(0.3)

  const overlay = props.trade
  if (overlay) {
    // in-profit / in-loss shading between avg entry and price over the trade's life
    const life = props.candles.filter((candle) => candle.time >= overlay.openTime && candle.time <= (overlay.closeTime ?? Infinity))
    const zone = chart.addSeries(BaselineSeries, {
      baseValue: { type: "price", price: overlay.avgEntry },
      topLineColor: "transparent", bottomLineColor: "transparent",
      topFillColor1: alpha(overlay.side === "long" ? green : red, 0.16), topFillColor2: alpha(overlay.side === "long" ? green : red, 0.16),
      bottomFillColor1: alpha(overlay.side === "long" ? red : green, 0.16), bottomFillColor2: alpha(overlay.side === "long" ? red : green, 0.16),
      lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
    })
    zone.setData(life.map((candle) => ({ time: toTime(candle.time), value: candle.close })))
    tradeLines(candleS, overlay)
  }
  markerApi = createSeriesMarkers(candleS, [])
  setData()

  // floating ohlc + indicator readout instead of a tooltip box
  chart.subscribeCrosshairMove((params: MouseEventParams) => {
    const candle = params.seriesData.get(candleS!) as any
    if (!candle) { readout.value = null; return }
    const volume = (params.seriesData.get(volS!) as any)?.value ?? 0
    const ind = props.lines.map((line) => ({ name: line.name, color: line.color, v: (params.seriesData.get(lineS.get(line.name)!) as any)?.value })).filter((entry) => entry.v != null)
    readout.value = { o: candle.open, h: candle.high, l: candle.low, c: candle.close, v: volume, chg: ((candle.close - candle.open) / candle.open) * 100, ind }
  })
  chart.timeScale().fitContent()
})

// new candles / refreshed indicators: replace data, keep the user's zoom
watch(() => [props.candles, props.lines, props.marks], () => { if (chart) setData() })

let resizeObserver: ResizeObserver | null = null
let lastW = 0
onMounted(() => {
  resizeObserver = new ResizeObserver(([entry]) => {
    const width = Math.round(entry.contentRect.width)
    if (width > 0 && Math.abs(width - lastW) > 4) { lastW = width; chart?.timeScale().fitContent() }
  })
  resizeObserver.observe(el.value!)
})
onBeforeUnmount(() => { resizeObserver?.disconnect(); chart?.remove() })

const fmt = (value: number) => (Math.abs(value) >= 100 ? value.toFixed(2) : Math.abs(value) >= 1 ? value.toFixed(4) : value.toPrecision(5))
</script>

<template>
  <div class="relative w-full min-h-0" :style="{ height: height === 'fill' ? '100%' : `${height}px` }">
    <div ref="el" class="absolute inset-0" />
    <div class="absolute left-3 top-2 z-10 flex flex-wrap gap-x-3 text-[11px] num pointer-events-none pr-20">
      <span class="text-ink font-semibold">{{ title }}</span>
      <span v-if="trade?.liquidation" class="text-down">liq {{ fmt(trade.liquidation) }} ({{ (((trade.liquidation - trade.avgEntry) / trade.avgEntry) * 100).toFixed(1) }}%)</span>
      <template v-if="readout">
        <span class="text-dim">O <span class="text-ink">{{ fmt(readout.o) }}</span></span>
        <span class="text-dim">H <span class="text-ink">{{ fmt(readout.h) }}</span></span>
        <span class="text-dim">L <span class="text-ink">{{ fmt(readout.l) }}</span></span>
        <span class="text-dim">C <span class="text-ink">{{ fmt(readout.c) }}</span></span>
        <span :class="readout.chg >= 0 ? 'text-up' : 'text-down'">{{ readout.chg >= 0 ? "+" : "" }}{{ readout.chg.toFixed(2) }}%</span>
        <span v-for="indicator in readout.ind" :key="indicator.name" :style="{ color: indicator.color }">{{ indicator.name }} {{ fmt(indicator.v) }}</span>
      </template>
    </div>
  </div>
</template>
