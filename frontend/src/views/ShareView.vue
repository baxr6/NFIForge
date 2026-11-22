<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import AreaChart from "@/components/charts/AreaChart.vue"
import EChart from "@/components/charts/EChart.vue"
import { css, ecBase } from "@/components/charts/chartTheme"
import { age, esc, pct, tone } from "@/lib/format"

// results in percent only (docs/SHARING.md): a share link for anyone with it (/s/<code>), or a percent-only
// viewer's whole NFIForge. the server sends nothing else, so this page can't show amounts by mistake
const props = defineProps<{ src: string; user?: string }>()
const emit = defineEmits<{ signOut: [] }>()

type Pos = { pair: string; short: boolean; leverage: number; opened: number; pct: number; entries?: number; closed?: number; tag?: string; exit?: string }
type Bot = {
  name: string; connected: boolean; exchange: string | null
  summary: { today: number | null; week: number | null; month: number | null; all: number | null; open: number | null; trades: number; won: number | null; profit_factor: number | null; drawdown: number; slots: number; slots_max: number | null }
  equity: [number, number][]; daily: { day: string; pct: number; trades: number }[]; open?: Pos[]; closed?: Pos[]
}
const page = ref<{ title: string; ts: number; bots: Bot[] } | null>(null)
const error = ref("")
const shown = ref(0)

async function load() {
  const response = await fetch(props.src, { cache: "no-store" }).catch(() => null)
  const body = response ? await response.json().catch(() => null) : null
  if (response?.ok && body) { page.value = body; error.value = "" }
  else error.value = body?.detail ?? (response ? response.statusText : "not reachable")
}
let timer = 0
onMounted(() => {
  load()
  timer = window.setInterval(load, 30000)
  // a share link stays out of search engines and doesn't travel on as a referrer
  for (const [name, content] of [["robots", "noindex, nofollow"], ["referrer", "no-referrer"]]) {
    const meta = document.createElement("meta")
    meta.name = name
    meta.content = content
    document.head.append(meta)
  }
})
onBeforeUnmount(() => clearInterval(timer))

const bot = computed(() => page.value?.bots[shown.value] ?? page.value?.bots[0])
const when = (ms?: number) => (ms ? new Date(ms).toLocaleString("en-GB", { hour12: false, dateStyle: "short", timeStyle: "short" }) : "–")
const coin = (pair: string) => pair.split("/")[0]
// one point per second (the chart needs rising times)
const equity = computed(() => {
  const byTime = new Map<number, number>()
  for (const [ms, value] of bot.value?.equity ?? []) byTime.set(Math.floor(ms / 1000), value)
  return [...byTime].sort((a, b) => a[0] - b[0]).map(([time, value]) => ({ time, value }))
})
const tiles = computed(() => {
  const summary = bot.value?.summary
  if (!summary) return []
  return [
    { label: "Today", v: pct(summary.today), t: summary.today }, { label: "7 days", v: pct(summary.week), t: summary.week },
    { label: "30 days", v: pct(summary.month), t: summary.month }, { label: "All time", v: pct(summary.all), t: summary.all },
    { label: "Open trades now", v: pct(summary.open), t: summary.open, hint: "of the account" },
    { label: "Won", v: summary.won == null ? "–" : `${summary.won.toFixed(0)}%`, hint: `${summary.trades} trades` },
    { label: "Profit factor", v: summary.profit_factor == null ? "–" : summary.profit_factor.toFixed(2), hint: "won ÷ lost" },
    { label: "Deepest drawdown", v: `${summary.drawdown.toFixed(2)}%`, t: summary.drawdown < 0 ? -1 : 0, hint: "closed trades" },
    { label: "Slots in use", v: summary.slots_max ? `${summary.slots} / ${summary.slots_max}` : String(summary.slots) },
  ]
})
const calendar = computed(() => {
  const theme = ecBase(), rows = bot.value?.daily ?? []
  const end = rows.length ? rows[rows.length - 1].day : new Date().toISOString().slice(0, 10)
  // at least 16 weeks across (a few days alone stretch into long bars), at most a year
  const ago = (days: number) => new Date(Date.parse(end) - days * 86400000).toISOString().slice(0, 10)
  const first = rows[0]?.day ?? end
  const start = first < ago(364) ? ago(364) : first > ago(111) ? ago(111) : first
  const max = Math.max(0.5, ...rows.map((row) => Math.abs(row.pct)))
  return {
    tooltip: { ...theme.tooltip, formatter: (params: any) => `${esc(params.value[0])}<br/>${pct(params.value[1])}<br/>${params.value[2]} trades` },
    visualMap: { min: -max, max, show: false, dimension: 1, inRange: { color: theme.diverging } },
    calendar: { range: [start, end], cellSize: ["auto", 14], top: 20, bottom: 4, left: 30, right: 8,
      itemStyle: { color: css("--panel"), borderColor: css("--void"), borderWidth: 3 }, splitLine: { show: false },
      dayLabel: { firstDay: 1, color: css("--text-faint"), fontFamily: "IBM Plex Mono", fontSize: 10 },
      monthLabel: { color: css("--text-dim"), fontFamily: "IBM Plex Sans", fontSize: 11 }, yearLabel: { show: false } },
    series: [{ type: "heatmap", coordinateSystem: "calendar", data: rows.filter((row) => row.day >= start).map((row) => [row.day, row.pct, row.trades]), itemStyle: { borderRadius: 3 } }],
  }
})
</script>

