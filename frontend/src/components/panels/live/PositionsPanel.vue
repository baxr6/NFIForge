<script setup lang="ts">
import { computed, ref } from "vue"
import DownloadButton from "@/components/DownloadButton.vue"
import Drawer from "@/components/trades/Drawer.vue"
import { walletOf } from "@/lib/trading"
import EntryForm from "@/components/trades/EntryForm.vue"
import TradeInspector from "@/components/trades/TradeInspector.vue"
import { useFiat } from "@/lib/fiat"
import { openSheet, ordersSheet } from "@/lib/tradeSheets"
import { age, money, pct, price, signed, tone } from "@/lib/format"
import { nfiMode } from "@/lib/nfi"
import { ladderShort } from "@/lib/risk"
import { totalProfit } from "@/lib/profit"
import type { Trade } from "@/lib/trades"
import { useAuth } from "@/stores/auth"
import { useLive } from "@/stores/live"
import { badges, btcgateOn, useBtcgateCoins } from "@/lib/btcgate"

// open trades of the bot picked on Trading (the same pick on every page), or of every bot; click a row for the full
// inspector
const live = useLive()
useBtcgateCoins()  // btcgate badges per coin, when btcgate is on
const names = computed(() => Object.keys(live.bots))
const all = ref(false)
const one = computed(() => (all.value || names.value.length < 2 ? null : live.picked))
const auth = useAuth()
// new entry button: admins, and only when some bot has trading on
const canEnter = computed(() => auth.isAdmin && Object.values(live.bots).some((bot) => bot.trading && bot.connected))
const entering = ref(false)
const entrySent = ref("")
type Row = Trade & { _bot: string; _nfi: boolean; _liq: number | null; _adds: number; _ladder: string; _heavy: boolean; _total: number; _totalPct: number }
const rows = computed<Row[]>(() =>
  Object.values(live.bots).filter((bot) => !one.value || bot.name === one.value).flatMap((bot) =>
    ((bot.status ?? []) as Trade[]).map((trade) => ({
      ...trade,
      _bot: bot.name,
      _nfi: !!bot.is_nfi,
      _liq: trade.liquidation_price && trade.current_rate ? (Math.abs(trade.current_rate - trade.liquidation_price) / trade.current_rate) * 100 : null,
      _adds: Math.max(0, (trade.nr_of_successful_entries ?? 1) - 1),
      _ladder: ladderShort(trade),
      // more than twice an even share of the account (wallet / slots)
      _heavy: !!walletOf(bot.balance) && Number(bot.config?.max_open_trades) > 0 && (trade.stake_amount ?? 0) > (2 * walletOf(bot.balance)!) / Number(bot.config.max_open_trades),
      _total: totalProfit(trade).abs,
      _totalPct: totalProfit(trade).pct,
    })),
  ),
)

// sortable columns
const COLS = [
  { key: "_bot", label: "Bot" }, { key: "pair", label: "Pair" }, { key: "is_short", label: "Side" }, { key: "enter_tag", label: "Tag" },
  { key: "open_timestamp", label: "Age" }, { key: "open_rate", label: "Avg" }, { key: "current_rate", label: "Price" }, { key: "stake_amount", label: "Stake" },
  { key: "_adds", label: "Adds" },
  { key: "_total", label: "Total profit" }, { key: "_totalPct", label: "Total %" },
  { key: "profit_abs", label: "Current profit" }, { key: "profit_ratio", label: "Current %" }, { key: "funding_fees", label: "Funding" }, { key: "_liq", label: "Liq dist" },
] as const
// the bot column only when more than one bot is shown
const cols = computed(() => COLS.filter((column) => column.key !== "_bot" || !one.value))
const sortKey = ref<string>("profit_abs")
const asc = ref(true)
function sortBy(key: string) { asc.value = sortKey.value === key ? !asc.value : true; sortKey.value = key }
const sorted = computed(() => [...rows.value].sort((left, right) => {
  const leftValue = left[sortKey.value] ?? -Infinity, rightValue = right[sortKey.value] ?? -Infinity
  return (leftValue < rightValue ? -1 : leftValue > rightValue ? 1 : 0) * (asc.value ? 1 : -1)
}))

