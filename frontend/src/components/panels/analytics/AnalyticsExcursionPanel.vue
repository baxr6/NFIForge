<script setup lang="ts">
import { esc } from "@/lib/format"
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { css, ecBase } from "@/components/charts/chartTheme"
import EChart from "@/components/charts/EChart.vue"
import PanelCard from "@/components/layout/PanelCard.vue"
import { useAnalytics } from "@/lib/state/analytics"

// MFE / MAE scatter of the shown closed trades: worst move vs result (how deep winners dip, for stops) and best move
// vs result (how much of the move was kept). measured in the background from exchange candles, once per trade
const { shown, bots } = useAnalytics()
const lev = ref(false)
type Ex = { rows: Record<string, [number | null, number | null]>; done: number; total: number }
const excursions = ref<Record<string, Ex>>({})

async function load() {
  for (const botName of bots.value) {
    const response = await fetch(`/api/bots/${encodeURIComponent(botName)}/excursions`).catch(() => null)
    if (response?.ok) excursions.value[botName] = await response.json()
  }
}
watch(() => bots.value.join(), load, { immediate: true })
// keep refreshing while some trades are still being measured
const pending = computed(() => Object.values(excursions.value).some((progress) => progress.done < progress.total))
const timer = setInterval(() => { if (pending.value) load() }, 15000)
onBeforeUnmount(() => clearInterval(timer))

// one point per measured trade: [mae, mfe, result] in price % (or leveraged %)
const pts = computed(() => shown.value.flatMap((trade) => {
  const row = excursions.value[trade._bot]?.rows[String(trade.trade_id)]
  if (!row || row[0] == null || row[1] == null) return []
  const tradeLeverage = trade.leverage || 1, scale = lev.value ? tradeLeverage : 1
  const res = ((trade.close_profit ?? trade.profit_ratio ?? 0) * 100 / tradeLeverage) * scale
  return [{ mfe: row[0] * scale, mae: row[1] * scale, res, pair: trade.pair as string, tag: trade.enter_tag as string, id: trade.trade_id }]
}))
const measured = computed(() => pts.value.length)
const progress = computed(() => {
  const all = Object.values(excursions.value)
  return { done: all.reduce((sum, progress) => sum + progress.done, 0), total: all.reduce((sum, progress) => sum + progress.total, 0) }
})

const quantile = (values: number[], fraction: number) => { const sorted = [...values].sort((a, b) => a - b); return sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(fraction * sorted.length))] : null }
const wins = computed(() => pts.value.filter((point) => point.res > 0))
// 95 % of winners stayed above this
const winnerDip = computed(() => quantile(wins.value.map((point) => point.mae), 0.05))
// share of the best move a winner kept (median)
const kept = computed(() => quantile(wins.value.filter((point) => point.mfe > 0).map((point) => Math.min(point.res / point.mfe, 1)), 0.5))

function option(axis: "mae" | "mfe") {
  const theme = ecBase(), unit = lev.value ? "% lev" : "%"
  const dot = (point: (typeof pts.value)[number]) => ({ value: [+point[axis].toFixed(2), +point.res.toFixed(2)], p: point, itemStyle: { color: point.res >= 0 ? css("--green") : css("--red"), opacity: 0.7 } })
  return {
    tooltip: { ...theme.tooltip, formatter: (params: any) => { const point = params.data.p; return `${esc(point.pair)} #${point.id} · tag ${esc(point.tag)}<br/>result ${point.res.toFixed(2)}${unit}<br/>best ${point.mfe.toFixed(2)} · worst ${point.mae.toFixed(2)}` } },
    grid: { left: 46, right: 12, top: 26, bottom: 36 },
    xAxis: { type: "value", name: axis === "mae" ? `worst move against (${unit})` : `best move in favour (${unit})`, nameLocation: "middle", nameGap: 24, nameTextStyle: { color: css("--text-dim"), fontSize: 11 }, ...theme.valueAxis },
    yAxis: { type: "value", name: `result (${unit})`, nameTextStyle: { color: css("--text-dim"), fontSize: 11 }, ...theme.valueAxis },
    series: [{ type: "scatter", symbolSize: 6, data: pts.value.map(dot), markLine: { silent: true, symbol: "none", lineStyle: { color: css("--line-bright"), type: "dashed" }, data: [{ yAxis: 0 }] } }],
  }
}
const maeOption = computed(() => option("mae"))
const mfeOption = computed(() => option("mfe"))
const pctS = (value: number | null) => (value == null ? "–" : `${value.toFixed(1)}%`)
</script>

<template>
  <PanelCard title="Best / worst move (MFE / MAE)">
    <template #actions>
      <span v-if="progress.done < progress.total" class="text-xs text-faint num">measuring {{ progress.done }} of {{ progress.total }} trades…</span>
      <div class="flex rounded-md border border-line overflow-hidden text-xs">
        <button class="px-2.5 py-1" :class="!lev ? 'bg-raised text-ink' : 'text-dim hover:text-ink'" @click="lev = false">price %</button>
        <button class="px-2.5 py-1" :class="lev ? 'bg-raised text-ink' : 'text-dim hover:text-ink'" @click="lev = true">leveraged %</button>
      </div>
    </template>
    <div class="h-full flex flex-col gap-2 min-h-0">
      <div class="text-xs text-dim num flex flex-wrap gap-x-4">
        <span>{{ measured }} trades shown</span>
        <span v-if="winnerDip != null">95% of winners never went below <span class="text-ink">{{ pctS(winnerDip) }}</span></span>
        <span v-if="kept != null">winners kept a median <span class="text-ink">{{ (kept * 100).toFixed(0) }}%</span> of their best move</span>
        <span class="text-faint">from candle highs / lows, so moves read slightly bigger than they were</span>
      </div>
      <div v-if="!measured" class="flex-1 grid place-items-center text-xs text-faint">{{ progress.total ? "no measured trades in this filter yet" : "no closed trades" }}</div>
      <div v-else class="flex-1 min-h-0 grid gap-2 md:grid-cols-2">
        <EChart :option="maeOption" height="fill" />
        <EChart :option="mfeOption" height="fill" />
      </div>
    </div>
  </PanelCard>
</template>
