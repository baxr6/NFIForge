<script setup lang="ts">
import { computed, ref, toRef, watch } from "vue"
import CandleChart from "@/components/charts/CandleChart.vue"
import DownloadButton from "@/components/DownloadButton.vue"
import ProfitBoxes from "@/components/trades/ProfitBoxes.vue"
import TradeActions from "@/components/trades/TradeActions.vue"
import { money, pct, signed, tone } from "@/lib/format"
import { nfiMode } from "@/lib/nfi"
import { ordersSheet } from "@/lib/tradeSheets"
import { ladder } from "@/lib/risk"
import { useTradeAccess } from "@/lib/tradeActions"
import { closeTs, duration, excursion, exitGroup, filledOrders, isEntry, openTs, overlay, type Trade } from "@/lib/trades"
import { useSettings } from "@/stores/settings"

// one trade in full: summary, chart with every order, best/worst move while open, order ladder, nfi data, similar trades
const props = defineProps<{ trade: Trade; bot: string; isNfi?: boolean; customData?: Record<string, any>[]; history?: Trade[]; wallet?: number | null }>()
const settings = useSettings()
const utc = computed(() => settings.s?.timezone !== "local")
const inspected = computed(() => props.trade)
const { canTrade } = useTradeAccess(toRef(props, "bot"))

