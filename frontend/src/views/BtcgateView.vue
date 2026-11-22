<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import BtcgateSettings from "@/components/btcgate/BtcgateSettings.vue"
import BtcgateSignals from "@/components/btcgate/BtcgateSignals.vue"
import BtcgateBook from "@/components/btcgate/BtcgateBook.vue"
import BtcgateScanner from "@/components/btcgate/BtcgateScanner.vue"
import PanelCard from "@/components/layout/PanelCard.vue"
import { DIRECTION, LOCK, TREND, TURB, coinOf, label, scanText, sig } from "@/lib/btcgate"
import { age, pct, price } from "@/lib/format"

// btcgate worker's market labels per coin and its signal ledger, read-only (docs/BTCGATE.md)
type Coin = Record<string, number | string | null> & { date: string; close: number }
type Row = Coin & { pair: string; coin: string }
type Tag = { tag: string; side: number; signals: number; scored: number; avg_pct: number | null; target_pct: number | null; stop_pct: number | null; time_pct: number | null; days: number; first: string }
type Event = { date: string; pair: string; layer: string; z: number | null }

const tab = ref<"market" | "coins" | "signals" | "scanner" | "ledger" | "book" | "settings">("market")
const status = ref<any>(null)
const off = ref(false)
const snap = ref<{ time?: number; candle?: string; coins: Record<string, Coin> }>({ coins: {} })
const ledger = ref<{ tags: Tag[] }>({ tags: [] })
const events = ref<Event[]>([])
const scanned = ref<Record<string, string[]>>({})  // coin -> scanner labels now

async function get(path: string) {
  const response = await fetch(`/api/btcgate/${path}`).catch(() => null)
  if (response?.status === 404) off.value = true
  return response?.ok ? response.json() : null
}
async function load() {
  if (["settings", "signals", "scanner", "book"].includes(tab.value)) { const fresh = await get("status"); if (fresh) status.value = fresh; return }  // own loads
  const [freshStatus, freshSnap, freshLedger, freshEvents, freshScan] = await Promise.all([get("status"), get("snapshot"), tab.value === "ledger" ? get("ledger") : null, tab.value === "ledger" ? null : get("events"),
    tab.value === "coins" ? get("scanner") : null])
  if (freshScan) scanned.value = Object.fromEntries((freshScan.scan.rows as { pair: string; labels: string[] }[]).map((row) => [coinOf(row.pair), row.labels]))
  if (freshStatus) status.value = freshStatus
  if (freshSnap) snap.value = freshSnap
  if (freshLedger) ledger.value = freshLedger
  if (freshEvents) events.value = freshEvents
}
let timer = 0
onMounted(() => { load(); timer = window.setInterval(load, 30_000) })
onBeforeUnmount(() => clearInterval(timer))
function pick(name: typeof tab.value) { tab.value = name; load() }

const worker = computed(() => status.value?.worker)
const now = ref(Date.now() / 1000)
window.setInterval(() => (now.value = Date.now() / 1000), 10_000)
const health = computed(() => {
  const current = status.value
  if (!current) return { text: "loading…", tone: "text-dim" }
  if (!current.installed) return { text: "the btcgate package isn't installed", tone: "text-down" }
  if (!current.running) return { text: `worker stopped${current.last_exit ? ` (${current.last_exit})` : ""}, restarting`, tone: "text-down" }
  const state = worker.value
  if (!state || state.phase !== "running") return { text: state?.phase ?? "starting", tone: "text-warn" }
  const late = state.updated && now.value - state.updated > 120
  return { text: late ? `no update for ${age(state.updated, now.value)}` : "running", tone: late ? "text-warn" : "text-up" }
})

const coins = computed(() => Object.entries(snap.value.coins).map(([pair, row]) => ({ ...row, pair, coin: pair.split("/")[0] }) as Row))
const btc = computed(() => coins.value.find((row) => row.coin === "BTC"))
const num = (value: unknown) => (typeof value === "number" ? value : null)
const fastOn = computed(() => coins.value.filter((row) => row.f_vol === 1 || row.f_oi === 1))
const counts = computed(() => ({
  high: coins.value.filter((row) => row.d_turb === 2).length,
  hourHigh: coins.value.filter((row) => row.r_turb === 2).length,
  locked: coins.value.filter((row) => num(row.lock_kind)).length,
  unlockSoon: coins.value.filter((row) => num(row.unlock_days) != null && (row.unlock_days as number) <= 3).length,
}))

