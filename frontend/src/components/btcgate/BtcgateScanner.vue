<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import PanelCard from "@/components/layout/PanelCard.vue"
import { SCAN_LABEL, scanText } from "@/lib/btcgate"
import { age, money, pct } from "@/lib/format"

// btcgate's coin scanner (worker.scan, every 30 min) and recovery list (every 6 h). they describe what happened; the
// history lines say what followed such moves before, not a promise. nothing here changes a bot or its blacklist
type Scan = { coin: string; pair: string; labels: string[]; r24: number; spread: number; r7: number | null; vol: number; rank: number; listed: boolean; reasons: string[]; known: string[]; extras: string[] }
type Rec = { coin: string; vol: number; r7: number | null; r30: number | null; checks: Record<string, boolean>; passed: number }
type Data = { scan: { time?: number; rows: Scan[] }; recovery: { time?: number; floor?: number | null; rows: Rec[]; check_names?: Record<string, string> } }
const data = ref<Data | null>(null)
async function load() {
  const response = await fetch("/api/btcgate/scanner").catch(() => null)
  if (response?.ok) data.value = await response.json()
}
let timer = 0
onMounted(() => { load(); timer = window.setInterval(load, 60_000) })
onBeforeUnmount(() => clearInterval(timer))

const label = ref("")
const listedOnly = ref(false)
const rows = computed(() => (data.value?.scan.rows ?? []).filter((row) => (!label.value || row.labels.includes(label.value)) && (!listedOnly.value || row.listed)))
const open = ref<string[]>([])
const toggle = (coin: string) => (open.value = open.value.includes(coin) ? open.value.filter((other) => other !== coin) : [...open.value, coin])
const usd = (value: number) => (value >= 1e9 ? `$${(value / 1e9).toFixed(1)}B` : `$${money(value / 1e6, 0)}M`)
const ratioPct = (value: number | null | undefined) => (value == null ? "–" : pct(value * 100, 1))
const failed = (record: Rec) => Object.entries(record.checks).filter(([, ok]) => !ok).map(([key]) => data.value?.recovery.check_names?.[key] ?? key)
</script>

