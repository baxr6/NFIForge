<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import CandleChart, { type Candle, type Line, type Mark } from "@/components/charts/CandleChart.vue"
import Drawer from "@/components/trades/Drawer.vue"
import EntryForm from "@/components/trades/EntryForm.vue"
import { css } from "@/components/charts/chartTheme"
import { useHistory } from "@/lib/history"
import { useTradeAccess } from "@/lib/tradeActions"
import { overlay, pairMarks, type Trade } from "@/lib/trades"
import { storeToRefs } from "pinia"
import { useLive } from "@/stores/live"

// one pair's candles: the bot's own timeframe with any of its indicator columns, or bigger timeframes from the
// exchange; every trade on the pair marked, the open one with avg entry, liquidation and profit zone
const live = useLive()
const route = useRoute()
const router = useRouter()
const { all: history } = useHistory()

// ===========================================================================
// BOT / PAIR / TIMEFRAME
// ===========================================================================
const botNames = computed(() => Object.keys(live.bots))
const { picked: botName } = storeToRefs(live)
if (route.query.bot) botName.value = String(route.query.bot)  // a link to a chart picks its bot
const bot = computed(() => live.bots[botName.value ?? ""] ?? live.bots[botNames.value[0]])
const botTf = computed(() => bot.value?.config?.timeframe ?? "5m")
const openTrades = computed(() => (bot.value?.status ?? []) as Trade[])
// entry on the shown pair: an add when the bot already holds it
const { canTrade } = useTradeAccess(computed(() => bot.value?.name))
const entering = ref(false)
const entrySent = ref("")
const pairTrade = computed(() => openTrades.value.find((trade) => trade.pair === pair.value) ?? null)
const pairs = computed(() => {
  const open = openTrades.value.map((trade) => trade.pair)
  const wl = ((bot.value?.whitelist?.whitelist ?? []) as string[]).filter((name) => !open.includes(name))
  return { open: [...new Set(open)], wl }
})
const pair = ref(String(route.query.pair ?? ""))
watch(pairs, (lists) => { if (!pair.value) pair.value = lists.open[0] ?? lists.wl[0] ?? "" }, { immediate: true })
const EX_TFS = ["15m", "1h", "4h", "1d"]
const timeframe = ref(String(route.query.tf ?? "bot"))
const tfLabel = computed(() => (timeframe.value === "bot" ? botTf.value : timeframe.value))
// the address keeps bot, pair and timeframe on the Chart page itself (not when this panel sits on another page)
watch([botName, pair, timeframe], () => { if (route.path === "/chart") router.replace({ query: { ...route.query, bot: bot.value?.name, pair: pair.value, tf: timeframe.value } }) })
const tfSec = (label: string) => Number.parseInt(label) * ({ m: 60, h: 3600, d: 86400, w: 604800 } as Record<string, number>)[label.slice(-1)]

// ===========================================================================
// INDICATORS (bot timeframe only), saved per bot in this browser
// ===========================================================================
type Ind = { name: string; color: string; place: "auto" | "price" | "pane"; group?: string }
const PALETTE = ["#3ea1ff", "#f0a83c", "#8b5cf6", "#3ddc84", "#f0566a", "#22d3ee", "#e879f9", "#a3e635"]
const inds = ref<Ind[]>([])
const columns = ref<string[]>([])
const signals = ref(false)
// strategies name colours ("LightGreen"); the colour picker needs hex
function hex(color: string | undefined, index: number): string {
  const ctx = document.createElement("canvas").getContext("2d")
  if (!color || !ctx) return PALETTE[index % PALETTE.length]
  ctx.fillStyle = PALETTE[index % PALETTE.length]
  ctx.fillStyle = color
  return ctx.fillStyle.startsWith("#") ? ctx.fillStyle : PALETTE[index % PALETTE.length]
}
const storeKey = computed(() => `nfiforge.chart.${bot.value?.name}`)