// single-candle signals of the last 24 h (they fire on one candle, so "now" would almost always be empty)
const lastSignal = computed(() => {
  const out: Record<string, Event> = {}
  for (const event of events.value) if (!out[event.pair]) out[event.pair] = event  // newest first from the api
  return out
})
const ago = (date: string) => age(Date.parse(date.replace(" ", "T")) / 1000, now.value)

// coins tab: search + sort
const find = ref("")
const sortKey = ref("risk_prob")
const sortDesc = ref(true)
const COLS = [
  { key: "coin", label: "Coin" }, { key: "close", label: "Price" }, { key: "d_turb", label: "Turbulence day" },
  { key: "r_turb", label: "Turbulence 24h" }, { key: "d_trend", label: "Trend" }, { key: "d_direction", label: "Direction" },
  { key: "risk_prob", label: "Big move risk" }, { key: "f_vol_z", label: "Fast volume z" }, { key: "f_oi_z", label: "Fast OI z" },
  { key: "lock_kind", label: "Lock" }, { key: "unlock_days", label: "Unlock in" }, { key: "buyback_pct", label: "Buyback /yr" }, { key: "last_signal", label: "Last signal (24 h)" },
  { key: "scan", label: "Scanner" },
]
function sortBy(key: string) { if (sortKey.value === key) sortDesc.value = !sortDesc.value; else { sortKey.value = key; sortDesc.value = key !== "coin" } }
const sorted = computed(() => {
  const query = find.value.trim().toUpperCase()
  const rows = coins.value.filter((row) => !query || row.coin.includes(query)).map((row) => ({ ...row, last_signal: lastSignal.value[row.pair]?.date ?? null, scan: scanned.value[coinOf(row.pair)]?.join(" ") ?? null }) as Row)
  const key = sortKey.value, dir = sortDesc.value ? -1 : 1
  return [...rows].sort((left: any, right: any) => {
    const leftValue = left[key], rightValue = right[key]
    if (leftValue == null) return 1
    if (rightValue == null) return -1
    return (leftValue > rightValue ? 1 : leftValue < rightValue ? -1 : 0) * dir
  })
})
// direction needs coinalyze's flow data; without a key it would say "warming up" forever
const dirLabel = (value: unknown) => (worker.value?.no_flow_key ? "needs Coinalyze key" : label(DIRECTION, num(value)))
const turbTone = (value: unknown) => (value === 2 ? "text-down" : value === 1 ? "text-warn" : "text-dim")
const trendTone = (value: unknown) => (value === 1 ? "text-up" : value === -1 ? "text-down" : "text-dim")

// ledger: random split by side, so each tag is read against random on its own side
const sideName = (entry: { tag: string; side: number }) => (entry.tag === "random" ? `random ${entry.side === 1 ? "long" : "short"}` : entry.tag)
const DAYS_NEEDED = 20
</script>