const total = computed(() => rows.value.reduce((sum, trade) => sum + trade._total, 0))
const current = computed(() => rows.value.reduce((sum, trade) => sum + (trade.profit_abs ?? 0), 0))
const stake = computed(() => rows.value.reduce((sum, trade) => sum + (trade.stake_amount ?? 0), 0))
const funding = computed(() => rows.value.reduce((sum, trade) => sum + (trade.funding_fees ?? 0), 0))
const picked = ref<Row | null>(null)
const fiat = useFiat(() => "USDT")
const sheets = () => [openSheet(sorted.value, fiat.rate.value), ordersSheet(sorted.value)]
// keep the open drawer on live data
const pickedLive = computed(() => (picked.value ? rows.value.find((row) => row._bot === picked.value!._bot && row.trade_id === picked.value!.trade_id) ?? picked.value : null))
</script>

<template>
  <div class="h-full flex flex-col gap-2 min-h-0">
    <div v-if="names.length > 1" class="flex flex-wrap rounded-md border border-line overflow-hidden text-xs self-start shrink-0">
      <button class="px-3 py-1.5" :class="all ? 'bg-raised text-ink' : 'text-dim hover:text-ink'" @click="all = true">All bots</button>
      <button v-for="name in names" :key="name" class="px-3 py-1.5 border-l border-line" :class="!all && name === live.picked ? 'bg-raised text-ink' : 'text-dim hover:text-ink'"
        @click="all = false; live.picked = name">{{ name }}</button>
    </div>
    <div class="flex flex-wrap items-baseline gap-3 shrink-0">
      <button v-if="canEnter" class="text-xs px-3 py-2 md:py-1 rounded-md border border-line text-dim hover:text-ink" @click="entering = true; entrySent = ''">+ new entry</button>
      <span v-if="entrySent" class="text-xs text-up">✓ {{ entrySent }}</span>
      <span class="text-sm text-dim num">{{ rows.length }} open · stake {{ money(stake) }} · total <span :class="tone(total)">{{ signed(total) }}</span> · current <span :class="tone(current)">{{ signed(current) }}</span> · funding <span :class="tone(funding)">{{ signed(funding) }}</span></span>
      <DownloadButton class="ml-auto" name="positions" :sheets="sheets" :disabled="!rows.length" />
    </div>

    <!-- phones: one card per trade, sorted by the same keys -->
    <div class="md:hidden flex flex-col gap-2">
      <label v-if="rows.length > 1" class="flex items-center gap-2 text-xs text-dim">sort
        <select v-model="sortKey" class="rounded-md bg-raised border border-line px-2 py-2 text-ink text-sm">
          <option v-for="column in cols" :key="column.key" :value="column.key">{{ column.label }}</option>
        </select>
        <button class="px-3 py-2 rounded-md border border-line text-ink" @click="asc = !asc">{{ asc ? "▲" : "▼" }}</button>
      </label>
      <button v-for="trade in sorted" :key="`${trade._bot}-${trade.trade_id}`" class="panel p-3 text-left num active:bg-hover" @click="picked = trade">
        <div class="flex items-baseline gap-2">
          <span class="font-semibold text-ink">{{ trade.pair.split("/")[0] }}</span>
          <span :class="trade.is_short ? 'text-down' : 'text-up'">{{ trade.is_short ? "▼ S" : "▲ L" }}</span><span class="text-dim text-xs">{{ trade.leverage }}x</span>
          <span class="ml-auto text-lg font-semibold" :class="tone(trade._total)">{{ signed(trade._total) }}</span>
          <span class="text-sm w-16 text-right" :class="tone(trade._totalPct)">{{ pct(trade._totalPct) }}</span>
        </div>
        <div class="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-dim">
          <span v-if="rows.some((row) => row._bot !== trade._bot)">{{ trade._bot }}</span>
          <span>{{ trade._nfi && nfiMode(trade.enter_tag) ? `${nfiMode(trade.enter_tag)} · ` : "" }}{{ trade.enter_tag }}</span>
          <span>{{ trade.open_timestamp ? age(trade.open_timestamp / 1000) : "–" }}</span>
          <span>avg {{ price(trade.open_rate) }} → <span :class="tone(trade.profit_ratio)">{{ price(trade.current_rate) }}</span></span>
          <span :class="trade._heavy ? 'text-warn' : ''">stake {{ money(trade.stake_amount) }}</span>
          <span v-if="trade._adds">adds {{ trade._adds }}<span v-if="trade._ladder"> {{ trade._ladder }}</span></span>
          <span v-if="trade._liq != null" :class="trade._liq < 10 ? 'text-down' : trade._liq < 20 ? 'text-warn' : ''">liq {{ trade._liq.toFixed(1) }}%</span>
        </div>
        <div v-if="btcgateOn && badges(trade.pair).length" class="mt-1 flex flex-wrap gap-1">
          <span v-for="badge in badges(trade.pair)" :key="badge.text" class="text-[11px] rounded border px-1.5" :class="badge.tone" :title="badge.title">{{ badge.text }}</span>
        </div>
      </button>
      <div v-if="!rows.length" class="panel px-3 py-8 text-center text-dim">no open trades</div>
    </div>

    <div class="panel overflow-auto flex-1 min-h-0 hidden md:block">
      <table class="w-full text-sm num">
        <thead class="text-xs text-dim text-left border-b border-line">
          <tr>
            <th v-for="column in cols" :key="column.key" class="px-3 py-2 font-normal cursor-pointer select-none whitespace-nowrap hover:text-ink" @click="sortBy(column.key)">
              {{ column.label }}<span v-if="sortKey === column.key" class="text-brand-b"> {{ asc ? "▲" : "▼" }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="trade in sorted" :key="`${trade._bot}-${trade.trade_id}`" class="border-b border-line last:border-0 hover:bg-hover cursor-pointer" @click="picked = trade">
            <td v-if="!one" class="px-3 py-2 text-dim">{{ trade._bot }}</td>
            <td class="px-3 py-2"><span class="font-semibold">{{ trade.pair.split("/")[0] }}</span>
              <span v-for="badge in btcgateOn ? badges(trade.pair) : []" :key="badge.text" class="ml-1 text-[11px] rounded border px-1 whitespace-nowrap" :class="badge.tone" :title="badge.title">{{ badge.text }}</span></td>
            <td class="px-3 py-2"><span :class="trade.is_short ? 'text-down' : 'text-up'">{{ trade.is_short ? "▼ S" : "▲ L" }}</span> <span class="text-dim">{{ trade.leverage }}x</span></td>
            <td class="px-3 py-2 text-dim">{{ trade._nfi && nfiMode(trade.enter_tag) ? `${nfiMode(trade.enter_tag)} · ` : "" }}{{ trade.enter_tag }}</td>
            <td class="px-3 py-2">{{ trade.open_timestamp ? age(trade.open_timestamp / 1000) : "–" }}</td>
            <td class="px-3 py-2">{{ price(trade.open_rate) }}</td>
            <!-- green above the average for a long, below it for a short -->
            <td class="px-3 py-2" :class="tone(trade.profit_ratio)">{{ price(trade.current_rate) }}</td>
            <td class="px-3 py-2" :class="trade._heavy ? 'text-warn' : ''" :title="trade._heavy ? 'more than twice an even share of the account' : undefined">{{ money(trade.stake_amount) }}</td>
            <td class="px-3 py-2 whitespace-nowrap">{{ trade._adds || "" }}<span v-if="trade._ladder" class="text-dim text-xs"> {{ trade._ladder }}</span></td>
            <td class="px-3 py-2" :class="tone(trade._total)">{{ signed(trade._total) }}</td>
            <td class="px-3 py-2" :class="tone(trade._totalPct)">{{ pct(trade._totalPct) }}</td>
            <td class="px-3 py-2" :class="tone(trade.profit_abs)">{{ signed(trade.profit_abs) }}</td>
            <td class="px-3 py-2" :class="tone(trade.profit_ratio)">{{ pct((trade.profit_ratio ?? 0) * 100) }}</td>
            <td class="px-3 py-2" :class="trade.funding_fees ? tone(trade.funding_fees) : 'text-faint'">{{ trade.funding_fees ? signed(trade.funding_fees) : "–" }}</td>
            <td class="px-3 py-2" :class="trade._liq == null ? 'text-faint' : trade._liq < 10 ? 'text-down' : trade._liq < 20 ? 'text-warn' : ''">{{ trade._liq == null ? "–" : `${trade._liq.toFixed(1)}%` }}</td>
          </tr>
          <tr v-if="!rows.length"><td :colspan="cols.length" class="px-3 py-8 text-center text-dim">no open trades</td></tr>
        </tbody>
      </table>
    </div>

    <Drawer v-if="entering" @close="entering = false">
      <EntryForm @done="(message) => { entering = false; entrySent = message }" @cancel="entering = false" />
    </Drawer>
    <Drawer v-if="pickedLive" @close="picked = null">
      <TradeInspector :trade="pickedLive" :bot="pickedLive._bot" :is-nfi="pickedLive._nfi"
        :custom-data="live.bots[pickedLive._bot]?.custom_data" :history="live.bots[pickedLive._bot]?.trades?.trades" :wallet="walletOf(live.bots[pickedLive._bot]?.balance)" />
    </Drawer>
  </div>
</template>