<template>
  <div class="min-h-full p-3 sm:p-4 2xl:p-6 max-w-[1400px] mx-auto space-y-3">
    <header class="flex flex-wrap items-center gap-x-3 gap-y-1">
      <div class="h-6 w-6 rounded-md" style="background: linear-gradient(135deg, var(--brand-a), var(--brand-b))" />
      <h1 class="text-xl font-semibold">{{ page?.title || "Results" }}</h1>
      <span v-if="page" class="text-xs text-dim num">updated {{ new Date(page.ts).toLocaleTimeString("en-GB", { hour12: false }) }} · every 30 s</span>
      <span class="ml-auto" />
      <template v-if="user">
        <span class="text-xs text-dim">{{ user }}</span>
        <button class="text-xs text-dim hover:text-ink" @click="emit('signOut')">Sign out</button>
      </template>
    </header>

    <div v-if="error && !page" class="panel p-8 text-center text-dim">{{ error }}</div>
    <div v-else-if="!page" class="panel p-8 text-center text-dim">loading…</div>
    <div v-else-if="!page.bots.length" class="panel p-8 text-center text-dim">no bots to show</div>
    <template v-else-if="bot">
      <div v-if="page.bots.length > 1" class="flex flex-wrap rounded-md border border-line overflow-hidden text-sm self-start w-fit">
        <button v-for="(item, i) in page.bots" :key="item.name" class="px-3 py-2 md:py-1.5" :class="[i && 'border-l border-line', bot === item ? 'bg-raised text-ink' : 'text-dim hover:text-ink']"
          @click="shown = i">{{ item.name }}</button>
      </div>
      <div class="flex items-center gap-2 text-sm">
        <span class="h-2 w-2 rounded-full" :style="{ background: bot.connected ? 'var(--green)' : 'var(--red)' }" />
        <span class="font-semibold">{{ bot.name }}</span>
        <span v-if="bot.exchange" class="text-dim">{{ bot.exchange }}</span>
        <span v-if="!bot.connected" class="text-warn text-xs">not reachable right now</span>
      </div>

      <div class="grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-9">
        <div v-for="tile in tiles" :key="tile.label" class="panel p-3">
          <div class="text-xs text-dim">{{ tile.label }}</div>
          <div class="text-xl font-semibold num mt-1" :class="'t' in tile ? tone(tile.t) : 'text-ink'">{{ tile.v }}</div>
          <div v-if="tile.hint" class="text-[11px] text-faint">{{ tile.hint }}</div>
        </div>
      </div>

      <div class="grid gap-3 lg:grid-cols-2">
        <div class="panel p-3">
          <div class="panel-title mb-2">Growth <span class="text-faint font-normal normal-case">closed trades, start = 100</span></div>
          <AreaChart v-if="equity.length > 1" :key="bot.name" :data="equity" :height="220" />
          <div v-else class="h-[220px] grid place-items-center text-dim text-sm">no closed trades yet</div>
        </div>
        <div class="panel p-3">
          <div class="panel-title mb-2">Each day <span class="text-faint font-normal normal-case">% of the account, UTC days</span></div>
          <EChart :option="calendar" :height="220" />
        </div>
      </div>

      <div v-if="bot.open" class="panel overflow-auto">
        <div class="panel-title px-3 pt-3 pb-2">Open trades ({{ bot.open.length }})</div>
        <table class="w-full text-sm num whitespace-nowrap">
          <thead class="text-xs text-dim text-left border-b border-line"><tr><th class="px-3 py-1.5 font-normal">pair</th><th class="px-3 font-normal">side</th><th v-if="bot.open.some((row) => 'tag' in row)" class="px-3 font-normal">tag</th><th class="px-3 font-normal">open for</th><th class="px-3 font-normal text-right">buys</th><th class="px-3 font-normal text-right">profit</th></tr></thead>
          <tbody>
            <tr v-for="position in bot.open" :key="position.pair + position.opened" class="border-b border-line last:border-0">
              <td class="px-3 py-1.5 font-semibold">{{ coin(position.pair) }}</td>
              <td class="px-3"><span :class="position.short ? 'text-down' : 'text-up'">{{ position.short ? "▼ short" : "▲ long" }}</span> <span class="text-dim">{{ position.leverage }}x</span></td>
              <td v-if="'tag' in position" class="px-3 text-dim">{{ position.tag }}</td>
              <td class="px-3">{{ age(position.opened / 1000) }}</td>
              <td class="px-3 text-right">{{ position.entries }}</td>
              <td class="px-3 text-right" :class="tone(position.pct)">{{ pct(position.pct) }}</td>
            </tr>
            <tr v-if="!bot.open.length"><td colspan="6" class="px-3 py-6 text-center text-dim">no open trades</td></tr>
          </tbody>
        </table>
      </div>

      <div v-if="bot.closed" class="panel overflow-auto">
        <div class="panel-title px-3 pt-3 pb-2">Latest closed trades</div>
        <table class="w-full text-sm num whitespace-nowrap">
          <thead class="text-xs text-dim text-left border-b border-line"><tr><th class="px-3 py-1.5 font-normal">closed</th><th class="px-3 font-normal">pair</th><th class="px-3 font-normal">side</th><th v-if="bot.closed.some((row) => 'tag' in row)" class="px-3 font-normal">tag</th><th v-if="bot.closed.some((row) => 'exit' in row)" class="px-3 font-normal">exit</th><th class="px-3 font-normal">held</th><th class="px-3 font-normal text-right">profit</th></tr></thead>
          <tbody>
            <tr v-for="trade in bot.closed" :key="trade.pair + trade.closed" class="border-b border-line last:border-0">
              <td class="px-3 py-1.5 text-dim">{{ when(trade.closed) }}</td>
              <td class="px-3 font-semibold">{{ coin(trade.pair) }}</td>
              <td class="px-3"><span :class="trade.short ? 'text-down' : 'text-up'">{{ trade.short ? "▼" : "▲" }}</span> <span class="text-dim">{{ trade.leverage }}x</span></td>
              <td v-if="'tag' in trade" class="px-3 text-dim">{{ trade.tag }}</td>
              <td v-if="'exit' in trade" class="px-3 text-dim truncate max-w-72" :title="trade.exit">{{ trade.exit }}</td>
              <td class="px-3">{{ age(trade.opened / 1000, (trade.closed ?? 0) / 1000) }}</td>
              <td class="px-3 text-right" :class="tone(trade.pct)">{{ pct(trade.pct) }}</td>
            </tr>
            <tr v-if="!bot.closed.length"><td colspan="7" class="px-3 py-6 text-center text-dim">no closed trades yet</td></tr>
          </tbody>
        </table>
      </div>
    </template>

    <p class="text-xs text-faint pt-2">Percentages only: of the account's starting balance plus what it had closed before. Trade % is the
      trade's own result. No balances, amounts or prices are shown. Made with NFIForge.</p>
  </div>
</template>