<template>
  <div class="space-y-3">
    <PanelCard :pad="false" title="Flagged now">
      <template #actions><span class="ml-auto text-xs text-faint">{{ data?.scan.time ? `checked ${age(data.scan.time)} ago · every 30 min` : "first check within 30 min of the worker starting" }}</span></template>
      <div class="px-4 pb-2 space-y-2">
        <p class="text-xs text-dim">The labels describe what happened. Under each coin: what followed such moves on Binance perps in 2024-26 (recent history, not a promise) and BTCGate's tested readings for it. Tap a coin for the detail. "Bots" = in one of your bots' whitelists.</p>
        <div class="flex flex-wrap items-center gap-2 text-sm">
          <button v-for="option in ['', ...Object.keys(SCAN_LABEL)]" :key="option" class="px-2 py-0.5 rounded-md border text-xs"
            :class="label === option ? 'border-brand-b/60 bg-brand-b/15 text-ink' : 'border-line text-dim hover:text-ink'" @click="label = option">{{ option ? scanText(option) : "all" }}</button>
          <label class="ml-2 flex items-center gap-1.5 text-dim"><input v-model="listedOnly" type="checkbox" /> only my bots' coins</label>
        </div>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-sm num whitespace-nowrap">
          <thead class="text-xs text-dim text-left border-b border-line"><tr>
            <th class="px-3 py-2 font-normal">Coin</th><th class="px-3 py-2 font-normal">Labels</th><th class="px-3 py-2 font-normal">24 h</th>
            <th class="px-3 py-2 font-normal">24 h range</th><th class="px-3 py-2 font-normal">7 d</th><th class="px-3 py-2 font-normal">Volume 24 h</th>
            <th class="px-3 py-2 font-normal">Rank</th></tr></thead>
          <tbody>
            <template v-for="row in rows" :key="row.coin">
              <tr class="border-b border-line cursor-pointer hover:bg-hover" @click="toggle(row.coin)">
                <td class="px-3 py-2 font-semibold">{{ row.coin }}<span v-if="row.listed" class="ml-1 text-[10px] text-brand-b">bots</span></td>
                <td class="px-3 py-2">{{ row.labels.map(scanText).join(", ") }}</td>
                <td class="px-3 py-2" :class="row.r24 > 0 ? 'text-up' : 'text-down'">{{ ratioPct(row.r24) }}</td>
                <td class="px-3 py-2 text-dim">{{ ratioPct(row.spread) }}</td>
                <td class="px-3 py-2" :class="row.r7 == null ? 'text-dim' : row.r7 > 0 ? 'text-up' : 'text-down'">{{ ratioPct(row.r7) }}</td>
                <td class="px-3 py-2">{{ usd(row.vol) }}</td><td class="px-3 py-2 text-dim">#{{ row.rank }}</td>
              </tr>
              <tr v-if="open.includes(row.coin)" class="border-b border-line bg-raised/40">
                <td colspan="7" class="px-4 py-2 whitespace-normal">
                  <ul class="space-y-0.5 text-dim text-xs">
                    <li v-for="(reason, i) in [...row.reasons, ...row.known, ...row.extras].filter(Boolean)" :key="i">↳ {{ reason }}</li>
                  </ul>
                </td>
              </tr>
            </template>
            <tr v-if="!rows.length"><td colspan="7" class="px-3 py-3 text-dim">nothing flagged</td></tr>
          </tbody>
        </table>
      </div>
    </PanelCard>

    <PanelCard :pad="false" title="Recovery list">
      <template #actions><span class="ml-auto text-xs text-faint">{{ data?.recovery.time ? `checked ${age(data.recovery.time)} ago · every 6 h` : "" }}</span></template>
      <p class="px-4 pb-2 text-xs text-dim">
        Coins on your bots' blacklists that look tradable again: blocked by name (not a category like stocks or stablecoins), trading at least
        <span class="num text-ink">{{ data?.recovery.floor ? usd(data.recovery.floor) : "–" }}</span> a day (your bots' quietest coin), no lock and no delisting notice in 30 days,
        passing at least 6 of 8 checks. The checks describe; none of them predicted returns in testing. Review by hand: nothing is changed.
      </p>
      <div class="overflow-x-auto">
        <table class="w-full text-sm num">
          <thead class="text-xs text-dim text-left border-b border-line"><tr>
            <th class="px-3 py-2 font-normal">Coin</th><th class="px-3 py-2 font-normal">Verdict</th><th class="px-3 py-2 font-normal">Volume 24 h</th>
            <th class="px-3 py-2 font-normal">7 d</th><th class="px-3 py-2 font-normal">30 d</th><th class="px-3 py-2 font-normal">Failed checks</th></tr></thead>
          <tbody><tr v-for="record in data?.recovery.rows ?? []" :key="record.coin" class="border-b border-line last:border-0">
            <td class="px-3 py-2 font-semibold">{{ record.coin }}</td>
            <td class="px-3 py-2 whitespace-nowrap" :class="record.passed >= 8 ? 'text-up' : 'text-warn'">{{ record.passed >= 8 ? "✅ could come off" : "🟡 close, review" }} ({{ record.passed }}/8)</td>
            <td class="px-3 py-2">{{ usd(record.vol) }}</td><td class="px-3 py-2">{{ ratioPct(record.r7) }}</td><td class="px-3 py-2">{{ ratioPct(record.r30) }}</td>
            <td class="px-3 py-2 text-dim">{{ failed(record).join(", ") || "none" }}</td></tr>
            <tr v-if="!(data?.recovery.rows ?? []).length"><td colspan="6" class="px-3 py-3 text-dim">no blacklisted coin passes 6 of the 8 checks right now</td></tr></tbody>
        </table>
      </div>
    </PanelCard>
  </div>
</template>
