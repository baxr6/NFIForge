<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { css, ecBase } from "@/components/charts/chartTheme"
import EChart from "@/components/charts/EChart.vue"
import PanelCard from "@/components/layout/PanelCard.vue"
import { coinOf } from "@/lib/btcgate"
import { age, money } from "@/lib/format"

// each bot's open trades as btcgate's book (worker.book): how many independent bets, the likely 24 h swing. information
// only: nothing here trades, blocks or resizes
type Book = { n: number; measured: number; unmeasured: string[]; long: number; short: number; gross: number; eff: number | null; sd: number | null; naive_sd: number | null; stress: Record<string, number>; stress_side: string; risk_share: Record<string, number> }
type Row = { at: string; bot: string; n: number; eff: number | null; sd: number | null; naive_sd: number | null; gross: number }
const data = ref<{ time?: number; books: Record<string, Book>; history: Row[] } | null>(null)
async function load() {
  const response = await fetch("/api/btcgate/book").catch(() => null)
  if (response?.ok) data.value = await response.json()
}
let timer = 0
onMounted(() => { load(); timer = window.setInterval(load, 60_000) })
onBeforeUnmount(() => clearInterval(timer))

const BAD_DAY = 0.97  // btcgate's Z_BAD_DAY: one day in six
const usd = (value: number | null | undefined) => (value == null ? "–" : `$${money(value, 0)}`)
const books = computed(() => Object.entries(data.value?.books ?? {}))
const top = (book: Book) => Object.entries(book.risk_share).sort((left, right) => right[1] - left[1]).slice(0, 3)

function option(bot: string) {
  const rows = (data.value?.history ?? []).filter((row) => row.bot === bot)
  const theme = ecBase()
  const line = (name: string, key: "sd" | "eff", color: string, axis: number) => ({
    name, type: "line", yAxisIndex: axis, showSymbol: false, connectNulls: false, lineStyle: { color, width: 1.5 }, itemStyle: { color },
    data: rows.map((row) => [Date.parse(row.at.replace(" ", "T")), row[key]]),
  })
  return {
    tooltip: { ...theme.tooltip, trigger: "axis" },
    legend: { top: 0, textStyle: { color: css("--text-dim"), fontSize: 11 } },
    grid: { left: 52, right: 40, top: 28, bottom: 24 },
    xAxis: { type: "time", ...theme.axis },
    yAxis: [
      { type: "value", ...theme.valueAxis, axisLabel: { ...theme.axis.axisLabel, formatter: (value: number) => `$${money(value, 0)}` } },
      { type: "value", ...theme.axis, min: 0, splitLine: { show: false } },
    ],
    series: [line("likely 24 h swing", "sd", css("--brand-b"), 0), line("bets", "eff", css("--green"), 1)],
  }
}
</script>

<template>
  <div class="space-y-3">
    <p class="text-sm text-dim">Coins move together, so ten long alts usually behave like about two bets. The likely swing is one normal day's move of the whole book (from 30 days of hourly prices). Information only: nothing here trades or changes a bot. Alerts for it are in Settings → Book.</p>
    <div v-if="!books.length" class="panel p-4 text-sm text-dim">No book yet: it's worked out after the worker's next pass (every 5 minutes) for each connected bot.</div>
    <div class="grid gap-3 xl:grid-cols-2">
      <PanelCard v-for="[bot, book] in books" :key="bot" :title="bot">
        <template #actions><span class="ml-auto text-xs text-faint">{{ data?.time ? `${age(data.time)} ago` : "" }}</span></template>
        <div v-if="!book.n" class="text-sm text-dim">no open trades</div>
        <div v-else class="space-y-3 text-sm">
          <div class="flex flex-wrap gap-x-6 gap-y-2">
            <div><div class="text-xs text-dim">Open trades</div><div class="text-lg num">{{ book.n }}</div>
              <div class="text-xs text-dim num">long {{ usd(book.long) }} · short {{ usd(book.short) }}</div></div>
            <div><div class="text-xs text-dim">Behaves like</div><div class="text-lg num">{{ book.eff == null ? "–" : book.eff.toFixed(1) }} <span class="text-sm text-dim">bets</span></div>
              <div v-if="book.eff != null" class="text-xs text-dim">{{ book.measured }} measured trades</div></div>
            <div><div class="text-xs text-dim">Likely 24 h swing</div><div class="text-lg num">±{{ usd(book.sd) }}</div>
              <div v-if="book.sd != null" class="text-xs text-dim num">{{ ((book.sd / book.gross) * 100).toFixed(1) }}% of exposure · bad day (1 in 6) −{{ usd(book.sd * BAD_DAY) }}</div></div>
          </div>
          <div v-if="book.eff == null" class="text-warn">not enough price history to measure yet</div>
          <ul class="space-y-1 text-dim">
            <li v-if="book.naive_sd != null">counting the trades as independent would say ±{{ usd(book.naive_sd) }}</li>
            <li>if the whole market {{ book.stress_side }} together: <span class="num text-ink">{{ Object.entries(book.stress).map(([move, loss]) => `${Math.round(+move * 100)}% −${usd(-loss)}`).join(", ") }}</span></li>
            <li v-if="book.n > 3 && top(book).length">most of the risk: <span class="text-ink">{{ top(book).map(([pair, share]) => `${coinOf(pair)} ${Math.round(share * 100)}%`).join(", ") }}</span></li>
            <li v-if="book.unmeasured.length">not measured (no Binance history or too short): {{ book.unmeasured.map((pair) => coinOf(pair)).join(", ") }}</li>
          </ul>
          <EChart v-if="(data?.history ?? []).some((row) => row.bot === bot)" :option="option(bot)" :height="180" />
        </div>
      </PanelCard>
    </div>
  </div>
</template>
