<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { storeToRefs } from "pinia"
import FootprintChart from "@/components/orderflow/FootprintChart.vue"
import type { CellStyle, Overlays } from "@/components/orderflow/footprintSeries"
import {
  autoFactor, cvd, dayProfiles, developing, DEFAULTS, fundingAt, MARK_INFO, marks, oiReads, parse, parseDerivs, parseHeat, profile, read, short,
  stats, zones as findZones, BANDS, type Bar, type Data, type Derivs, type Heat, type MarkKind,
} from "@/lib/orderflow"
import { useHistory } from "@/lib/history"
import { overlay, pairMarks, type Trade } from "@/lib/trades"
import { look, pair, TF_SEC } from "@/lib/orderflowState"
import { useLive } from "@/stores/live"
import { wide } from "@/lib/viewport"

// footprint of one pair on the selected bot's exchange: recorded live by the order flow worker from when the pair is
// first opened here (or traded), history filled back from the exchange's archives / api
const live = useLive()
const route = useRoute()
const router = useRouter()

// ===========================================================================
// BOT / PAIR / TIMEFRAME / LOOK (saved in this browser)
// ===========================================================================
const botNames = computed(() => Object.keys(live.bots))
const { picked: botName } = storeToRefs(live)
if (route.query.bot) botName.value = String(route.query.bot)
const bot = computed(() => live.bots[botName.value ?? ""] ?? live.bots[botNames.value[0]])
const pairs = computed(() => {
  const open = ((bot.value?.status ?? []) as { pair: string }[]).map((trade) => trade.pair)
  const wl = ((bot.value?.whitelist?.whitelist ?? []) as string[]).filter((name) => !open.includes(name))
  return { open: [...new Set(open)], wl }
})
if (route.query.pair) pair.value = String(route.query.pair)
watch(pairs, (lists) => { if (!pair.value) pair.value = lists.open[0] ?? lists.wl[0] ?? "" }, { immediate: true })
const TFS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
const STYLES: { v: CellStyle; label: string; title: string }[] = [
  { v: "bidask", label: "bid × ask", title: "sold into the bid × bought at the ask, per price" },
  { v: "delta", label: "delta", title: "bought minus sold, per price" },
  { v: "volume", label: "volume", title: "volume per price" },
  { v: "trades", label: "trades", title: "number of sells × buys, per price" },
  { v: "profile", label: "profile", title: "volume profile inside each bar, sells red, buys green" },
]
const ROWS = [0, 1, 2, 5, 10, 20, 50, 100]

if (route.query.tf && TF_SEC[String(route.query.tf)]) look.tf = String(route.query.tf)
watch([botName, pair, () => look.tf], () => {
  if (route.path === "/orderflow") router.replace({ query: { ...route.query, bot: bot.value?.name, pair: pair.value, tf: look.tf } })
})
const settings = computed(() => ({ ratio: look.ratio, minVol: look.minVol, stack: look.stack, va: DEFAULTS.va }))

// ===========================================================================
// DATA: full load on a new pair / timeframe, then the newest bars every 2 s
// ===========================================================================
const data = ref<Data | null>(null)
const error = ref("")
const loading = ref(false)
let seq = 0

async function fetchBars(start?: number): Promise<Data> {
  const query = new URLSearchParams({ bot: bot.value!.name, pair: pair.value, tf: look.tf })
  if (start) query.set("start", String(start))
  const response = await fetch(`/api/orderflow/bars?${query}`)
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail ?? response.statusText)
  return parse(await response.json())
}

async function load() {
  if (!bot.value || !pair.value) return
  const ticket = ++seq
  loading.value = true
  try {
    const loaded = await fetchBars()
    if (ticket !== seq) return
    data.value = loaded
    error.value = ""
  } catch (e) {
    if (ticket === seq) error.value = String((e as Error).message ?? e)
  } finally {
    if (ticket === seq) loading.value = false
  }
}

async function refresh() {
  const current = data.value
  if (!bot.value || !pair.value || loading.value) return
  if (!current || current.pending || !current.bars.length) return load()
  const ticket = seq
  try {
    const last = current.bars[current.bars.length - 1].t
    const newer = await fetchBars(last)
    if (ticket !== seq || data.value !== current) return
    // history filled in since: load everything again
    if (JSON.stringify(newer.cover.slice(0, -1)) !== JSON.stringify(current.cover.slice(0, -1)) || newer.cover.length !== current.cover.length) return load()
    data.value = { ...current, bars: [...current.bars.filter((bar) => bar.t < last), ...newer.bars], big: [...current.big.filter((trade) => trade[0] / 1000 < last), ...newer.big], cover: newer.cover }
    error.value = ""
  } catch (e) {
    error.value = String((e as Error).message ?? e)
  }
}
watch([() => bot.value?.name, pair, () => look.tf], () => { data.value = null; load() }, { immediate: true })