async function loadIndicators() {
  if (!bot.value) return
  const encodedName = encodeURIComponent(bot.value.name)
  try {
    const saved = localStorage.getItem(storeKey.value)
    if (saved) { const stored = JSON.parse(saved); inds.value = stored.inds ?? []; signals.value = !!stored.signals; return }
  } catch { /* storage blocked: fall back to the strategy's plot_config */ }
  const plotConfig: Record<string, any> = await fetch(`/api/bots/${encodedName}/plot_config`).then((response) => (response.ok ? response.json() : {})).catch(() => ({}))
  const out: Ind[] = []
  for (const [name, spec] of Object.entries<any>(plotConfig.main_plot ?? {})) out.push({ name, color: hex(spec?.color, out.length), place: "price" })
  for (const [group, cols] of Object.entries<any>(plotConfig.subplots ?? {}))
    for (const [name, spec] of Object.entries<any>(cols ?? {})) out.push({ name, color: hex(spec?.color, out.length), place: "pane", group })
  inds.value = out
}
watch(() => bot.value?.name, loadIndicators, { immediate: true })
watch([inds, signals], () => { try { localStorage.setItem(storeKey.value, JSON.stringify({ inds: inds.value, signals: signals.value })) } catch { /* not saved */ } }, { deep: true })

async function loadColumns() {
  if (!bot.value || !pair.value) return
  const response = await fetch(`/api/bots/${encodeURIComponent(bot.value.name)}/frame/columns?pair=${encodeURIComponent(pair.value)}`).catch(() => null)
  columns.value = response?.ok ? await response.json() : []
}
watch([() => bot.value?.name, pair], loadColumns, { immediate: true })

const adding = ref("")
function add() {
  const name = adding.value.trim()
  if (name && columns.value.includes(name) && !inds.value.some((indicator) => indicator.name === name))
    inds.value.push({ name, color: PALETTE[inds.value.length % PALETTE.length], place: "auto" })
  adding.value = ""
}
const remove = (name: string) => (inds.value = inds.value.filter((indicator) => indicator.name !== name))
function cyclePlace(indicator: Ind) { indicator.place = indicator.place === "price" ? "pane" : "price" }
function reset() { try { localStorage.removeItem(storeKey.value) } catch { /* ignore */ } loadIndicators() }

// ===========================================================================
// DATA
// ===========================================================================
const candles = ref<Candle[]>([])
const raw = ref<{ columns: string[]; data: any[][] } | null>(null)
const error = ref("")
const loading = ref(false)
// which bot / pair / timeframe the candles shown are for: the chart redraws when new candles arrive, not when the
// picker changes (else the old pair's prices draw the new pair's trade); a slower older load never lands last
const loadedFor = ref("")
let seq = 0

async function load() {
  if (!bot.value || !pair.value) return
  const ticket = ++seq, want = `${bot.value.name}-${pair.value}-${timeframe.value}`
  loading.value = true
  const encodedName = encodeURIComponent(bot.value.name), encodedPair = encodeURIComponent(pair.value)
  try {
    if (timeframe.value === "bot") {
      const cols = [...inds.value.map((indicator) => indicator.name), ...(signals.value ? ["enter_long", "enter_short"] : [])].join(",")
      const response = await fetch(`/api/bots/${encodedName}/frame?pair=${encodedPair}&limit=1500&columns=${encodeURIComponent(cols)}`)
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail ?? response.statusText)
      const frame = await response.json()
      if (ticket !== seq) return
      const columnIndex = (name: string) => frame.columns.indexOf(name)
      const [timeCol, openCol, highCol, lowCol, closeCol, volumeCol] = ["__date_ts", "open", "high", "low", "close", "volume"].map(columnIndex)
      raw.value = frame
      candles.value = frame.data.map((row: any[]) => ({ time: row[timeCol] / 1000, open: row[openCol], high: row[highCol], low: row[lowCol], close: row[closeCol], volume: row[volumeCol] }))
    } else {
      const response = await fetch(`/api/bots/${encodedName}/candles?pair=${encodedPair}&timeframe=${timeframe.value}&limit=1000`)
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail ?? response.statusText)
      const rows = (await response.json()).candles
      if (ticket !== seq) return
      raw.value = null
      candles.value = rows.map((candle: number[]) => ({ time: candle[0] / 1000, open: candle[1], high: candle[2], low: candle[3], close: candle[4], volume: candle[5] }))
    }
    loadedFor.value = want
    error.value = ""
  } catch (e) {
    if (ticket === seq) error.value = String((e as Error).message ?? e)
  } finally {
    if (ticket === seq) loading.value = false
  }
}
watch([() => bot.value?.name, pair, timeframe, () => inds.value.map((indicator) => indicator.name).join(), signals], load, { immediate: true })
let timer = 0
onMounted(() => (timer = window.setInterval(load, 60000)))
onBeforeUnmount(() => clearInterval(timer))

