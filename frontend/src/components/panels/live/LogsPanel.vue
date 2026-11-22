<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { RouterLink } from "vue-router"
import { storeToRefs } from "pinia"
import { useLive } from "@/stores/live"
import { useSettings } from "@/stores/settings"

// a bot's log, newest first: freqtrade keeps only its last 1000 lines, so while this page is open we poll and keep
// our own longer buffer. Level / kind / text filters, repeats grouped, pairs link to the chart
const live = useLive()
const settings = useSettings()
const utc = computed(() => settings.s?.timezone !== "local")

const botNames = computed(() => Object.keys(live.bots))
const { picked: botName } = storeToRefs(live)
const bot = computed(() => live.bots[botName.value ?? ""] ?? live.bots[botNames.value[0]])

// ===========================================================================
// BUFFER
// ===========================================================================
type Log = { ts: number; logger: string; level: string; msg: string; kind: Kind; n: number; first: number }
type Kind = "error" | "warning" | "trade" | "nfi" | "pairlist" | "system"
const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]
const rank = (level: string) => (level === "CRITICAL" ? 3 : Math.max(0, LEVELS.indexOf(level)))
const minLevel = ref("INFO")
const MAX = 20000  // the backend keeps the same
const lines = ref<Log[]>([])
const seen = new Set<string>()
const error = ref("")
const follow = ref(true)
const warning = ref("")

function kindOf(logger: string, level: string, msg: string): Kind {
  if (rank(level) >= 3) return "error"
  if (level === "WARNING") return "warning"
  if (logger.startsWith("NostalgiaForInfinity")) return "nfi"
  if (/Exit for|signal found|[Oo]rder|Position adjust|DCA|[Gg]rind|[Dd]e-?risk|open trade|denied|stop_?loss|entry|Entry/.test(msg)) return "trade"
  if (/pairlist|Filter|PairList/i.test(logger) || /whitelist|blacklist/i.test(msg)) return "pairlist"
  return "system"
}

async function poll(full = false) {
  if (!bot.value) return
  full ||= !lines.value.length  // nothing yet: ask for everything the backend kept
  const debug = minLevel.value === "DEBUG"
  const response = await fetch(`/api/bots/${encodeURIComponent(bot.value.name)}/logs?limit=${full ? MAX : 1000}&debug=${debug}`).catch(() => null)
  if (!response?.ok) { error.value = response ? (await response.json().catch(() => ({}))).detail ?? response.statusText : "backend unreachable"; return }
  const body = await response.json()
  warning.value = body.warning ?? ""
  error.value = ""
  const fresh: Log[] = []
  for (const [, ts, logger, level, msg] of body.logs as [string, number, string, string, string][]) {
    if (rank(level) < rank(minLevel.value)) continue
    const key = `${ts}|${logger}|${msg}`
    if (seen.has(key)) continue
    seen.add(key)
    fresh.push({ ts, logger, level, msg, kind: kindOf(logger, level, msg), n: 1, first: ts })
  }
  if (!fresh.length) return
  const all = [...lines.value, ...fresh].sort((a, b) => a.ts - b.ts)
  lines.value = all.slice(-MAX)
  if (seen.size > MAX * 3) { seen.clear(); for (const line of lines.value) seen.add(`${line.ts}|${line.logger}|${line.msg}`) }
}
function reset() { lines.value = []; seen.clear(); poll(true) }
watch([() => bot.value?.name, minLevel], reset, { immediate: true })
let timer = 0
onMounted(() => (timer = window.setInterval(() => follow.value && poll(), 3000)))
onBeforeUnmount(() => clearInterval(timer))

// ===========================================================================
// FILTERS
// ===========================================================================
const KINDS: [Kind, string][] = [["trade", "trades"], ["nfi", "NFI"], ["warning", "warnings"], ["error", "errors"], ["pairlist", "pairlist"], ["system", "system"]]
const kinds = ref<Set<Kind>>(new Set(KINDS.map(([kind]) => kind)))
function toggleKind(kind: Kind) { const next = new Set(kinds.value); if (next.has(kind)) next.delete(kind); else next.add(kind); kinds.value = next }
const only = (kind: Kind) => (kinds.value = new Set([kind]))
const search = ref("")
const group = ref(true)
const counts = computed(() => {
  const tally: Record<string, number> = {}
  for (const line of lines.value) tally[line.kind] = (tally[line.kind] ?? 0) + 1
  return tally
})
const shown = computed(() => {
  const needle = search.value.trim().toLowerCase()
  const matching = lines.value.filter((line) => kinds.value.has(line.kind) && (!needle || line.msg.toLowerCase().includes(needle) || line.logger.toLowerCase().includes(needle)))
  if (!group.value) return matching.slice().reverse().slice(0, 1500)
  // same logger + level + message shown once, at its latest time, with how often and since when
  const grouped = new Map<string, Log>()
  for (const line of matching) {
    const key = `${line.logger}|${line.level}|${line.msg}`
    const group = grouped.get(key)
    grouped.set(key, group ? { ...line, n: group.n + 1, first: group.first } : { ...line })
  }
  return [...grouped.values()].sort((a, b) => b.ts - a.ts).slice(0, 1500)
})
const span = computed(() => (lines.value.length ? (lines.value[lines.value.length - 1].ts - lines.value[0].ts) / 60 : 0))

