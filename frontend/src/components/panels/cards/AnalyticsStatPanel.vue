<script setup lang="ts">
import StatCard from "@/components/trading/StatCard.vue"
import { signed, tone } from "@/lib/format"
import { useAnalytics } from "@/lib/state/analytics"

// one Analytics summary card (follows the Analytics page's filters)
const props = defineProps<{ card: "trades" | "won" | "total" | "avg" | "pf" | "dd" | "funding" }>()
const { s, c, pctRange, hold, funding } = useAnalytics()
</script>

<template>
  <StatCard v-if="props.card === 'trades'" label="Trades" :value="String(s.n)" :sub="`${s.wins} won · ${s.n - s.wins} lost`" />
  <StatCard v-else-if="props.card === 'won'" label="Won" :value="s.n ? `${((s.wins / s.n) * 100).toFixed(1)}%` : '–'" :sub="pctRange(s.winCi) ? `95% range ${pctRange(s.winCi)}` : ''" />
  <StatCard v-else-if="props.card === 'total'" label="Total profit" :value="signed(s.total)" :value-class="tone(s.total)" :sub="`best ${signed(s.best)}`" />
  <StatCard v-else-if="props.card === 'avg'" label="Avg / trade" :value="signed(s.avg)" :value-class="tone(s.avg)" :sub="s.avgCi ? `95% range ${signed(s.avgCi[0])} to ${signed(s.avgCi[1])}` : ''" />
  <StatCard v-else-if="props.card === 'pf'" label="Profit factor" :value="s.pf == null ? (s.n ? 'no losses' : '–') : s.pf.toFixed(2)" :sub="`worst ${signed(s.worst)}`" />
  <StatCard v-else-if="props.card === 'funding'" label="Funding" :value="signed(funding.total)" :value-class="tone(funding.total)"
    :sub="`${funding.got} trades received · ${funding.paid} paid · already in profit`" />
  <StatCard v-else label="Max drawdown" :value="signed(c.maxDd)" :value-class="tone(c.maxDd)" :sub="`${c.maxDdPct ? `${c.maxDdPct.toFixed(1)}% · ` : ''}avg held ${hold(s.holdH)}`" />
</template>
