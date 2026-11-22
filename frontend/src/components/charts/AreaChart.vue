<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue"
import { AreaSeries, BaselineSeries, createChart, LastPriceAnimationMode, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts"
import { alpha, baseOptions, css } from "./chartTheme"

// gradient area for equity (brand colours) or baseline for p&l (green above 0, red below), pulsing live end
const props = withDefaults(defineProps<{
  data: { time: number; value: number }[]
  mode?: "equity" | "pnl"
  minimal?: boolean
  height?: number | "fill"
}>(), { mode: "equity", minimal: false, height: 240 })

const el = ref<HTMLDivElement>()
let chart: IChartApi | null = null
let series: ISeriesApi<"Area"> | ISeriesApi<"Baseline"> | null = null

onMounted(() => {
  chart = createChart(el.value!, baseOptions(props.minimal))
  if (props.mode === "pnl") {
    const green = css("--green"), red = css("--red")
    series = chart.addSeries(BaselineSeries, {
      baseValue: { type: "price", price: 0 },
      topLineColor: green, topFillColor1: alpha(green, 0.35), topFillColor2: alpha(green, 0.02),
      bottomLineColor: red, bottomFillColor1: alpha(red, 0.02), bottomFillColor2: alpha(red, 0.35),
      lineWidth: 2, lastPriceAnimation: LastPriceAnimationMode.Continuous, priceLineVisible: false,
    })
  } else {
    const brandB = css("--brand-b"), brandA = css("--brand-a")
    series = chart.addSeries(AreaSeries, {
      lineColor: brandB, topColor: alpha(brandA, 0.42), bottomColor: alpha(brandB, 0.0), lineWidth: 2,
      lastPriceAnimation: LastPriceAnimationMode.Continuous, priceLineVisible: false, crosshairMarkerBackgroundColor: brandB,
    })
  }
  series.setData(props.data.map((point) => ({ time: point.time as UTCTimestamp, value: point.value })))
  chart.timeScale().fitContent()
})

// live ticks: a point appended or the last point moved update in place; anything else (inserted points) redraws
let prev: number[] = props.data.map((point) => point.time)
watch(() => props.data, (points) => {
  if (!series || !points.length) return
  const times = points.map((point) => point.time)
  const prevCount = prev.length
  const sameHead = (count: number) => count <= prevCount && times.slice(0, count).every((time, i) => time === prev[i])
  const tail = points[points.length - 1]
  if ((points.length === prevCount + 1 && sameHead(prevCount)) || (points.length === prevCount && prevCount > 0 && sameHead(prevCount - 1))) {
    series.update({ time: tail.time as UTCTimestamp, value: tail.value })
  } else {
    series.setData(points.map((point) => ({ time: point.time as UTCTimestamp, value: point.value })))
    chart?.timeScale().fitContent()
  }
  prev = times
}, { deep: true })
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
</script>

<template>
  <div ref="el" :style="{ height: height === 'fill' ? '100%' : `${height}px` }" class="w-full min-h-0" />
</template>