// ===========================================================================
// DISPLAY
// ===========================================================================
const time = (ts: number) => new Date(ts * 1000).toLocaleTimeString("en-GB", { timeZone: utc.value ? "UTC" : undefined, hour12: false })
const day = (ts: number) => new Date(ts * 1000).toLocaleDateString("en-GB", { timeZone: utc.value ? "UTC" : undefined, day: "2-digit", month: "short" })
const short = (logger: string) => logger.replace(/^freqtrade\./, "")
const PAIR = /([A-Z0-9]{2,20}\/[A-Z]{3,5}(?::[A-Z]{3,5})?)/
const parts = (msg: string) => msg.split(PAIR).map((text, i) => ({ t: text, pair: i % 2 === 1 }))
const kindStyle: Record<Kind, string> = {
  error: "bg-down", warning: "bg-warn", trade: "bg-brand-b", nfi: "bg-brand-a", pairlist: "bg-faint", system: "bg-line-bright",
}
const kindColor: Record<Kind, string> = {
  error: "var(--red)", warning: "var(--amber)", trade: "var(--brand-b)", nfi: "var(--brand-a)", pairlist: "var(--text-faint)", system: "var(--line-bright)",
}
const levelStyle = (level: string) => (rank(level) >= 3 ? "text-down" : level === "WARNING" ? "text-warn" : level === "DEBUG" ? "text-faint" : "text-dim")
const sel = "rounded-md bg-raised border border-line px-2 py-1 text-ink text-sm"
</script>

<template>
  <div class="flex flex-col gap-3 h-full min-h-0">
    <div class="flex flex-wrap items-baseline gap-3">
      <span class="text-sm text-dim num">{{ lines.length }} lines · last {{ span < 90 ? `${Math.round(span)} min` : `${(span / 60).toFixed(1)} h` }}</span>
      <span v-if="warning" class="text-xs text-warn" title="freqtrade's api keeps only its last 1000 lines; at debug level that is under a second, so lines between reads are lost. Running the bot without -v fixes it">⚠ {{ warning }}</span>
      <span v-if="error" class="text-sm text-down">{{ error }}</span>
      <button class="ml-auto text-xs px-3 py-1 rounded-md border border-line" :class="follow ? 'text-up border-up/40' : 'text-dim'" @click="follow = !follow">
        {{ follow ? "● live" : "❚❚ paused" }}</button>
    </div>

    <div class="panel p-3 flex flex-wrap gap-2 items-center text-sm">
      <select v-if="botNames.length > 1" v-model="botName" :class="sel"><option v-for="name in botNames" :key="name" :value="name">{{ name }}</option></select>
      <select v-model="minLevel" :class="sel" title="lowest level kept"><option v-for="level in LEVELS" :key="level" :value="level">{{ level }}{{ level === "ERROR" ? "" : " and up" }}</option></select>
      <input v-model="search" placeholder="search text or pair" :class="sel" class="w-52" />
      <div class="flex flex-wrap gap-1">
        <button v-for="[kind, label] in KINDS" :key="kind" class="flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs"
          :class="kinds.has(kind) ? 'border-line-bright text-ink' : 'border-line text-faint'" :title="'click: toggle · double-click: only this'"
          @click="toggleKind(kind)" @dblclick="only(kind)">
          <span class="w-2 h-2 rounded-full" :class="kindStyle[kind]" />{{ label }} <span class="num text-faint">{{ counts[kind] ?? 0 }}</span>
        </button>
      </div>
      <label class="flex items-center gap-1 text-dim text-xs ml-auto"><input v-model="group" type="checkbox" /> group repeats</label>
    </div>

    <div class="panel flex-1 min-h-0 overflow-auto num text-[12px] leading-5">
      <!-- phone: time, level, logger, count on one line and the message under it; wider: one line per entry -->
      <div v-for="line in shown" :key="`${line.ts}|${line.logger}|${line.msg}`" class="flex flex-wrap items-baseline gap-x-3 pl-2.5 pr-3 py-1 sm:py-0.5 border-b border-l-2 border-b-line/50 hover:bg-hover"
        :style="{ borderLeftColor: kindColor[line.kind] }">
        <span class="text-faint whitespace-nowrap" :title="day(line.ts)">{{ time(line.ts) }}</span>
        <span class="sm:w-16 shrink-0" :class="levelStyle(line.level)">{{ line.level }}</span>
        <span class="min-w-0 max-w-[45%] sm:max-w-none sm:w-36 shrink truncate text-faint" :title="line.logger">{{ short(line.logger) }}</span>
        <span v-if="line.n > 1" class="ml-auto sm:ml-0 sm:order-last shrink-0 text-warn whitespace-nowrap" :title="`first ${time(line.first)}`">×{{ line.n }}</span>
        <span class="basis-full sm:basis-0 sm:flex-1 min-w-0 break-words" :class="line.kind === 'nfi' || line.kind === 'trade' ? 'text-ink' : 'text-dim'">
          <template v-for="(part, i) in parts(line.msg)" :key="i"><RouterLink v-if="part.pair" :to="{ path: '/chart', query: { bot: bot?.name, pair: part.t } }" class="text-brand-b hover:underline">{{ part.t }}</RouterLink><template v-else>{{ part.t }}</template></template>
        </span>
      </div>
      <div v-if="!shown.length" class="p-8 text-center text-dim">{{ lines.length ? "nothing matches" : "waiting for log lines…" }}</div>
    </div>
  </div>
</template>
