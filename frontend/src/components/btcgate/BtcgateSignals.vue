<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import PanelCard from "@/components/layout/PanelCard.vue"
import { coinOf, sig } from "@/lib/btcgate"
import { pct, price } from "@/lib/format"

// every btcgate signal with how it turned out: alerts (worker's events.json, last 7 days) and the ledger's signals
type Move = { scored: number; right: number | null; avg: number | null; usual: number | null }
type Alert = { date: string; pair: string; layer: string; z: number | null; side: number; price: number | null; "1h"?: number | null; "4h"?: number | null; "24h"?: number | null }
type Ledger = { date: string; pair: string; tag: string; side: number; price: number; outcome: string | null; ret_pct: number | null; mfe_pct: number | null; mae_pct: number | null }
type Data = { alerts: { days?: number; events: Alert[]; summary: Record<string, { n: number } & Record<string, Move>> }; ledger: Ledger[]; bot_pairs: string[] }

const data = ref<Data | null>(null)
async function load() {
  const response = await fetch("/api/btcgate/signals").catch(() => null)
  if (response?.ok) data.value = await response.json()
}
let timer = 0
onMounted(() => { load(); timer = window.setInterval(load, 60_000) })
onBeforeUnmount(() => clearInterval(timer))

const HORIZONS = ["1h", "4h", "24h"] as const
const SAYS: Record<number, string> = { 1: "up", [-1]: "down", 0: "either way" }
const find = ref("")
const type = ref("")
const mine = ref(false)
const showRandom = ref(false)
const botCoins = computed(() => new Set((data.value?.bot_pairs ?? []).map(coinOf)))
const keep = (pair: string, kind: string) =>
  (!type.value || type.value === kind) && (!find.value.trim() || coinOf(pair).includes(find.value.trim().toUpperCase())) && (!mine.value || botCoins.value.has(coinOf(pair)))
const alerts = computed(() => (data.value?.alerts.events ?? []).filter((event) => keep(event.pair, event.layer)))
const ledger = computed(() => (data.value?.ledger ?? []).filter((entry) => (showRandom.value || entry.tag !== "random") && keep(entry.pair, entry.tag)))
const summary = computed(() => Object.entries(data.value?.alerts.summary ?? {}).filter(([layer]) => !type.value || type.value === layer))
const types = computed(() => {
  const layers = new Set((data.value?.alerts.events ?? []).map((event) => event.layer))
  const tags = new Set((data.value?.ledger ?? []).filter((entry) => entry.tag !== "random").map((entry) => entry.tag))
  return [...[...layers].map((value) => ({ v: value, label: sig(value).label })), ...[...tags].map((value) => ({ v: value, label: value }))]
})
// a move the way the alert said = green, the other way = red, no side = plain
const tone = (value: number | null | undefined, side: number) => (value == null || !side ? "text-dim" : value * side > 0 ? "text-up" : "text-down")
const share = (value: number | null) => (value == null ? "–" : `${Math.round(value * 100)}%`)
const RESULT: Record<string, string> = { tp: "target", sl: "stop", time: "24 h" }
</script>