// open interest, liquidations, funding (perpetuals): with each full load, then every 10 s
const derivs = ref<Derivs | null>(null)
let derivSeq = 0
async function loadDerivs() {
  const current = data.value
  if (!bot.value || !pair.value || current?.market !== "swap" || (!look.oi && !look.liq)) { derivs.value = null; return }
  const ticket = ++derivSeq
  const query = new URLSearchParams({ bot: bot.value.name, pair: pair.value, tf: look.tf })
  const response = await fetch(`/api/orderflow/derivs?${query}`).catch(() => null)
  if (ticket === derivSeq && response?.ok) derivs.value = parseDerivs(await response.json())
}
watch(() => [data.value?.market, look.oi, look.liq], loadDerivs)

// the spot pair on the same exchange (spot vs perp delta): with each full load, then every 10 s
const spotPair = computed(() => pair.value.replace(/:.*$/, ""))
const spotBars = ref<Bar[] | null>(null)
let spotSeq = 0
async function loadSpot() {
  if (!bot.value || !pair.value || data.value?.market !== "swap" || !look.spotCvd) { spotBars.value = null; return }
  const ticket = ++spotSeq
  const query = new URLSearchParams({ bot: bot.value.name, pair: spotPair.value, tf: look.tf, market: "spot" })
  const response = await fetch(`/api/orderflow/bars?${query}`).catch(() => null)
  if (ticket === spotSeq && response?.ok) spotBars.value = parse(await response.json()).bars
}
watch(() => [data.value?.market, look.spotCvd], loadSpot)
watch([() => bot.value?.name, pair, () => look.tf], () => (spotBars.value = null))
watch([() => bot.value?.name, pair, () => look.tf], () => (derivs.value = null))
let timer = 0, statusTimer = 0
let derivTimer = 0
onMounted(() => {
  timer = window.setInterval(refresh, 2000); statusTimer = window.setInterval(loadStatus, 5000)
  derivTimer = window.setInterval(() => { loadDerivs(); loadSpot() }, 10_000)
  loadStatus()
})
onBeforeUnmount(() => { clearInterval(timer); clearInterval(statusTimer); clearInterval(derivTimer) })

// ===========================================================================
// BOOK HEATMAP for what the chart shows: columns sized to the screen (a few px each), refetched on scroll / zoom
// and every 5 s
// ===========================================================================
const heat = ref<Heat | null>(null)
const view = ref<{ from: number; to: number; barPx: number; rowPx: number } | null>(null)
let heatSeq = 0, viewTimer = 0
async function loadHeat() {
  const visible = view.value
  if (!look.heat && !look.walls && !look.imb) { heat.value = null; return }
  if (!bot.value || !pair.value || !visible || !step.value) return
  const ticket = ++heatSeq
  const perBar = Math.max(1, Math.min(tfSec.value / 10, Math.floor(visible.barPx / 3)))  // the book is kept per 10 s
  const rows = Math.max(1, [1, 2, 5, 10, 20, 50, 100, 200].find((merge) => visible.rowPx * merge >= 2) ?? 200)
  const sec = tfSec.value
  const query = new URLSearchParams({ bot: bot.value.name, pair: pair.value, tf: look.tf, start: String(visible.from - sec), end: String(visible.to + 2 * sec), per_bar: String(perBar), rows: String(rows) })
  const response = await fetch(`/api/orderflow/heat?${query}`).catch(() => null)
  if (ticket !== heatSeq || !response?.ok) return
  heat.value = parseHeat(await response.json())
}
function onView(visible: { from: number; to: number; barPx: number; rowPx: number }) {
  view.value = visible
  clearTimeout(viewTimer)
  viewTimer = window.setTimeout(loadHeat, 250)
}
watch(() => [look.heat, look.walls, look.imb], loadHeat)
watch([() => bot.value?.name, pair, () => look.tf], () => (heat.value = null))
let heatTimer = 0
onMounted(() => (heatTimer = window.setInterval(loadHeat, 5000)))
onBeforeUnmount(() => { clearInterval(heatTimer); clearTimeout(viewTimer) })

