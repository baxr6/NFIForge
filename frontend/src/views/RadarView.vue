<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { useRouter } from "vue-router"
import { storeToRefs } from "pinia"
import { useSettings } from "@/stores/settings"
import { useLive } from "@/stores/live"

// signal radar: every whitelisted pair's entry signals and the strategy's guards per candle, and what happened to each
// signal (traded, blocked and why, not taken). answers "why didn't the bot take that move"
const live = useLive()
const settings = useSettings()
const router = useRouter()
const utc = computed(() => settings.s?.timezone !== "local")
const radarBots = computed(() => Object.values(live.bots).filter((bot) => bot.radar).map((bot) => bot.name))
const { picked } = storeToRefs(live)
const bot = computed(() => (radarBots.value.includes(picked.value ?? "") ? picked.value! : radarBots.value[0] ?? ""))

// [ts s, side L/S/"", tag, outcome, reason, guards-off bitmask, candles (a guard-only run is one cell)]
type Cell = [number, string, string, string, string, number, number]
type View = { enabled: boolean; timeframe: string; seconds: number; swept: number | null; guards: string[]; pairs_watched: number; summary: Record<string, number>; pairs: Record<string, Cell[]> }
const view = ref<View | null>(null)
const error = ref("")

async function load() {
  if (!bot.value) return
  const response = await fetch(`/api/bots/${encodeURIComponent(bot.value)}/radar?hours=${win.value / 3600}`).catch(() => null)
  if (response?.ok) { view.value = await response.json(); error.value = "" } else error.value = response ? `radar failed (${response.status})` : "backend not reachable"
}

const GUARD_LABEL: Record<string, string> = {
  protections_long_global: "long protections", protections_short_global: "short protections",
  global_protections_long_pump: "long pump guard", global_protections_long_dump: "long dump guard",
  global_protections_short_pump: "short pump guard", global_protections_short_dump: "short dump guard",
}
const guardsOff = (mask: number) => (view.value?.guards ?? []).filter((_, i) => mask & (1 << i)).map((guard) => GUARD_LABEL[guard] ?? guard)

const WINDOWS: [string, number][] = [["1h", 3600], ["4h", 14400], ["12h", 43200], ["24h", 86400], ["3d", 259200], ["7d", 604800]]
const win = ref(14400)
watch([bot, win], load, { immediate: true })
const timer = setInterval(load, 30000)
onBeforeUnmount(() => clearInterval(timer))
const activeOnly = ref(true)
const now = ref(Date.now() / 1000)
const tick = setInterval(() => (now.value = Date.now() / 1000), 15000)
onBeforeUnmount(() => clearInterval(tick))
const start = computed(() => now.value - win.value)

// pairs with something in the window, most recent activity first
const rows = computed(() => {
  const out = Object.entries(view.value?.pairs ?? {}).map(([pair, cells]) => {
    const inWin = cells.filter((cell) => cell[0] >= start.value)
    return { pair, cells: inWin, last: inWin.length ? inWin[inWin.length - 1][0] : 0, signals: inWin.filter((cell) => cell[1]).length }
  })
  return out.filter((row) => !activeOnly.value || row.cells.length).sort((a, b) => b.signals - a.signals || b.last - a.last)
})
const latest = computed(() => rows.value.flatMap((row) => row.cells.filter((cell) => cell[1]).map((cell) => ({ pair: row.pair, c: cell }))).sort((a, b) => b.c[0] - a.c[0]).slice(0, 60))
const counts = computed(() => {
  const tally: Record<string, number> = {}
  for (const row of rows.value) for (const cell of row.cells) if (cell[1]) tally[cell[3]] = (tally[cell[3]] ?? 0) + 1
  return tally
})

