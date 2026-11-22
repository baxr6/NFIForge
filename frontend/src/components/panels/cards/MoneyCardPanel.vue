<script setup lang="ts">
import { reactive } from "vue"
import AreaChart from "@/components/charts/AreaChart.vue"
import StatCard from "@/components/trading/StatCard.vue"
import { useFiat } from "@/lib/fiat"
import { money, signed, tone } from "@/lib/format"
import { useTrading } from "@/lib/trading"

// one money card as its own panel (the old Money panel split up so each can be placed anywhere)
const props = defineProps<{ card: "equity" | "open" | "today" | "net" | "winrate" | "notional" | "stake" | "drawdown" | "expectancy" }>()
const trading = reactive(useTrading())
const fiat = useFiat(() => trading.quote)
</script>

<template>
  <div v-if="props.card === 'equity'" class="panel p-3 h-full min-w-0 flex flex-col">
    <div class="flex items-center justify-between text-xs text-dim">
      <span>Equity (wallet + open)</span>
      <span class="num">start {{ money(trading.start) }}</span>
    </div>
    <div class="num text-3xl 2xl:text-4xl font-semibold mt-1">{{ money(trading.equity) }} <span class="text-sm text-dim font-normal">{{ trading.quote }}</span></div>
    <div v-if="fiat.on.value" class="num text-sm text-dim" :title="fiat.note.value">≈ {{ fiat.amount(trading.equity) }}</div>
    <div class="flex flex-wrap gap-x-4 text-xs num mt-1">
      <span :class="tone(trading.profit.profit_all_coin)">{{ signed(trading.profit.profit_all_coin) }} since start<template v-if="fiat.on.value"> ({{ fiat.change(trading.profit.profit_all_coin) }})</template></span>
      <span class="text-dim">wallet {{ money(trading.wallet) }}</span>
    </div>
    <div v-if="fiat.on.value" class="text-[10px] text-faint num mt-0.5">{{ fiat.note.value }}</div>
    <div class="flex-1 min-h-[60px]">
      <AreaChart v-if="trading.eqHist.length > 1" :data="trading.eqHist" mode="equity" height="fill" />
      <div v-else class="h-full grid place-items-center text-xs text-faint">equity history builds up from now (one point a minute)</div>
    </div>
  </div>
  <StatCard v-else-if="props.card === 'open'" label="Open P&L" :value="signed(trading.openPnl)" :unit="trading.quote" :value-class="tone(trading.openPnl)" :sub="`${trading.open.length} position${trading.open.length === 1 ? '' : 's'}${fiat.on.value ? ` · ≈ ${fiat.change(trading.openPnl)}` : ''}`" />
  <StatCard v-else-if="props.card === 'today'" label="Today realised" :value="signed(trading.todayRealised)" :unit="trading.quote" :value-class="tone(trading.todayRealised)"
    :sub="`${trading.todayCloses.length} close${trading.todayCloses.length === 1 ? '' : 's'} · with open ${signed(trading.todayRealised + trading.openPnl)}`" />
  <StatCard v-else-if="props.card === 'net'" label="True net" :value="signed(trading.profit.profit_all_coin)" :unit="trading.quote" :value-class="tone(trading.profit.profit_all_coin)"
    :sub="`closed ${signed(trading.profit.profit_closed_coin)} · n=${trading.profit.closed_trade_count ?? 0}`" />
  <StatCard v-else-if="props.card === 'winrate'" label="Win rate" :value="trading.wins + trading.losses ? `${((trading.wins / (trading.wins + trading.losses)) * 100).toFixed(1)}%` : '–'"
    :sub="trading.ci ? `95% CI ${(trading.ci[0] * 100).toFixed(0)}–${(trading.ci[1] * 100).toFixed(0)}% · ${trading.wins}W ${trading.losses}L` : ''" :badge="trading.wins + trading.losses < 30 ? 'low sample' : undefined" />
  <StatCard v-else-if="props.card === 'notional'" label="Notional exposure" :value="money(trading.notional)" :unit="trading.quote" :sub="`stake in trades ${money(trading.stakeIn)}`" />
  <StatCard v-else-if="props.card === 'stake'" label="Stake used" :value="`${trading.stakeUsed.toFixed(1)}%`" :sub="`${money(trading.stakeIn)} / ${money(trading.wallet)}`" />
  <StatCard v-else-if="props.card === 'drawdown'" label="Drawdown" :value="`${trading.drawdown.toFixed(2)}%`" :value-class="trading.drawdown > 0 ? 'text-down' : ''"
    :sub="`max ${((trading.profit.max_drawdown ?? 0) * 100).toFixed(1)}% · ${money(trading.profit.max_drawdown_abs)} ${trading.quote}`" />
  <StatCard v-else label="Expectancy / trade" :value="signed(trading.profit.expectancy)" :unit="trading.quote" :value-class="tone(trading.profit.expectancy)"
    :sub="`profit factor ${trading.profit.profit_factor ? Number(trading.profit.profit_factor).toFixed(2) : '–'}`" />
</template>