// ===========================================================================
// WORKER STATUS FOR THIS PAIR
// ===========================================================================
const status = ref<any>(null)
async function loadStatus() {
  const response = await fetch("/api/orderflow/status").catch(() => null)
  status.value = response?.ok ? await response.json() : null
}
const spotStatus = computed(() => (look.spotCvd ? ((status.value?.worker?.pairs ?? []) as any[]).find((entry) => entry.symbol === spotPair.value && entry.market === "spot") ?? null : null))
const pairStatus = computed(() => {
  const current = data.value
  const workerPairs = (status.value?.worker?.pairs ?? []) as any[]
  return workerPairs.find((entry) => entry.symbol === pair.value && (!current || (entry.exchange === current.exchange && entry.market === current.market))) ?? null
})

// ===========================================================================
// READS
// ===========================================================================
const bars = computed(() => data.value?.bars ?? [])
const step = computed(() => data.value?.step ?? 0)
const tfSec = computed(() => TF_SEC[look.tf])
// zones and stats use the row size picked, or 1 (stored rows) on auto
const factor = computed(() => look.rows || 1)
const zoneList = computed(() => (look.zones && step.value ? findZones(bars.value, factor.value, step.value, settings.value) : []))
// bars that follow a hole in the recorded history: the time between them and the bar before isn't all recorded
// (quiet minutes inside a recorded range have no bar but are no hole)
const gaps = computed(() => {
  const current = data.value
  if (!current) return []
  const tfMs = tfSec.value * 1000
  const out: number[] = []
  for (let index = 1; index < current.bars.length; index++) {
    const expected = current.bars[index - 1].t * 1000 + tfMs, actual = current.bars[index].t * 1000
    if (expected < actual && !current.cover.some((cover) => cover.start <= expected && cover.end >= actual)) out.push(current.bars[index].t)
  }
  return out
})
const hover = ref<{ bar: Bar | null; price: number | null }>({ bar: null, price: null })
const shown = computed(() => hover.value.bar ?? bars.value[bars.value.length - 1] ?? null)
const barStats = computed(() => {
  const bar = shown.value
  if (!bar || !step.value) return null
  return stats(bar, read(bar, factor.value, settings.value), step.value * factor.value, data.value?.big ?? [], tfSec.value)
})
const atPrice = computed(() => {
  const bar = hover.value.bar, price = hover.value.price
  if (!bar || price == null || !step.value) return null
  const size = step.value * factor.value
  const row = read(bar, factor.value, settings.value).rows.find((candidate) => candidate.i === Math.floor(price / size))
  return row ? { price: row.i * size, ...row } : null
})
// ===========================================================================
// PROFILES, VWAP, MARKS, BIG TRADES
// ===========================================================================
// profile rows: the picked size, else ~3 px rows at the current zoom
const profileFactor = computed(() => look.rows || (view.value ? autoFactor(view.value.rowPx, 3) : 1))
// bars picked on the chart: the anchored VWAP's first bar, a range profile's first and last
const anchor = ref<number | null>(null)
const range = ref<[number, number] | null>(null)
const tool = ref<"" | "anchor" | "range" | "range2">("")
let rangeFirst = 0
watch([() => bot.value?.name, pair], () => { anchor.value = null; range.value = null; tool.value = "" })
watch(() => look.profile, (mode) => { if (mode === "range" && !range.value) tool.value = "range" })
function onPick(time: number) {
  if (tool.value === "anchor") { anchor.value = time; tool.value = "" }
  else if (tool.value === "range") { rangeFirst = time; tool.value = "range2" }
  else if (tool.value === "range2") { range.value = [Math.min(rangeFirst, time), Math.max(rangeFirst, time)]; tool.value = "" }
}
const profiles = computed(() => {
  const barList = bars.value, settingsNow = settings.value, visible = view.value
  if (!step.value || !barList.length) return []
  if (look.profile === "day") return dayProfiles(barList, profileFactor.value, step.value, settingsNow)
  let result = null
  if (look.profile === "range" && range.value) {
    const [from, to] = range.value, sel = barList.filter((bar) => bar.t + tfSec.value > from && bar.t <= to)
    if (sel.length) result = profile(sel, profileFactor.value, step.value, settingsNow, sel[0].t, sel[sel.length - 1].t)
  } else if (look.profile === "visible" && visible) result = profile(barList.filter((bar) => bar.t >= visible.from && bar.t <= visible.to), profileFactor.value, step.value, settingsNow)
  return result ? [result] : []
})
const levels = computed(() => (step.value && (look.dev || look.vwap) ? developing(bars.value, profileFactor.value, step.value, settings.value, true) : []))
const anchored = computed(() => {
  const anchorTime = anchor.value
  return anchorTime != null && step.value ? developing(bars.value.filter((bar) => bar.t + tfSec.value > anchorTime), profileFactor.value, step.value, settings.value, false) : []
})
const markOn = computed<Record<string, boolean>>(() => ({ ua: look.ua, exh: look.exh, abs: look.abs, div: look.div }))
const markList = computed(() => {
  if (!look.ua && !look.exh && !look.abs && !look.div) return []
  return marks(bars.value, factor.value, settings.value, cvd(bars.value, false)).filter((mark) => markOn.value[mark.kind.split("-")[0]])
})
const bigList = computed(() => {
  const current = data.value
  if (!look.bubbles || !current) return []
  const min = Math.max(current.bigUsd, look.bigMin || 0)
  return current.big.filter((trade) => trade[1] * trade[2] >= min)
})
const overlays = computed<Overlays>(() => ({
  profiles: profiles.value, split: look.split, levels: levels.value, dev: look.dev, vwap: look.vwap, bands: look.bands,
  anchored: anchored.value, marks: markList.value, cot: look.cot, big: bigList.value, bigUsd: Math.max(data.value?.bigUsd ?? 0, look.bigMin || 0),
}))
const oiByBar = computed(() => (look.oi && derivs.value?.oi.size ? oiReads(bars.value, derivs.value.oi) : null))