<template>
  <div class="space-y-3">
    <div class="flex flex-wrap items-center gap-3">
      <h1 class="text-xl font-semibold">BTCGate</h1>
      <span v-if="!off" class="text-sm" :class="health.tone">{{ health.text }}</span>
      <span v-if="worker?.phase === 'running'" class="text-sm text-dim num">
        {{ worker.analysed }} coins · candle {{ worker.candle?.slice(11, 16) }} UTC · {{ worker.analyse_s }}s · {{ status.rss_mb ?? "–" }}/{{ status.memory_mb }} MB · btcgate {{ worker.btcgate }}
        <template v-if="status.restarts"> · {{ status.restarts }} restart{{ status.restarts === 1 ? "" : "s" }}</template>
      </span>
      <div v-if="!off" class="ml-auto flex rounded-md border border-line overflow-hidden text-sm">
        <button v-for="tabName in (['market', 'coins', 'signals', 'scanner', 'ledger', 'book', 'settings'] as const)" :key="tabName" class="px-3 py-1 capitalize"
          :class="tab === tabName ? 'bg-hover text-ink' : 'text-dim hover:text-ink'" @click="pick(tabName)">{{ tabName }}</button>
      </div>
    </div>

    <div v-if="off" class="panel p-4 text-sm text-dim">BTCGate is off. Set <span class="num text-ink">btcgate: enabled: true</span> in config.yaml and restart NFIForge.</div>
    <div v-else-if="status && !status.installed" class="panel p-4 text-sm space-y-2">
      <div>BTCGate is on but its package isn't installed. Install it, then restart NFIForge:</div>
      <div class="num text-ink break-all">{{ status.install }}</div>
    </div>
    <BtcgateSettings v-else-if="tab === 'settings'" />
    <BtcgateSignals v-else-if="tab === 'signals'" />
    <BtcgateBook v-else-if="tab === 'book'" />
    <BtcgateScanner v-else-if="tab === 'scanner'" />
    <div v-else-if="!coins.length" class="panel p-4 text-sm text-dim">
      No labels yet. A first start loads about 2,500 candles for each of ~150 coins (a few minutes), then labels every coin after each 5 minute candle.
      <span v-if="worker?.error" class="block mt-2 text-warn">last problem: {{ worker.error }}</span>
    </div>

    <template v-else-if="tab === 'market'">
      <div class="grid gap-3 md:grid-cols-3">
        <PanelCard title="BTC">
          <dl v-if="btc" class="grid grid-cols-2 gap-y-1 text-sm num">
            <dt class="text-dim">Price</dt><dd>{{ price(btc.close) }}</dd>
            <dt class="text-dim">Trend</dt><dd :class="trendTone(btc.d_trend)">{{ label(TREND, num(btc.d_trend)) }}</dd>
            <dt class="text-dim">Turbulence day</dt><dd :class="turbTone(btc.d_turb)">{{ label(TURB, num(btc.d_turb)) }}</dd>
            <dt class="text-dim">Turbulence 24h</dt><dd :class="turbTone(btc.r_turb)">{{ label(TURB, num(btc.r_turb)) }}</dd>
            <dt class="text-dim">Direction</dt><dd>{{ dirLabel(btc.d_direction) }}</dd>
            <dt class="text-dim">Big move risk (4h)</dt><dd>{{ num(btc.risk_prob) == null ? "–" : `${((btc.risk_prob as number) * 100).toFixed(0)}%` }}</dd>
          </dl>
          <div v-else class="text-sm text-dim">BTC isn't in the coin list</div>
        </PanelCard>
        <PanelCard title="Calendar and volatility">
          <dl v-if="btc" class="grid grid-cols-2 gap-y-1 text-sm num">
            <dt class="text-dim">FOMC</dt><dd :class="btc.fomc ? 'text-warn' : ''">{{ btc.fomc ? `on (${num(btc.fomc_hours) ?? "?"} h)` : "no" }}</dd>
            <dt class="text-dim">US open</dt><dd :class="btc.us_open ? 'text-warn' : ''">{{ btc.us_open ? "yes" : "no" }}</dd>
            <dt class="text-dim">DVOL 6h change</dt><dd>{{ num(btc.dvol_6h) == null ? "–" : pct((btc.dvol_6h as number) * 100, 1) }}</dd>
            <dt class="text-dim">DVOL jump</dt><dd :class="btc.dvol_jump ? 'text-warn' : ''">{{ btc.dvol_jump ? "yes" : "no" }}</dd>
          </dl>
        </PanelCard>
        <PanelCard title="Across all coins">
          <dl class="grid grid-cols-2 gap-y-1 text-sm num">
            <dt class="text-dim">Turbulence HIGH (day)</dt><dd>{{ counts.high }}</dd>
            <dt class="text-dim">Turbulence HIGH (24h)</dt><dd>{{ counts.hourHigh }}</dd>
            <dt class="text-dim">Fast flags on</dt><dd>{{ fastOn.length }}</dd>
            <dt class="text-dim">Locked</dt><dd>{{ counts.locked }}</dd>
            <dt class="text-dim">Unlock within 3 days</dt><dd>{{ counts.unlockSoon }}</dd>
          </dl>
        </PanelCard>
      </div>
      <PanelCard :title="`Signals in the last 24 h · ${events.length}`">
        <div v-if="!events.length" class="text-sm text-dim">none: forced moves, contested spikes, catch-up calls and absorb warnings show here</div>
        <table v-else class="w-full text-sm num">
          <thead class="text-xs text-dim text-left border-b border-line"><tr>
            <th class="px-3 py-2 font-normal">When</th><th class="px-3 py-2 font-normal">Coin</th><th class="px-3 py-2 font-normal">Signal</th>
            <th class="px-3 py-2 font-normal">Strength</th><th class="px-3 py-2 font-normal">Turbulence day</th></tr></thead>
          <tbody><tr v-for="event in events.slice(0, 50)" :key="`${event.date}${event.pair}${event.layer}`" class="border-b border-line last:border-0">
            <td class="px-3 py-2 text-dim whitespace-nowrap">{{ ago(event.date) }} ago</td><td class="px-3 py-2 font-semibold">{{ event.pair.split("/")[0] }}</td>
            <td class="px-3 py-2" :class="sig(event.layer).tone">{{ sig(event.layer).label }}</td>
            <td class="px-3 py-2">{{ event.z == null ? "–" : event.z.toFixed(event.layer === "fp_contested" ? 3 : 1) }}</td>
            <td class="px-3 py-2" :class="turbTone(snap.coins[event.pair]?.d_turb)">{{ label(TURB, num(snap.coins[event.pair]?.d_turb)) }}</td></tr></tbody>
        </table>
      </PanelCard>
      <PanelCard :title="`Fast flags on now · ${fastOn.length}`">
        <div v-if="!fastOn.length" class="text-sm text-dim">none</div>
        <table v-else class="w-full text-sm num">
          <thead class="text-xs text-dim text-left border-b border-line"><tr>
            <th class="px-3 py-2 font-normal">Coin</th><th class="px-3 py-2 font-normal">Price</th><th class="px-3 py-2 font-normal">Fast volume z</th>
            <th class="px-3 py-2 font-normal">Fast OI z</th><th class="px-3 py-2 font-normal">Turbulence day</th></tr></thead>
          <tbody><tr v-for="row in fastOn" :key="row.pair" class="border-b border-line last:border-0">
            <td class="px-3 py-2 font-semibold">{{ row.coin }}</td><td class="px-3 py-2">{{ price(row.close) }}</td>
            <td class="px-3 py-2" :class="row.f_vol === 1 ? 'text-warn' : ''">{{ num(row.f_vol_z)?.toFixed(1) ?? "–" }}</td>
            <td class="px-3 py-2" :class="row.f_oi === 1 ? 'text-warn' : ''">{{ num(row.f_oi_z)?.toFixed(1) ?? "–" }}</td>
            <td class="px-3 py-2" :class="turbTone(row.d_turb)">{{ label(TURB, num(row.d_turb)) }}</td></tr></tbody>
        </table>
      </PanelCard>
    </template>

    <PanelCard v-else-if="tab === 'coins'" :pad="false" :title="`Coins · ${coins.length}`">
      <template #actions><input v-model="find" placeholder="find coin" class="w-32 rounded-md bg-raised border border-line px-2 py-1 text-ink text-xs num" /></template>
      <div class="overflow-x-auto">
        <table class="w-full text-sm num">
          <thead class="text-xs text-dim text-left border-b border-line"><tr>
            <th v-for="column in COLS" :key="column.key" class="px-3 py-2 font-normal cursor-pointer select-none whitespace-nowrap hover:text-ink" @click="sortBy(column.key)">
              {{ column.label }}<span v-if="sortKey === column.key">{{ sortDesc ? " ↓" : " ↑" }}</span></th></tr></thead>
          <tbody><tr v-for="row in sorted" :key="row.pair" class="border-b border-line last:border-0 hover:bg-hover">
            <td class="px-3 py-2 font-semibold">{{ row.coin }}</td>
            <td class="px-3 py-2">{{ price(row.close) }}</td>
            <td class="px-3 py-2" :class="turbTone(row.d_turb)">{{ label(TURB, num(row.d_turb)) }}</td>
            <td class="px-3 py-2" :class="turbTone(row.r_turb)">{{ label(TURB, num(row.r_turb)) }}</td>
            <td class="px-3 py-2" :class="trendTone(row.d_trend)">{{ label(TREND, num(row.d_trend)) }}</td>
            <td class="px-3 py-2">{{ dirLabel(row.d_direction) }}</td>
            <td class="px-3 py-2">{{ num(row.risk_prob) == null ? "–" : `${((row.risk_prob as number) * 100).toFixed(0)}%` }}</td>
            <td class="px-3 py-2" :class="row.f_vol === 1 ? 'text-warn' : ''">{{ num(row.f_vol_z)?.toFixed(1) ?? "–" }}</td>
            <td class="px-3 py-2" :class="row.f_oi === 1 ? 'text-warn' : ''">{{ num(row.f_oi_z)?.toFixed(1) ?? "–" }}</td>
            <td class="px-3 py-2" :class="num(row.lock_kind) ? 'text-down' : 'text-dim'">{{ num(row.lock_kind) ? label(LOCK, num(row.lock_kind)) : "–" }}</td>
            <td class="px-3 py-2" :class="num(row.unlock_days) != null && (row.unlock_days as number) <= 3 ? 'text-warn' : ''">{{ num(row.unlock_days) == null ? "–" : `${(row.unlock_days as number).toFixed(0)} d` }}</td>
            <td class="px-3 py-2" title="handed to holders a year (buybacks or staking payouts) as % of market cap, untested">{{ num(row.buyback_pct) == null ? "–" : `${(row.buyback_pct as number).toFixed(1)}%` }}</td>
            <td class="px-3 py-2 whitespace-nowrap"><template v-if="lastSignal[row.pair]"><span :class="sig(lastSignal[row.pair].layer).tone">{{ sig(lastSignal[row.pair].layer).label }}</span> <span class="text-dim">{{ ago(lastSignal[row.pair].date) }}</span></template><span v-else class="text-dim">–</span></td>
            <td class="px-3 py-2 whitespace-nowrap">{{ scanned[coinOf(row.pair)]?.map(scanText).join(", ") ?? "–" }}</td>
          </tr></tbody>
        </table>
      </div>
    </PanelCard>

    <template v-else>
      <PanelCard :pad="false" title="Signal ledger">
        <p class="px-4 pb-2 text-xs text-dim">Every signal is scored as a 24 h trade with a target and a stop at 2x the coin's 1h ATR. Read each tag against random on the same side, by market day: a tag needs {{ DAYS_NEEDED }} market days before it's judged.</p>
        <div class="overflow-x-auto">
          <table class="w-full text-sm num">
            <thead class="text-xs text-dim text-left border-b border-line"><tr>
              <th class="px-3 py-2 font-normal">Tag</th><th class="px-3 py-2 font-normal">Side</th><th class="px-3 py-2 font-normal">Signals</th>
              <th class="px-3 py-2 font-normal">Scored</th><th class="px-3 py-2 font-normal">Market days</th><th class="px-3 py-2 font-normal">Avg result</th>
              <th class="px-3 py-2 font-normal">Target hit</th><th class="px-3 py-2 font-normal">Stopped</th><th class="px-3 py-2 font-normal">24 h limit</th></tr></thead>
            <tbody><tr v-for="entry in ledger.tags" :key="`${entry.tag}${entry.side}`" class="border-b border-line last:border-0">
              <td class="px-3 py-2 font-semibold">{{ sideName(entry) }}</td>
              <td class="px-3 py-2" :class="entry.side === 1 ? 'text-up' : 'text-down'">{{ entry.side === 1 ? "long" : "short" }}</td>
              <td class="px-3 py-2">{{ entry.signals }}</td><td class="px-3 py-2">{{ entry.scored }}</td>
              <td class="px-3 py-2" :class="entry.days >= DAYS_NEEDED ? 'text-up' : 'text-dim'">{{ entry.days }}/{{ DAYS_NEEDED }}</td>
              <td class="px-3 py-2" :class="entry.avg_pct == null ? '' : entry.avg_pct > 0 ? 'text-up' : 'text-down'">{{ pct(entry.avg_pct) }}</td>
              <td class="px-3 py-2">{{ entry.target_pct == null ? "–" : `${entry.target_pct.toFixed(0)}%` }}</td>
              <td class="px-3 py-2">{{ entry.stop_pct == null ? "–" : `${entry.stop_pct.toFixed(0)}%` }}</td>
              <td class="px-3 py-2">{{ entry.time_pct == null ? "–" : `${entry.time_pct.toFixed(0)}%` }}</td></tr>
              <tr v-if="!ledger.tags.length"><td colspan="9" class="px-3 py-3 text-dim">no signals yet</td></tr></tbody>
          </table>
        </div>
      </PanelCard>
    </template>
  </div>
</template>
