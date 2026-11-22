<script setup lang="ts">
import { esc } from "@/lib/format"
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { storeToRefs } from "pinia"
import { css, ecBase } from "@/components/charts/chartTheme"
import EChart from "@/components/charts/EChart.vue"
import PanelCard from "@/components/layout/PanelCard.vue"
import { useLive } from "@/stores/live"
import { useSettings } from "@/stores/settings"

// one time axis for the picked bot: events (alerts, trade events, actions), equity, open slots, server cpu and the
// bot's loop time. zoom or hover one and all follow. all from what nfiforge already keeps
const live = useLive()
const settings = useSettings()
const { picked } = storeToRefs(live)
const bot = computed(() => (picked.value && live.bots[picked.value] ? picked.value : Object.keys(live.bots)[0] ?? ""))
const RANGES: [string, number][] = [["6h", 6], ["24h", 24], ["7d", 168], ["30d", 720]]
const hours = ref(24)

type Pt = [number, number]
type Note = { ts: number; bot: string | null; kind: string; level: string; title: string }
const equity = ref<Pt[]>([])
const cpu = ref<Pt[]>([])
const loops = ref<Pt[]>([])
const notes = ref<Note[]>([])
const loading = ref(false)

async function load() {
  if (!bot.value) return
  loading.value = true
  const encodedName = encodeURIComponent(bot.value)
  const get = (url: string) => fetch(url).then((response) => (response.ok ? response.json() : null)).catch(() => null)
  const [equityData, srv, noteData] = await Promise.all([get(`/api/bots/${encodedName}/equity?hours=${hours.value}`), get(`/api/server/history?hours=${hours.value}`), get("/api/notifications?limit=1000")])
  equity.value = (equityData ?? []).map((point: any) => [point.ts * 1000, +point.equity.toFixed(2)])
  cpu.value = (srv?.host ?? []).map((sample: any) => [sample.ts * 1000, sample.cpu])
  loops.value = (srv?.loops ?? []).filter((loop: any) => loop.bot === bot.value).map((loop: any) => [loop.ts * 1000, loop.loop_s])
  notes.value = (noteData?.items ?? []).filter((note: Note) => !note.bot || note.bot === bot.value)
  loading.value = false
}
watch([bot, hours], load, { immediate: true })
const timer = setInterval(load, 60000)
onBeforeUnmount(() => clearInterval(timer))

const start = computed(() => Date.now() - hours.value * 3600000)
// open slots over time from the bot's trades (open ones from status): a step at every open and close
const slots = computed<Pt[]>(() => {
  const botState = live.bots[bot.value]
  const all = [...((botState?.trades?.trades ?? []) as any[]), ...((botState?.status ?? []) as any[])]
  const seen = new Set<number>()
  const steps: Pt[] = []
  let count = 0
  for (const trade of all) {
    if (seen.has(trade.trade_id) || !trade.open_timestamp) continue
    seen.add(trade.trade_id)
    const close = trade.is_open ? null : trade.close_timestamp
    if (trade.open_timestamp < start.value && (close == null || close > start.value)) count++
    else if (trade.open_timestamp >= start.value) steps.push([trade.open_timestamp, 1])
    if (close != null && close >= start.value) steps.push([close, -1])
  }
  const out: Pt[] = [[start.value, count]]
  for (const [ts, change] of steps.sort((a, b) => a[0] - b[0])) out.push([ts, (count += change)])
  out.push([Date.now(), count])
  return out
})
const events = computed(() => notes.value.filter((event) => event.ts * 1000 >= start.value))
const maxSlots = computed(() => Number(live.bots[bot.value]?.config?.max_open_trades) || undefined)

const option = computed(() => {
  const theme = ecBase(), utc = settings.s?.timezone !== "local"
  const LEVEL: Record<string, string> = { bad: css("--red"), warn: css("--amber"), info: css("--brand-b"), ok: css("--green") }
  // events strip on top, then four charts sharing one x axis
  const rows = [["events", 2, 6], ["equity", 12, 28], ["open slots", 44, 13], ["server CPU %", 61, 13], ["loop time (s)", 78, 13]] as const
  const grid = rows.map(([, top, height]) => ({ left: 54, right: 14, top: `${top}%`, height: `${height}%` }))
  const fmt = (ms: number) => new Date(ms).toLocaleString("en-GB", { timeZone: utc ? "UTC" : undefined, hour12: false, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
  const xAxis = rows.map((_, i) => ({
    type: "time", gridIndex: i, min: start.value, max: Date.now(), ...theme.axis,
    axisLabel: { ...theme.axis.axisLabel, show: i === rows.length - 1, formatter: (value: number) => fmt(value) },
    splitLine: { show: false },
  }))
  const yAxis = rows.map(([name], i) => ({
    type: "value", gridIndex: i, name, nameLocation: "end", nameGap: 4, nameTextStyle: { color: css("--text-dim"), fontSize: 10, align: "left", padding: [0, 0, 0, -50] },
    ...theme.valueAxis, scale: i === 1, show: i !== 0, splitNumber: 2, max: i === 2 ? maxSlots.value : i === 3 ? 100 : undefined, min: i === 0 ? 0 : undefined,
  }))
  const line = (i: number, data: Pt[], color: string, step = false) => ({
    type: "line", xAxisIndex: i, yAxisIndex: i, data, showSymbol: false, step: step ? "end" : undefined, sampling: "lttb",
    lineStyle: { width: 1.4, color }, areaStyle: { color, opacity: 0.08 },
  })
  return {
    animation: false,
    tooltip: { ...theme.tooltip, trigger: "axis", axisPointer: { type: "line", link: [{ xAxisIndex: "all" }] },
      formatter: (params: any[]) => {
        const lines = params.filter((param) => param.seriesName !== "events").map((param) => `${param.seriesName} ${typeof param.value[1] === "number" ? +param.value[1].toFixed(2) : param.value[1]}`)
        return params.length ? `${fmt(params[0].value[0])}<br/>${lines.join("<br/>")}` : ""
      } },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    dataZoom: [{ type: "inside", xAxisIndex: rows.map((_, i) => i) }],
    grid, xAxis, yAxis,
    series: [
      { name: "events", type: "scatter", xAxisIndex: 0, yAxisIndex: 0, symbolSize: 8,
        data: events.value.map((event) => ({ value: [event.ts * 1000, 0.5], e: event, itemStyle: { color: LEVEL[event.level] ?? css("--text-dim") } })),
        tooltip: { trigger: "item", formatter: (params: any) => `${fmt(params.value[0])}<br/>${esc(params.data.e.kind)}: ${esc(params.data.e.title)}` } },
      { name: "equity", ...line(1, equity.value, css("--brand-b")) },
      { name: "open slots", ...line(2, slots.value, css("--green"), true) },
      { name: "cpu %", ...line(3, cpu.value, css("--amber")) },
      { name: "loop s", ...line(4, loops.value, css("--red")) },
    ],
  }
})
</script>

<template>
  <PanelCard :title="`Timeline · ${bot}`">
    <template #actions>
      <span v-if="loading" class="text-xs text-faint">loading…</span>
      <span class="text-xs text-faint num">{{ events.length }} events</span>
      <div class="flex rounded-md border border-line overflow-hidden text-xs">
        <button v-for="[label, rangeHours] in RANGES" :key="label" class="px-2.5 py-1" :class="hours === rangeHours ? 'bg-raised text-ink' : 'text-dim hover:text-ink'" @click="hours = rangeHours">{{ label }}</button>
      </div>
    </template>
    <EChart :option="option" height="fill" />
  </PanelCard>
</template>