const SEC: Record<string, number> = { "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400 }
const candles = ref<{ time: number; open: number; high: number; low: number; close: number; volume: number }[]>([])
const timeframe = ref("5m")
// chart timeframe: auto picks from the trade length; a picked one is kept for the next trade (browser only)
const TFS = ["auto", "5m", "15m", "1h", "4h", "1d"]
const TF_KEY = "nfiforge.tradeChartTf"
const pick = ref((() => { try { return localStorage.getItem(TF_KEY) ?? "auto" } catch { return "auto" } })())
watch(pick, (value) => { try { localStorage.setItem(TF_KEY, value) } catch { /* not saved */ } })
const clipped = ref(false)
const loading = ref(false)
const error = ref("")

async function load() {
  loading.value = true
  error.value = ""
  const query = new URLSearchParams({ pair: inspected.value.pair, start: String(openTs(inspected.value)), end: String(closeTs(inspected.value)) })
  if (pick.value !== "auto") query.set("timeframe", pick.value)
  try {
    const response = await fetch(`/api/bots/${encodeURIComponent(props.bot)}/candles?${query}`)
    if (!response.ok) { error.value = (await response.json().catch(() => ({}))).detail ?? `candles failed (${response.status})`; return }
    const body = await response.json()
    timeframe.value = body.timeframe
    clipped.value = !!body.clipped
    candles.value = body.candles.map((candle: number[]) => ({ time: Math.floor(candle[0] / 1000), open: candle[1], high: candle[2], low: candle[3], close: candle[4], volume: candle[5] ?? 0 }))
  } catch {
    error.value = "backend not reachable"
  } finally {
    loading.value = false
  }
}
watch(() => `${props.bot}|${inspected.value.trade_id}|${pick.value}`, load, { immediate: true })

const chartOverlay = computed(() => overlay(inspected.value, SEC[timeframe.value] ?? 300))
const excursionStats = computed(() => excursion(inspected.value, candles.value))
const pnl = computed(() => (inspected.value.is_open ? inspected.value.profit_abs : inspected.value.close_profit_abs) ?? inspected.value.profit_abs)
const pnlPct = computed(() => ((inspected.value.is_open ? inspected.value.profit_ratio : inspected.value.close_profit) ?? inspected.value.profit_ratio ?? 0) * 100)
const orders = computed(() => filledOrders(inspected.value))
// margin in and out per level (first entry, grind n, buyback, manual add ...)
const levels = computed(() => ladder(inspected.value))
const firstIn = computed(() => levels.value.find((level) => level.level === "first entry")?.marginIn ?? 0)
const margin = computed(() => (inspected.value.is_open ? inspected.value.stake_amount : inspected.value.max_stake_amount) ?? 0)
const mode = computed(() => (props.isNfi ? nfiMode(inspected.value.enter_tag) : null))
const nfiData = computed(() => (props.customData ?? []).find((entry) => entry.trade_id === inspected.value.trade_id)?.custom_data ?? [])
const when = (ms?: number) => (ms ? new Date(ms).toLocaleString("en-GB", { timeZone: utc.value ? "UTC" : undefined, hour12: false }) : "–")

// other closed trades with the same entry tag: how that setup usually ends
const similar = computed(() => {
  const tag = (inspected.value.enter_tag ?? "").trim()
  const sameTag = (props.history ?? []).filter((other) => other.trade_id !== inspected.value.trade_id && (other.enter_tag ?? "").trim() === tag)
  if (!sameTag.length) return null
  const wins = sameTag.filter((other) => (other.close_profit_abs ?? 0) > 0).length
  const total = sameTag.reduce((sum, other) => sum + (other.close_profit_abs ?? 0), 0)
  const samePair = sameTag.filter((other) => other.pair === inspected.value.pair).length
  return { n: sameTag.length, win: (wins / sameTag.length) * 100, total, avg: total / sameTag.length, samePair }
})
</script>

<template>
  <div class="space-y-3">
    <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <span class="text-lg font-semibold">{{ inspected.pair }}</span>
      <span class="text-xs px-1.5 rounded" :class="inspected.is_short ? 'text-down bg-[var(--red-dim)]' : 'text-up bg-[var(--green-dim)]'">{{ inspected.is_short ? "▼ short" : "▲ long" }} {{ inspected.leverage }}x</span>
      <span class="text-xs text-dim">#{{ inspected.trade_id }} · {{ mode ? `${mode} · ` : "" }}tag {{ inspected.enter_tag }}</span>
      <span v-if="!inspected.is_open" class="ml-auto num text-xl font-semibold" :class="tone(pnl)">{{ signed(pnl) }} <span class="text-sm">{{ pct(pnlPct) }}</span></span>
    </div>
    <ProfitBoxes v-if="inspected.is_open" :trade="inspected" />
    <TradeActions v-if="inspected.is_open && canTrade" :trade="inspected" :bot="bot" />

    <div class="grid gap-2 grid-cols-2 sm:grid-cols-4 text-xs">
      <div class="rounded-md bg-raised p-2"><div class="text-faint">opened</div><div class="num">{{ when(inspected.open_timestamp) }}</div></div>
      <div class="rounded-md bg-raised p-2"><div class="text-faint">{{ inspected.is_open ? "open for" : "closed" }}</div><div class="num">{{ inspected.is_open ? duration(inspected) : `${when(inspected.close_timestamp)} · ${duration(inspected)}` }}</div></div>
      <div class="rounded-md bg-raised p-2"><div class="text-faint">avg entry → {{ inspected.is_open ? "now" : "exit" }}</div><div class="num">{{ money(inspected.open_rate, 5) }} → {{ money(inspected.is_open ? inspected.current_rate : inspected.close_rate, 5) }}</div></div>
      <div class="rounded-md bg-raised p-2"><div class="text-faint">stake · max stake</div><div class="num">{{ money(inspected.stake_amount) }} · {{ money(inspected.max_stake_amount) }}</div></div>
      <div class="rounded-md bg-raised p-2"><div class="text-faint">exit reason</div><div class="num truncate" :title="inspected.exit_reason">{{ inspected.is_open ? "open" : exitGroup(inspected.exit_reason) }}</div></div>
      <div class="rounded-md bg-raised p-2"><div class="text-faint">best move (MFE)</div><div class="num text-up">{{ excursionStats ? `${pct(excursionStats.mfe)} · ${pct(excursionStats.mfeLev, 1)} lev` : "–" }}</div></div>
      <div class="rounded-md bg-raised p-2"><div class="text-faint">worst move (MAE)</div><div class="num text-down">{{ excursionStats ? `${pct(excursionStats.mae)} · ${pct(excursionStats.maeLev, 1)} lev` : "–" }}</div></div>
      <div class="rounded-md bg-raised p-2"><div class="text-faint">funding · fees</div><div class="num">{{ signed(inspected.funding_fees ?? 0) }} · {{ money((inspected.fee_open_cost ?? 0) + (inspected.fee_close_cost ?? 0)) }}</div></div>
    </div>

    <div class="panel p-2">
      <div class="flex flex-wrap items-center gap-2 mb-2 text-xs">
        <div class="flex rounded-md border border-line overflow-hidden">
          <button v-for="option in TFS" :key="option" class="px-2.5 py-1" :class="pick === option ? 'bg-raised text-ink' : 'text-dim hover:text-ink'" @click="pick = option">{{ option }}</button>
        </div>
        <span v-if="clipped && !loading" class="text-faint">{{ timeframe }}: newest {{ Math.round((candles.length * (SEC[timeframe] ?? 300)) / 86400) }} days shown</span>
      </div>
      <div v-if="loading" class="h-[380px] grid place-items-center text-xs text-faint">loading {{ inspected.pair }} candles from the exchange…</div>
      <div v-else-if="error" class="h-[380px] grid place-items-center text-xs text-down px-4 text-center">{{ error }}</div>
      <CandleChart v-else-if="candles.length" :key="`${inspected.trade_id}-${timeframe}`" :candles="candles" :trade="chartOverlay" :height="380" :title="`${inspected.pair} · ${timeframe}`" />
    </div>

    <div v-if="levels.length > 1" class="panel p-3 overflow-auto">
      <div class="flex flex-wrap items-baseline gap-x-3 mb-2">
        <span class="panel-title">Ladder</span>
        <span class="text-xs text-dim num">{{ inspected.is_open ? "margin now" : "most margin" }} {{ money(margin) }}<template v-if="firstIn"> · {{ (margin / firstIn).toFixed(1) }}x the first entry</template><template v-if="wallet && inspected.is_open"> · {{ ((margin / wallet) * 100).toFixed(1) }}% of the account</template></span>
      </div>
      <table class="w-full text-xs num">
        <thead class="text-faint text-left"><tr><th class="font-normal pb-1">level</th><th class="font-normal text-right">buys</th><th class="font-normal text-right">margin in</th><th class="font-normal text-right">sells</th><th class="font-normal text-right">margin out</th></tr></thead>
        <tbody>
          <tr v-for="level in levels" :key="level.level" class="border-t border-line">
            <td class="py-1">{{ level.level }}</td>
            <td class="text-right">{{ level.buys || "" }}</td>
            <td class="text-right">{{ level.buys ? money(level.marginIn) : "" }}</td>
            <td class="text-right">{{ level.sells || "" }}</td>
            <td class="text-right">{{ level.sells ? money(level.marginOut) : "" }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="grid gap-3 lg:grid-cols-2">
      <div class="panel p-3 overflow-auto">
        <div class="flex items-baseline mb-2"><span class="panel-title">Orders ({{ orders.length }})</span>
          <DownloadButton class="ml-auto" :name="`orders-${inspected.pair.split('/')[0]}-${inspected.trade_id}`" :sheets="() => [ordersSheet([{ ...inspected, _bot: bot }])]" :disabled="!orders.length" /></div>
        <table class="w-full text-xs num whitespace-nowrap [&_td]:pr-3 [&_th]:pr-3">
          <thead class="text-faint text-left"><tr><th class="font-normal pb-1">time</th><th class="font-normal">side</th><th class="font-normal">tag</th><th class="font-normal text-right">price</th><th class="font-normal text-right">cost</th></tr></thead>
          <tbody>
            <tr v-for="order in orders" :key="order.order_id" class="border-t border-line">
              <td class="py-1 pr-2 whitespace-nowrap">{{ when(order.order_filled_timestamp) }}</td>
              <td :class="isEntry(inspected, order) ? 'text-brand-b' : 'text-warn'">{{ isEntry(inspected, order) ? "entry" : "exit" }}</td>
              <td class="text-dim">{{ order.ft_order_tag || "–" }}</td>
              <td class="text-right">{{ money(order.safe_price, 5) }}</td>
              <td class="text-right">{{ money(order.cost) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="space-y-3">
        <div v-if="similar" class="panel p-3 text-xs">
          <div class="panel-title mb-2">Same tag ({{ inspected.enter_tag }}) in history</div>
          <div class="grid grid-cols-2 gap-2 num">
            <div><span class="text-faint">trades</span> {{ similar.n }} <span class="text-faint">({{ similar.samePair }} on {{ inspected.pair.split("/")[0] }})</span></div>
            <div><span class="text-faint">won</span> {{ similar.win.toFixed(0) }}%</div>
            <div><span class="text-faint">total</span> <span :class="tone(similar.total)">{{ signed(similar.total) }}</span></div>
            <div><span class="text-faint">avg</span> <span :class="tone(similar.avg)">{{ signed(similar.avg) }}</span></div>
          </div>
        </div>
        <div v-if="nfiData.length" class="panel p-3 text-xs">
          <div class="panel-title mb-2">NFI trade data</div>
          <div class="flex flex-wrap gap-1.5">
            <span v-for="entry in nfiData" :key="entry.key" class="px-2 py-0.5 rounded bg-raised num">{{ entry.key.replace(/_/g, " ") }} <span class="text-ink">{{ typeof entry.value === "number" ? +entry.value.toFixed(4) : entry.value }}</span></span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