// indicator columns -> lines; "auto" goes on the price when its values sit near the price, else its own pane
const lines = computed<Line[]>(() => {
  const frame = raw.value
  if (!frame || timeframe.value !== "bot") return []
  const timeCol = frame.columns.indexOf("__date_ts"), closeCol = frame.columns.indexOf("close")
  const panes = new Map<string, number>()
  const out: Line[] = []
  for (const indicator of inds.value) {
    const valueCol = frame.columns.indexOf(indicator.name)
    if (valueCol < 0) continue
    const num = (value: any) => (typeof value === "boolean" ? Number(value) : value == null ? null : Number(value))
    const data = frame.data.map((row) => ({ time: row[timeCol] / 1000, value: num(row[valueCol]) }))
    let place = indicator.place
    if (place === "auto") {
      const ratios = frame.data.map((row) => (num(row[valueCol]) ?? NaN) / row[closeCol]).filter((ratio) => Number.isFinite(ratio)).sort((a, b) => a - b)
      const mid = ratios[Math.floor(ratios.length / 2)]
      place = mid > 0.5 && mid < 2 ? "price" : "pane"
    }
    const key = indicator.group ?? indicator.name
    if (place === "pane" && !panes.has(key)) panes.set(key, 2 + panes.size)
    out.push({ name: indicator.name, color: indicator.color, pane: place === "price" ? 0 : panes.get(key)!, data })
  }
  return out
})
const paneKey = computed(() => lines.value.map((line) => `${line.name}:${line.pane}:${line.color}`).join("|"))