const TONE: Record<string, string> = { traded: "bg-up", blocked: "bg-warn", "not taken": "bg-down", pending: "bg-brand-b" }
const LABEL: Record<string, string> = { traded: "traded", blocked: "blocked", "not taken": "not taken", pending: "this candle" }
const when = (time: number) => new Date(time * 1000).toLocaleString("en-GB", { timeZone: utc.value ? "UTC" : undefined, hour12: false, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
const left = (time: number) => `${((time - start.value) / win.value) * 100}%`
const width = (cell: Cell) => `max(3px, ${(((view.value?.seconds ?? 300) * (cell[6] ?? 1)) / win.value) * 100}%)`
function tip(pair: string, cell: Cell) {
  const guards = guardsOff(cell[5])
  const sig = cell[1] ? `${cell[1] === "S" ? "short" : "long"} · tag ${cell[2] || "–"} · ${LABEL[cell[3]] ?? cell[3]}${cell[4] ? `: ${cell[4]}` : ""}` : "no signal"
  const run = cell[6] > 1 ? ` (${cell[6]} candles)` : ""
  return `${pair} · ${when(cell[0])}${run}\n${sig}${guards.length ? `\nguards off: ${guards.join(", ")}` : ""}`
}
const openChart = (pair: string) => router.push({ path: "/chart", query: { bot: bot.value, pair, tf: "bot" } })
const ago = computed(() => (view.value?.swept ? Math.max(0, Math.round((now.value - view.value.swept) / 60)) : null))
const coin = (pair: string) => pair.split("/")[0]
</script>

<template>
  <div class="space-y-3">
    <div class="flex flex-wrap items-center gap-3">
      <h1 class="text-xl font-semibold">Signal Radar</h1>
      <select v-if="radarBots.length > 1" v-model="picked" class="rounded-md bg-raised border border-line px-2 py-1 text-ink text-sm">
        <option v-for="name in radarBots" :key="name" :value="name">{{ name }}</option></select>
      <span v-if="view?.enabled" class="text-sm text-dim num">{{ view.pairs_watched }} pairs · {{ view.timeframe }} · updated {{ ago == null ? "–" : `${ago} min ago` }}</span>
      <span v-if="error" class="text-sm text-down">{{ error }}</span>
    </div>

    <div v-if="!radarBots.length" class="panel p-6 text-dim text-sm">No bot has the signal radar on. Turn it on per bot in <b>Manage Bots → edit → Signal radar</b> (or <span class="num">radar: true</span> under the bot in config.yaml).</div>

    <template v-else-if="view?.enabled">
      <div class="panel p-3 flex flex-wrap gap-2 items-center text-xs">
        <span class="text-dim">guards now</span>
        <span v-for="guard in view.guards" :key="guard" class="px-2 py-0.5 rounded border num" :class="view.summary[guard] ? 'border-down/50 text-down' : 'border-line text-faint'"
          :title="view.summary[guard] ? `blocking on ${view.summary[guard]} pairs at the latest candle` : 'not blocking anywhere'">{{ GUARD_LABEL[guard] ?? guard }} {{ view.summary[guard] ? `· ${view.summary[guard]} pairs` : "✓" }}</span>
      </div>

      <div class="panel p-3 space-y-2">
        <div class="flex flex-wrap items-center gap-2 text-xs">
          <div class="flex rounded-md border border-line overflow-hidden">
            <button v-for="[label, seconds] in WINDOWS" :key="label" class="px-2.5 py-1" :class="win === seconds ? 'bg-raised text-ink' : 'text-dim hover:text-ink'" @click="win = seconds">{{ label }}</button>
          </div>
          <label class="flex items-center gap-1 text-dim"><input v-model="activeOnly" type="checkbox" /> only pairs with activity</label>
          <span class="ml-auto flex flex-wrap gap-3 text-dim">
            <span v-for="kind in ['traded', 'blocked', 'not taken', 'pending']" :key="kind" class="flex items-center gap-1"><span class="inline-block w-2.5 h-2.5 rounded-sm" :class="TONE[kind]" />{{ LABEL[kind] }} {{ counts[kind] ?? 0 }}</span>
            <span class="flex items-center gap-1"><span class="inline-block w-2.5 h-2.5 rounded-sm bg-[var(--red-dim)]" />guard off</span>
          </span>
        </div>
        <div v-if="!rows.length" class="py-6 text-center text-xs text-faint">no signals or guards in this window</div>
        <div v-for="row in rows" :key="row.pair" class="flex items-center gap-2 h-5">
          <button class="w-24 shrink-0 text-left text-xs num truncate hover:text-brand-b" :title="`open ${row.pair} on Chart`" @click="openChart(row.pair)">{{ coin(row.pair) }}</button>
          <div class="relative flex-1 h-3.5 rounded-sm bg-raised overflow-hidden">
            <span v-for="cell in row.cells" :key="cell[0]" class="absolute top-0 h-full cursor-pointer"
              :class="cell[1] ? TONE[cell[3]] : 'bg-[var(--red-dim)]'" :style="{ left: left(cell[0]), width: width(cell) }" :title="tip(row.pair, cell)" @click="openChart(row.pair)" />
          </div>
          <span class="w-8 shrink-0 text-right text-[11px] text-dim num">{{ row.signals || "" }}</span>
        </div>
        <div class="flex justify-between pl-26 text-[10px] text-faint num"><span>{{ when(start) }}</span><span>now</span></div>
      </div>

      <div class="panel p-3 overflow-auto">
        <div class="panel-title mb-2">Latest signals</div>
        <table class="w-full text-xs num">
          <thead class="text-faint text-left"><tr><th class="font-normal pb-1">candle</th><th class="font-normal">pair</th><th class="font-normal">side · tag</th><th class="font-normal">what happened</th></tr></thead>
          <tbody>
            <tr v-for="entry in latest" :key="`${entry.pair}-${entry.c[0]}`" class="border-t border-line">
              <td class="py-1 pr-2 whitespace-nowrap">{{ when(entry.c[0]) }}</td>
              <td class="pr-2"><button class="hover:text-brand-b" @click="openChart(entry.pair)">{{ coin(entry.pair) }}</button></td>
              <td class="pr-2" :class="entry.c[1] === 'S' ? 'text-down' : 'text-up'">{{ entry.c[1] === "S" ? "short" : "long" }} · {{ entry.c[2] || "–" }}</td>
              <td><span class="inline-block w-2 h-2 rounded-sm mr-1" :class="TONE[entry.c[3]]" />{{ LABEL[entry.c[3]] ?? entry.c[3] }}<span v-if="entry.c[4]" class="text-dim">: {{ entry.c[4] }}</span>
                <span v-if="guardsOff(entry.c[5]).length" class="text-down"> · guards off: {{ guardsOff(entry.c[5]).join(", ") }}</span></td>
            </tr>
            <tr v-if="!latest.length"><td colspan="4" class="py-4 text-center text-faint">no signals in this window</td></tr>
          </tbody>
        </table>
      </div>
    </template>
    <div v-else-if="view && !view.enabled" class="panel p-6 text-dim text-sm">The radar is off for {{ bot }}.</div>
  </div>
</template>