<template>
  <div class="space-y-3">
    <div class="flex flex-wrap items-center gap-2 text-sm">
      <input v-model="find" class="rounded-md bg-raised border border-line px-2 py-1 text-ink w-32" placeholder="coin" />
      <select v-model="type" class="rounded-md bg-raised border border-line px-2 py-1 text-ink">
        <option value="">every type</option>
        <option v-for="type in types" :key="type.v" :value="type.v">{{ type.label }}</option>
      </select>
      <label class="flex items-center gap-1.5 text-dim"><input v-model="mine" type="checkbox" /> only my bots' coins</label>
    </div>

    <PanelCard :pad="false" :title="`Alerts · last ${data?.alerts.days ?? 7} days`">
      <p class="px-4 pb-2 text-xs text-dim">How often each alert went the way it said, against how often the same coins moved that way anyway over the same days ("usual"). An alert is only worth something above its usual. Small numbers: information, not a verdict.</p>
      <div class="overflow-x-auto">
        <table class="w-full text-sm num whitespace-nowrap">
          <thead class="text-xs text-dim text-left border-b border-line"><tr>
            <th class="px-3 py-2 font-normal">Alert</th><th class="px-3 py-2 font-normal">Says</th><th class="px-3 py-2 font-normal">Alerts</th>
            <th v-for="horizon in HORIZONS" :key="horizon" class="px-3 py-2 font-normal">{{ horizon }} later: right / usual</th></tr></thead>
          <tbody><tr v-for="[layer, stats] in summary" :key="layer" class="border-b border-line last:border-0">
            <td class="px-3 py-2 font-semibold" :class="sig(layer).tone">{{ sig(layer).label }}</td>
            <td class="px-3 py-2 text-dim">{{ SAYS[alerts.find((event) => event.layer === layer)?.side ?? 0] }}</td>
            <td class="px-3 py-2">{{ stats.n }}</td>
            <td v-for="horizon in HORIZONS" :key="horizon" class="px-3 py-2">
              <template v-if="stats[horizon]?.scored">
                <span :class="stats[horizon].right != null && stats[horizon].usual != null && stats[horizon].right > stats[horizon].usual ? 'text-up' : 'text-dim'">{{ share(stats[horizon].right) }}</span>
                <span class="text-faint"> / {{ share(stats[horizon].usual) }}</span>
                <span class="text-faint text-xs"> · {{ stats[horizon].scored }} scored · avg {{ pct((stats[horizon].avg ?? 0) * 100) }}</span>
              </template>
              <span v-else class="text-faint">waiting</span>
            </td></tr>
            <tr v-if="!summary.length"><td colspan="6" class="px-3 py-3 text-dim">no alerts with a price yet</td></tr></tbody>
        </table>
      </div>
      <div class="overflow-x-auto border-t border-line max-h-[32rem]">
        <table class="w-full text-sm num whitespace-nowrap">
          <thead class="text-xs text-dim text-left border-b border-line sticky top-0 bg-panel"><tr>
            <th class="px-3 py-2 font-normal">Time (UTC)</th><th class="px-3 py-2 font-normal">Coin</th><th class="px-3 py-2 font-normal">Alert</th>
            <th class="px-3 py-2 font-normal">Says</th><th class="px-3 py-2 font-normal">Price</th>
            <th v-for="horizon in HORIZONS" :key="horizon" class="px-3 py-2 font-normal">{{ horizon }} later</th></tr></thead>
          <tbody><tr v-for="event in alerts" :key="`${event.date}${event.pair}${event.layer}`" class="border-b border-line last:border-0">
            <td class="px-3 py-2 text-dim">{{ event.date.slice(5, 16) }}</td>
            <td class="px-3 py-2 font-semibold">{{ coinOf(event.pair) }}<span v-if="botCoins.has(coinOf(event.pair))" class="ml-1 text-[10px] text-brand-b" title="one of your bots trades or watches it">bot</span></td>
            <td class="px-3 py-2" :class="sig(event.layer).tone">{{ sig(event.layer).label }}</td>
            <td class="px-3 py-2 text-dim">{{ SAYS[event.side] }}</td>
            <td class="px-3 py-2">{{ event.price == null ? "no candles" : price(event.price) }}</td>
            <td v-for="horizon in HORIZONS" :key="horizon" class="px-3 py-2" :class="tone(event[horizon], event.side)">{{ event.price == null ? "" : event[horizon] == null ? "waiting" : pct(event[horizon]! * 100) }}</td></tr>
            <tr v-if="!alerts.length"><td colspan="8" class="px-3 py-3 text-dim">no alerts</td></tr></tbody>
        </table>
      </div>
    </PanelCard>

    <PanelCard :pad="false" title="Ledger signals · last 30 days">
      <template #actions><label class="ml-auto flex items-center gap-1.5 text-xs text-dim"><input v-model="showRandom" type="checkbox" /> show the random control</label></template>
      <p class="px-4 pb-2 text-xs text-dim">Each one scored as a 24 h trade with a target and a stop at 2x the coin's 1h ATR. Best / worst = how far it went for and against before closing. The Ledger tab compares them with random.</p>
      <div class="overflow-x-auto max-h-[32rem]">
        <table class="w-full text-sm num whitespace-nowrap">
          <thead class="text-xs text-dim text-left border-b border-line sticky top-0 bg-panel"><tr>
            <th class="px-3 py-2 font-normal">Time (UTC)</th><th class="px-3 py-2 font-normal">Coin</th><th class="px-3 py-2 font-normal">Tag</th>
            <th class="px-3 py-2 font-normal">Side</th><th class="px-3 py-2 font-normal">Price</th><th class="px-3 py-2 font-normal">Result</th>
            <th class="px-3 py-2 font-normal">Best / worst</th></tr></thead>
          <tbody><tr v-for="entry in ledger" :key="`${entry.date}${entry.pair}${entry.tag}`" class="border-b border-line last:border-0">
            <td class="px-3 py-2 text-dim">{{ entry.date.slice(5, 16) }}</td>
            <td class="px-3 py-2 font-semibold">{{ coinOf(entry.pair) }}<span v-if="botCoins.has(coinOf(entry.pair))" class="ml-1 text-[10px] text-brand-b">bot</span></td>
            <td class="px-3 py-2" :class="entry.tag === 'random' && 'text-faint'">{{ entry.tag }}</td>
            <td class="px-3 py-2" :class="entry.side === 1 ? 'text-up' : 'text-down'">{{ entry.side === 1 ? "long" : "short" }}</td>
            <td class="px-3 py-2">{{ price(entry.price) }}</td>
            <td class="px-3 py-2" :class="entry.ret_pct == null ? 'text-dim' : entry.ret_pct > 0 ? 'text-up' : 'text-down'">{{ entry.outcome ? `${pct(entry.ret_pct)} (${RESULT[entry.outcome] ?? entry.outcome})` : "waiting" }}</td>
            <td class="px-3 py-2 text-dim">{{ entry.outcome ? `${pct(entry.mfe_pct)} / ${pct(entry.mae_pct)}` : "" }}</td></tr>
            <tr v-if="!ledger.length"><td colspan="7" class="px-3 py-3 text-dim">no signals</td></tr></tbody>
        </table>
      </div>
    </PanelCard>
  </div>
</template>
