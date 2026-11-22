<script setup lang="ts">
import { computed } from "vue"
import Sparkline from "@/components/charts/Sparkline.vue"
import ProfitBoxes from "@/components/trades/ProfitBoxes.vue"
import { age, money, signed } from "@/lib/format"
import { nfiMode } from "@/lib/nfi"

// one open trade (or an empty slot): pair, side, leverage, nfi mode, p&l, price since entry, liquidation distance, dca adds
const props = defineProps<{ index: number; trade?: Record<string, any>; prices?: [number, number][]; isNfi?: boolean; loopAge?: string }>()

const slotTrade = computed(() => props.trade)
const pnlPct = computed(() => (slotTrade.value ? (slotTrade.value.total_profit_ratio ?? slotTrade.value.profit_ratio ?? 0) * 100 : 0))
const liqDist = computed(() => {
  const trade = slotTrade.value
  if (!trade?.liquidation_price || !trade.current_rate) return null
  return (Math.abs(trade.current_rate - trade.liquidation_price) / trade.current_rate) * 100
})
// price move since entry, flipped for shorts so up = good
const spark = computed(() => {
  const trade = slotTrade.value
  if (!trade || !props.prices?.length) return []
  const since = (trade.open_timestamp ?? 0) / 1000 - 1800
  const sign = trade.is_short ? -1 : 1
  return props.prices.filter(([ts]) => ts >= since).map(([ts, close]) => ({ time: ts, value: sign * ((close / trade.open_rate - 1) * 100) }))
})
const adds = computed(() => Math.max(0, (slotTrade.value?.nr_of_successful_entries ?? 1) - 1))
const mode = computed(() => (props.isNfi ? nfiMode(slotTrade.value?.enter_tag) : null))
</script>

<template>
  <div v-if="slotTrade" class="panel p-3 min-w-0" :style="{ borderColor: pnlPct < 0 ? 'var(--red-dim)' : 'var(--line)' }">
    <div class="flex items-center gap-2 text-sm min-w-0">
      <span class="text-[10px] text-faint num">S{{ index + 1 }}</span>
      <span class="font-semibold truncate">{{ slotTrade.pair.split("/")[0] }}</span>
      <span class="text-[11px] px-1.5 rounded shrink-0" :class="slotTrade.is_short ? 'text-down bg-[var(--red-dim)]' : 'text-up bg-[var(--green-dim)]'">{{ slotTrade.is_short ? "▼ S" : "▲ L" }} {{ slotTrade.leverage }}x</span>
      <span class="text-[11px] text-dim truncate">{{ mode ? `${mode} · ` : "" }}{{ slotTrade.enter_tag }}</span>
    </div>
    <div v-if="slotTrade.open_timestamp" class="text-[11px] text-dim num mt-0.5">open {{ age(slotTrade.open_timestamp / 1000) }}</div>
    <ProfitBoxes :trade="slotTrade" compact class="mt-1.5" />
    <Sparkline v-if="spark.length > 1" :data="spark" pnl :height="48" />
    <div v-else class="h-12 grid place-items-center text-[11px] text-faint">loading price…</div>
    <div v-if="liqDist != null" class="mt-1">
      <div class="flex justify-between text-[10px] text-dim num"><span>liq {{ money(slotTrade.liquidation_price, 4) }}</span><span :class="liqDist < 10 ? 'text-down' : liqDist < 20 ? 'text-warn' : ''">{{ liqDist.toFixed(1) }}% away</span></div>
      <div class="h-1.5 rounded bg-raised overflow-hidden mt-0.5">
        <div class="h-full rounded" :style="{ width: Math.min(100, liqDist * 2) + '%', background: liqDist < 10 ? 'var(--red)' : liqDist < 20 ? 'var(--amber)' : 'var(--green)' }" />
      </div>
    </div>
    <div class="flex justify-between text-[10px] text-dim mt-1.5 num">
      <span>stake {{ money(slotTrade.stake_amount) }}</span>
      <span v-if="adds">{{ adds }} add{{ adds > 1 ? "s" : "" }}</span>
      <span v-if="slotTrade.realized_profit">realised {{ signed(slotTrade.realized_profit) }}</span>
    </div>
  </div>
  <div v-else class="panel px-3 py-2 sm:p-3 flex sm:grid items-center gap-3 sm:place-items-center sm:text-center sm:min-h-[150px] opacity-70">
    <div class="contents sm:block">
      <div class="text-[10px] text-faint num">S{{ index + 1 }}</div>
      <div class="h-2 w-2 rounded-full sm:mx-auto sm:my-2 scan" />
      <div class="text-sm text-dim">Empty slot</div>
      <div class="text-[11px] text-faint ml-auto sm:ml-0">scanning{{ loopAge ? ` · ${loopAge} ago` : "" }}</div>
    </div>
  </div>
</template>

<style scoped>
/* slow pulse on empty slots so the page feels alive */
.scan { background: var(--brand-b); animation: pulse 2s var(--ease) infinite; }
@keyframes pulse { 0%, 100% { opacity: 0.25; transform: scale(0.8); } 50% { opacity: 1; transform: scale(1.2); box-shadow: 0 0 10px var(--brand-b); } }
</style>