// the bot's trades on this pair: the open one with its lines, every other one as marks
const { all: history } = useHistory()
const openTrades = computed(() => ((bot.value?.status ?? []) as Trade[]).filter((trade) => trade.pair === pair.value))
const tradeOv = computed(() => (look.trades && openTrades.value[0] ? overlay(openTrades.value[0], tfSec.value) : undefined))
const tradeMarks = computed(() => (look.trades
  ? pairMarks(history.value.filter((trade) => trade._bot === bot.value?.name && trade.pair === pair.value), openTrades.value.slice(1), tfSec.value)
  : []))

const shownMarks = computed(() => markList.value.filter((mark) => mark.t === shown.value?.t))
const shownDerivs = computed(() => {
  const bar = shown.value, current = derivs.value
  if (!bar || !current) return null
  return { oi: oiByBar.value?.get(bar.t) ?? null, liq: current.liq.get(bar.t) ?? null, funding: fundingAt(current.funding, bar.t + tfSec.value) }
})
const fmtPct = (rate: number) => `${(rate * 100).toFixed(4)}%`
const MARK_NAME: Record<MarkKind, string> = {
  "ua-high": "unfinished auction high", "ua-low": "unfinished auction low", "exh-high": "exhaustion high", "exh-low": "exhaustion low",
  "abs-high": "absorption high", "abs-low": "absorption low", "div-bear": "bearish delta divergence", "div-bull": "bullish delta divergence",
}
const markTip = (kind: string) => `${MARK_INFO[`${kind}-high` as MarkKind] ?? MARK_INFO["div-bear"]}. ${MARK_INFO[`${kind}-low` as MarkKind] ?? MARK_INFO["div-bull"]}`
const fmtTime = (time: number) => new Date(time * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
const fmtMs = (ms: number) => fmtTime(ms / 1000)
const fmtP = (price: number) => (step.value ? price.toFixed(Math.max(0, Math.ceil(-Math.log10(step.value) - 1e-9))) : String(price))
const historyFrom = computed(() => data.value?.cover[0] ?? null)
const title = computed(() => `${pair.value} · ${look.tf} · ${data.value?.exchange ?? ""} ${data.value?.market ?? ""}`)
// the two rows of switches: open on desktop, folded on phones so the chart gets the screen
const layers = ref(wide.value)
const sel = "rounded-md bg-raised border border-line px-2 py-1 text-ink text-sm"
const seg = (on: boolean) => (on ? "bg-raised text-ink" : "text-dim hover:text-ink")
</script>

<template>
  <div class="flex flex-col gap-3 h-full min-h-0">
    <div class="panel p-3 flex flex-wrap gap-2 items-center">
      <select v-if="botNames.length > 1" v-model="botName" :class="sel"><option v-for="name in botNames" :key="name" :value="name">{{ name }}</option></select>
      <select v-model="pair" :class="sel" class="max-w-56">
        <optgroup v-if="pairs.open.length" label="open trades"><option v-for="pairName in pairs.open" :key="pairName" :value="pairName">● {{ pairName }}</option></optgroup>
        <optgroup label="whitelist"><option v-for="pairName in pairs.wl" :key="pairName" :value="pairName">{{ pairName }}</option></optgroup>
      </select>
      <div class="flex rounded-md border border-line overflow-hidden text-sm">
        <button v-for="timeframe in TFS" :key="timeframe" class="px-2.5 py-1" :class="seg(look.tf === timeframe)" @click="look.tf = timeframe">{{ timeframe }}</button>
      </div>
      <div v-if="layers || wide" class="flex rounded-md border border-line overflow-hidden text-sm">
        <button v-for="style in STYLES" :key="style.v" class="px-2.5 py-1" :class="seg(look.style === style.v)" :title="style.title" @click="look.style = style.v">{{ style.label }}</button>
      </div>
      <label v-if="layers || wide" class="text-xs text-dim flex items-center gap-1" title="price rows merged; auto keeps the numbers readable as you zoom">rows
        <select v-model.number="look.rows" :class="sel" class="text-xs"><option v-for="merge in ROWS" :key="merge" :value="merge">{{ merge ? `${merge}× (${short(step * merge)})` : "auto" }}</option></select>
      </label>
      <span v-if="loading" class="text-xs text-faint">loading…</span>
      <span v-if="error" class="text-xs text-down">{{ error }}</span>
      <button class="ml-auto text-xs px-3 py-1 rounded-md border border-line text-dim hover:text-ink" title="show / hide the switches" @click="layers = !layers">layers {{ layers ? "▾" : "▸" }}</button>
      <button class="text-xs px-3 py-1 rounded-md border border-line text-dim hover:text-ink" @click="load">↻</button>
    </div>

    <div v-if="layers" class="panel p-3 flex flex-wrap gap-x-4 gap-y-2 items-center text-xs">
      <label class="flex items-center gap-1 text-dim"><input v-model="look.poc" type="checkbox" /> POC</label>
      <label class="flex items-center gap-1 text-dim"><input v-model="look.va" type="checkbox" /> value area</label>
      <label class="flex items-center gap-1 text-dim"><input v-model="look.zones" type="checkbox" /> stacked zones</label>
      <label class="flex items-center gap-1 text-dim" title="cumulative delta restarts each UTC day"><input v-model="look.session" type="checkbox" /> CVD per day</label>
      <label class="flex items-center gap-1 text-dim" title="one side at least this many times the other, one row away">imbalance
        <select v-model.number="look.ratio" :class="sel" class="text-xs"><option v-for="ratio in [1.5, 2, 2.5, 3, 4, 5]" :key="ratio" :value="ratio">{{ ratio * 100 }}%</option></select>
      </label>
      <label class="flex items-center gap-1 text-dim" title="this many imbalances in a row make a stacked zone">stacked
        <select v-model.number="look.stack" :class="sel" class="text-xs"><option v-for="count in [2, 3, 4, 5]" :key="count" :value="count">{{ count }}</option></select>
      </label>
      <label class="flex items-center gap-1 text-dim" title="ignore imbalances smaller than this (base units)">min vol
        <input v-model.number="look.minVol" type="number" min="0" step="any" :class="sel" class="w-20 text-xs" />
      </label>
      <span class="w-px h-4 bg-line" />
      <label class="flex items-center gap-1 text-dim" title="resting orders over time, brighter = more size"><input v-model="look.heat" type="checkbox" /> book heatmap</label>
      <label v-if="look.heat" class="flex items-center gap-1 text-dim" title="heatmap brightness">contrast
        <input v-model.number="look.contrast" type="range" min="0.3" max="3" step="0.1" class="w-20" />
      </label>
      <label v-if="look.heat" class="flex items-center gap-1 text-dim" title="brightness by the log of the size: small orders show too, walls stand out less"><input v-model="look.heatLog" type="checkbox" /> log</label>
      <label v-if="look.heat" class="flex items-center gap-1 text-dim" :title="`resting size (base units) shown at full brightness; empty = auto (now ${short(heat?.scale ?? 0)}, the 99.5th percentile on screen)`">full at
        <input type="number" min="0" step="any" :value="look.heatMax || ''" :placeholder="`auto ${short(heat?.scale ?? 0)}`" :class="sel" class="w-24 text-xs"
          @change="look.heatMax = Number(($event.target as HTMLInputElement).value) || 0" />
      </label>
      <label class="flex items-center gap-1 text-dim" :title="`large resting orders (at least $${short(heat?.wallUsd ?? 0)}): ○ appeared, × pulled, ● filled`"><input v-model="look.walls" type="checkbox" /> large orders</label>
      <label class="flex items-center gap-1 text-dim" title="bid vs ask value within this distance of the mid: +100% all bids, -100% all asks"><input v-model="look.imb" type="checkbox" /> book imbalance
        <select v-model.number="look.band" :class="sel" class="text-xs"><option v-for="(band, i) in BANDS" :key="band" :value="i">±{{ band * 100 }}%</option></select>
      </label>
    </div>

    <div v-if="layers" class="panel p-3 flex flex-wrap gap-x-4 gap-y-2 items-center text-xs">
      <label class="flex items-center gap-1 text-dim" title="volume per price over the bars on screen (drawn on the right), each UTC day, or a range of bars you pick; amber = POC, violet lines = value area, solid = high volume nodes, dashed = low volume nodes">profile
        <select v-model="look.profile" :class="sel" class="text-xs">
          <option value="off">off</option><option value="visible">on screen</option><option value="day">each day</option><option value="range">range</option>
        </select>
      </label>
      <select v-if="look.profile !== 'off'" v-model="look.split" :class="sel" class="text-xs" title="profile rows: sells (red) | buys (green), or bought minus sold">
        <option value="bidask">sells | buys</option><option value="delta">delta</option>
      </select>
      <button v-if="look.profile === 'range'" class="px-2 py-0.5 rounded-md border" :class="tool.startsWith('range') ? 'border-warn text-warn' : 'border-line text-dim hover:text-ink'" @click="tool = tool.startsWith('range') ? '' : 'range'">
        {{ tool === "range" ? "click the first bar…" : tool === "range2" ? "now the last bar…" : "pick range" }}
      </button>
      <span class="w-px h-4 bg-line" />
      <label class="flex items-center gap-1 text-dim" title="the day's (UTC) POC and value area so far, bar by bar"><input v-model="look.dev" type="checkbox" /> developing POC / VA</label>
      <label class="flex items-center gap-1 text-dim" title="volume-weighted average price of the day (UTC), from every traded price row"><input v-model="look.vwap" type="checkbox" /> VWAP</label>
      <button class="px-2 py-0.5 rounded-md border" :class="tool === 'anchor' ? 'border-warn text-warn' : 'border-line text-dim hover:text-ink'" title="VWAP from a bar you click (white line)" @click="tool = tool === 'anchor' ? '' : 'anchor'">
        {{ tool === "anchor" ? "click a bar…" : anchor != null ? "move anchored VWAP" : "anchored VWAP" }}
      </button>
      <button v-if="anchor != null" class="text-dim hover:text-ink" title="remove the anchored VWAP" @click="anchor = null">×</button>
      <label v-if="look.vwap || anchor != null" class="flex items-center gap-1 text-dim" title="standard deviation bands around the VWAP lines">bands
        <select v-model.number="look.bands" :class="sel" class="text-xs"><option :value="0">none</option><option :value="1">±1σ</option><option :value="2">±1σ, ±2σ</option></select>
      </label>
      <span class="w-px h-4 bg-line" />
      <label class="flex items-center gap-1 text-dim" :title="markTip('ua')"><input v-model="look.ua" type="checkbox" /> <span class="text-warn">○</span> unfinished auctions</label>
      <label class="flex items-center gap-1 text-dim" :title="markTip('exh')"><input v-model="look.exh" type="checkbox" /> ▼ exhaustion</label>
      <label class="flex items-center gap-1 text-dim" :title="markTip('abs')"><input v-model="look.abs" type="checkbox" /> <span class="text-brand-a">■</span> absorption</label>
      <label class="flex items-center gap-1 text-dim" :title="markTip('div')"><input v-model="look.div" type="checkbox" /> <span class="text-down">◆</span> delta divergence</label>
      <label class="flex items-center gap-1 text-dim" title="running delta at the moment the bar made its high (above it) and its low (below it); shown when the numbers fit"><input v-model="look.cot" type="checkbox" /> delta at high / low</label>
      <span class="w-px h-4 bg-line" />
      <label class="flex items-center gap-1 text-dim" :title="`single trades of at least $${short(Math.max(data?.bigUsd ?? 0, look.bigMin || 0))}, sized by value, green bought / red sold`"><input v-model="look.bubbles" type="checkbox" /> big trades</label>
      <label v-if="look.bubbles" class="flex items-center gap-1 text-dim" :title="`smallest trade shown in USD; 0 = this pair's big-trade size ($${short(data?.bigUsd ?? 0)}, the top 0.5% of its trades)`">min $
        <input v-model.number="look.bigMin" type="number" min="0" step="1000" :class="sel" class="w-24 text-xs" />
      </label>
      <span class="w-px h-4 bg-line" />
      <label class="flex items-center gap-1 text-dim" title="the bot's entries, adds and exits on this pair; the open trade's average entry, stop (when it fires before liquidation) and liquidation price"><input v-model="look.trades" type="checkbox" /> bot trades</label>
      <template v-if="data?.market === 'swap'">
        <label class="flex items-center gap-1 text-dim" title="open interest change per bar (bars) and open interest (grey line). Green: price up, OI up (longs opening). Red: price down, OI up (shorts opening). Faded green: price up, OI down (shorts closing). Faded red: price down, OI down (longs closing)"><input v-model="look.oi" type="checkbox" /> open interest</label>
        <label class="flex items-center gap-1 text-dim" :title="`cumulative delta of ${spotPair} (spot, same exchange) as an amber line next to the perp's, in coins; records the spot pair while on`"><input v-model="look.spotCvd" type="checkbox" /> spot CVD</label>
        <label class="flex items-center gap-1 text-dim" title="value of longs liquidated (red, down) and shorts liquidated (green, up) per bar, recorded live from when the pair is watched; amber line = the settled funding rate (%)"><input v-model="look.liq" type="checkbox" /> liquidations &amp; funding</label>
      </template>
    </div>

    <div class="text-xs text-faint px-1 -my-1" :class="!wide && !layers && 'truncate'" @click="layers = true">
      <template v-if="pairStatus">
        live: <span :class="pairStatus.live === 'on' ? 'text-up' : 'text-warn'">{{ pairStatus.live }}</span>
        <template v-if="pairStatus.book"> · book: <span :class="pairStatus.book === 'on' ? 'text-up' : 'text-warn'">{{ pairStatus.book }}</span> {{ pairStatus.book_levels }} levels</template>
        · {{ pairStatus.trades_s }} trades/s · history: {{ pairStatus.fill }}
        <template v-if="pairStatus.oi"> · OI: {{ pairStatus.oi }}</template>
        <template v-if="pairStatus.liq"> · liquidations: {{ pairStatus.liq }}<template v-if="pairStatus.liq_since"> since {{ fmtMs(pairStatus.liq_since) }}</template></template>
        <template v-if="pairStatus.funding"> · funding <span :class="pairStatus.funding.rate >= 0 ? 'text-up' : 'text-down'">{{ fmtPct(pairStatus.funding.rate) }}</span><template v-if="pairStatus.funding.next"> at {{ fmtMs(pairStatus.funding.next) }}</template></template>
        <template v-if="spotStatus"> · spot: <span :class="spotStatus.live === 'on' ? 'text-up' : 'text-warn'">{{ spotStatus.live }}</span></template>
        <span v-if="pairStatus.derivs_error" class="text-warn" :title="pairStatus.derivs_error"> · OI / funding error</span>
      </template>
      <template v-else-if="status && !status.running">worker not running</template>
      <template v-if="historyFrom"> · data from {{ fmtMs(historyFrom.start) }}</template>
    </div>

    <div class="panel flex-1 min-h-0 p-2">
      <FootprintChart v-if="bars.length" :bars="bars" :step="step" :cell-style="look.style" :rows="look.rows" :settings="settings"
        :show-poc="look.poc" :show-va="look.va" :zones="zoneList" :gaps="gaps" :session="look.session" :title="title"
        :tf-sec="tfSec" :heat="look.heat ? heat : null" :contrast="look.contrast" :heat-log="look.heatLog" :heat-max="look.heatMax" :events="look.walls ? heat?.events ?? [] : []" :wall-usd="heat?.wallUsd ?? 0"
        :imb="look.imb ? heat?.imb ?? [] : []" :band="look.band" :overlays="overlays" @pick="onPick"
        :oi="oiByBar" :derivs="derivs" :show-liq="look.liq" :trade="tradeOv" :trade-marks="tradeMarks" :spot-bars="spotBars"
        @hover="(bar, price) => (hover = { bar: bar, price: price })" @view="onView" />
      <div v-else class="h-full grid place-items-center text-dim text-sm text-center px-6">
        <template v-if="loading">loading…</template>
        <template v-else-if="error">{{ error }}</template>
        <template v-else-if="data?.pending">starting to record {{ pair }} on {{ data.exchange }}: the first bars show within a minute, history fills in behind them</template>
        <template v-else>no trades recorded for {{ pair }} yet</template>
      </div>
    </div>

    <div v-if="barStats && shown" class="panel p-3 text-xs shrink-0 max-h-28 overflow-auto lg:max-h-none">
      <div class="flex flex-wrap gap-x-5 gap-y-1 num">
        <span class="text-ink font-semibold">{{ fmtTime(shown.t) }}</span>
        <span class="text-dim">O <span class="text-ink">{{ fmtP(shown.o) }}</span> H <span class="text-ink">{{ fmtP(shown.h) }}</span> L <span class="text-ink">{{ fmtP(shown.l) }}</span> C <span class="text-ink">{{ fmtP(shown.c) }}</span></span>
        <span class="text-dim">volume <span class="text-ink">{{ short(barStats.volume) }}</span></span>
        <span class="text-dim">delta <span :class="barStats.delta >= 0 ? 'text-up' : 'text-down'">{{ barStats.delta >= 0 ? "+" : "" }}{{ short(barStats.delta) }} ({{ barStats.deltaPct.toFixed(1) }}%)</span></span>
        <span class="text-dim" title="lowest and highest running delta inside the bar">min / max delta <span class="text-ink">{{ short(barStats.dmin) }} / {{ short(barStats.dmax) }}</span></span>
        <span class="text-dim" title="running delta when the bar made its high / low">delta at high / low <span class="text-ink">{{ short(barStats.dh) }} / {{ short(barStats.dl) }}</span></span>
        <span class="text-dim">trades <span class="text-up">{{ barStats.buys }}</span> / <span class="text-down">{{ barStats.sells }}</span></span>
        <span class="text-dim">avg / max size <span class="text-ink">{{ short(barStats.avgSize) }} / {{ short(barStats.maxSize) }}</span></span>
        <span class="text-dim">POC <span class="text-warn">{{ fmtP(barStats.poc) }}</span></span>
        <span class="text-dim">VA <span class="text-ink">{{ fmtP(barStats.val) }} – {{ fmtP(barStats.vah) }}</span></span>
        <span class="text-dim">imbalances <span class="text-up">{{ barStats.buyImb }}</span> / <span class="text-down">{{ barStats.sellImb }}</span> · stacked {{ barStats.stacks }}</span>
        <span class="text-dim" :title="`trades of at least $${short(data?.bigUsd ?? 0)}`">big trades <span class="text-ink">{{ barStats.bigCount }} ({{ barStats.bigShare.toFixed(1) }}% of volume)</span></span>
        <template v-if="shownDerivs">
          <span v-if="shownDerivs.oi" class="text-dim">OI <span class="text-ink">{{ short(shownDerivs.oi.oi) }}</span>
            <template v-if="shownDerivs.oi.delta != null"> (<span :class="shownDerivs.oi.delta >= 0 ? 'text-up' : 'text-down'">{{ shownDerivs.oi.delta >= 0 ? "+" : "" }}{{ short(shownDerivs.oi.delta) }}</span>, {{ shownDerivs.oi.who }})</template></span>
          <span v-if="shownDerivs.liq" class="text-dim">liquidated longs <span class="text-down">${{ short(shownDerivs.liq.long) }}</span> / shorts <span class="text-up">${{ short(shownDerivs.liq.short) }}</span></span>
          <span v-if="shownDerivs.funding != null" class="text-dim">funding <span :class="shownDerivs.funding >= 0 ? 'text-up' : 'text-down'">{{ fmtPct(shownDerivs.funding) }}</span></span>
        </template>
        <span v-for="mark in shownMarks" :key="mark.kind" class="text-warn" :title="MARK_INFO[mark.kind]">{{ MARK_NAME[mark.kind] }}</span>
        <span v-if="atPrice" class="text-dim">at {{ fmtP(atPrice.price) }}: <span class="text-down">{{ short(atPrice.vs) }}</span> × <span class="text-up">{{ short(atPrice.vb) }}</span>
          (Δ {{ short(atPrice.vb - atPrice.vs) }}, {{ atPrice.ns }} × {{ atPrice.nb }} trades)</span>
      </div>
    </div>
  </div>
</template>