// ===========================================================================
// TRADES ON THIS PAIR
// ===========================================================================
const sec = computed(() => tfSec(tfLabel.value))
const openTrade = computed(() => openTrades.value.find((trade) => trade.pair === pair.value))
const tradeOv = computed(() => (openTrade.value ? overlay(openTrade.value, sec.value) : undefined))
const marks = computed<Mark[]>(() => {
  // closed trades, and open ones beyond the first (rare: several bots/pairs), as marks
  const out = pairMarks(
    history.value.filter((trade) => trade._bot === bot.value?.name && trade.pair === pair.value),
    openTrades.value.filter((other) => other.pair === pair.value && other !== openTrade.value), sec.value)
  const frame = raw.value
  if (signals.value && frame) {
    const timeCol = frame.columns.indexOf("__date_ts"), longCol = frame.columns.indexOf("enter_long"), shortCol = frame.columns.indexOf("enter_short")
    for (const row of frame.data) {
      if (longCol >= 0 && row[longCol] === 1) out.push({ time: row[timeCol] / 1000, kind: "signal", side: "long" })
      if (shortCol >= 0 && row[shortCol] === 1) out.push({ time: row[timeCol] / 1000, kind: "signal", side: "short" })
    }
  }
  return out
})
const title = computed(() => {
  const trade = openTrade.value
  return `${pair.value} · ${tfLabel.value}${trade ? ` · ${trade.is_short ? "short" : "long"} ${trade.leverage}x · tag ${trade.enter_tag}` : ""}`
})
const sel = "rounded-md bg-raised border border-line px-2 py-1 text-ink text-sm"
const dim = css("--text-dim")
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
        <button class="px-3 py-1" :class="timeframe === 'bot' ? 'bg-raised text-ink' : 'text-dim hover:text-ink'" :title="'the bot\'s own candles, with its indicators'" @click="timeframe = 'bot'">{{ botTf }} · bot</button>
        <button v-for="option in EX_TFS" :key="option" class="px-3 py-1" :class="timeframe === option ? 'bg-raised text-ink' : 'text-dim hover:text-ink'" title="from the exchange, no indicators" @click="timeframe = option">{{ option }}</button>
      </div>
      <span v-if="loading" class="text-xs text-faint">loading…</span>
      <span v-if="error" class="text-xs text-down">{{ error }}</span>
      <span v-if="entrySent" class="text-xs text-up">✓ {{ entrySent }}</span>
      <button v-if="canTrade && pair" class="ml-auto text-xs px-3 py-1 rounded-md border border-line text-dim hover:text-ink" @click="entering = true; entrySent = ''">{{ pairTrade ? "+ add" : "+ entry" }}</button>
      <button class="text-xs px-3 py-1 rounded-md border border-line text-dim hover:text-ink" :class="canTrade && pair ? '' : 'ml-auto'" @click="load">↻</button>
    </div>
    <Drawer v-if="entering" @close="entering = false">
      <div v-if="pairTrade" class="text-lg font-semibold mb-3">Add to {{ pair }} #{{ pairTrade.trade_id }}</div>
      <EntryForm :bot="bot?.name" :pair="pair" :trade="pairTrade" @done="(message) => { entering = false; entrySent = message }" @cancel="entering = false" />
    </Drawer>

    <div v-if="timeframe === 'bot'" class="panel p-3 flex flex-wrap gap-2 items-center text-xs">
      <span class="text-dim">indicators</span>
      <span v-for="indicator in inds" :key="indicator.name" class="flex items-center gap-1.5 rounded-full border border-line pl-2 pr-1 py-0.5">
        <input v-model="indicator.color" type="color" class="w-3.5 h-3.5 rounded-full border-0 bg-transparent p-0 cursor-pointer" :title="'colour'" />
        <span class="num text-ink">{{ indicator.name }}</span>
        <button class="text-faint hover:text-ink px-1" :title="'on the price or in its own pane'" @click="cyclePlace(indicator)">{{ indicator.place === "pane" ? "pane" : indicator.place === "price" ? "price" : "auto" }}</button>
        <button class="text-faint hover:text-down px-1" :title="'remove'" @click="remove(indicator.name)">✕</button>
      </span>
      <input v-model="adding" list="ind-cols" placeholder="+ add column" :class="sel" class="w-44 text-xs" @change="add" @keydown.enter="add" />
      <datalist id="ind-cols"><option v-for="column in columns.filter((column) => !inds.some((indicator) => indicator.name === column))" :key="column" :value="column" /></datalist>
      <label class="flex items-center gap-1 text-dim ml-2"><input v-model="signals" type="checkbox" /> entry signals</label>
      <button class="ml-auto text-faint hover:text-ink" :style="{ color: dim }" @click="reset">reset to strategy's</button>
    </div>

    <div class="panel flex-1 min-h-0 p-2">
      <CandleChart v-if="candles.length" :key="`${loadedFor}-${paneKey}-${!!tradeOv}`" :candles="candles" :trade="tradeOv" :marks="marks" :lines="lines" height="fill" :title="title" />
      <div v-else class="h-full grid place-items-center text-dim text-sm">{{ loading ? "loading…" : error || "no candles" }}</div>
    </div>
  </div>
</template>
