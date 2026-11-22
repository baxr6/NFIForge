<script setup lang="ts">
import { computed } from "vue"
import EChart from "@/components/charts/EChart.vue"
import { alpha, css, ecBase } from "@/components/charts/chartTheme"
import { short } from "@/lib/orderflow"
import { useBookNow } from "@/lib/orderflowBook"
import { look, pair } from "@/lib/orderflowState"

// depth chart of the Order Flow pair: resting value added up from the mid outwards, bids left, asks right
const { data, error } = useBookNow()
const RANGES = [0.25, 0.5, 1, 2, 5]

const depth = computed(() => {
  const book = data.value?.book
  if (!book || !book.bids.length || !book.asks.length) return null
  const mid = (book.bids[0][0] + book.asks[0][0]) / 2
  const lo = mid * (1 - look.depthPct / 100), hi = mid * (1 + look.depthPct / 100)
  const side = (levels: [number, number][], inside: (price: number) => boolean) => {
    let run = 0
    const out: [number, number][] = []
    for (const [price, amount] of levels) {
      if (!inside(price)) break
      run += price * amount
      out.push([price, run])
    }
    return out
  }
  const bids = side(book.bids, (price) => price >= lo).reverse()
  const asks = side(book.asks, (price) => price <= hi)
  // how far the book the exchange sends reaches; a shorter side means the chart can't go further
  const reach = Math.min((mid - book.bids[book.bids.length - 1][0]) / mid, (book.asks[book.asks.length - 1][0] - mid) / mid) * 100
  return { mid, lo, hi, bids, asks, reach }
})

const option = computed(() => {
  const current = depth.value
  if (!current) return {}
  const base = ecBase(), green = css("--green"), red = css("--red")
  const line = (data: [number, number][], color: string) => ({
    type: "line", step: "end", data, symbol: "none", lineStyle: { color: color, width: 1.5 }, areaStyle: { color: alpha(color, 0.18) },
  })
  return {
    animation: false,
    grid: { left: 8, right: 8, top: 10, bottom: 22, containLabel: true },
    tooltip: { ...base.tooltip, trigger: "axis", valueFormatter: (value: number) => `$${short(value)}` },
    xAxis: { type: "value", min: current.lo, max: current.hi, ...base.axis, axisLabel: { ...base.axis.axisLabel, formatter: (value: number) => `${(((value - current.mid) / current.mid) * 100).toFixed(1)}%` } },
    yAxis: { type: "value", ...base.valueAxis, axisLabel: { ...base.valueAxis.axisLabel, formatter: (value: number) => short(value) } },
    series: [line(current.bids, green), line(current.asks, red)],
  }
})
const sel = "rounded-md bg-raised border border-line px-1.5 py-0.5 text-ink text-xs"
</script>

<template>
  <div class="flex flex-col h-full min-h-0 panel p-2 text-xs">
    <div class="flex items-center gap-2 pb-1">
      <span class="text-ink font-semibold">Depth</span>
      <span class="text-faint truncate">{{ pair }}</span>
      <label class="ml-auto flex items-center gap-1 text-dim">±
        <select v-model.number="look.depthPct" :class="sel"><option v-for="percent in RANGES" :key="percent" :value="percent">{{ percent }}%</option></select>
      </label>
    </div>
    <div class="flex-1 min-h-0">
      <EChart v-if="depth" :option="option" height="fill" />
      <div v-else class="h-full grid place-items-center text-dim">{{ error || "waiting for the book…" }}</div>
    </div>
    <div v-if="depth && depth.reach < look.depthPct" class="pt-1 text-faint text-[10px]">the exchange's book reaches ±{{ depth.reach.toFixed(2) }}% only</div>
  </div>
</template>
