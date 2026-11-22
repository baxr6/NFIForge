<script setup lang="ts">
import StatCard from "@/components/trading/StatCard.vue"
import { signed, tone } from "@/lib/format"
import { useHistoryPage } from "@/lib/state/history"

// one Trade History summary card (follows the Trade History page's filters)
const props = defineProps<{ card: "trades" | "won" | "total" | "avg" | "losses" | "worst" }>()
const { sum } = useHistoryPage()
</script>

<template>
  <StatCard v-if="props.card === 'trades'" label="Closed trades" :value="String(sum.n)" />
  <StatCard v-else-if="props.card === 'won'" label="Won" :value="`${sum.win.toFixed(1)}%`" />
  <StatCard v-else-if="props.card === 'total'" label="Total" :value="signed(sum.total)" :value-class="tone(sum.total)" />
  <StatCard v-else-if="props.card === 'avg'" label="Avg / trade" :value="signed(sum.avg)" :value-class="tone(sum.avg)" />
  <StatCard v-else-if="props.card === 'losses'" label="All losses" :value="signed(sum.loss)" :value-class="tone(sum.loss)" />
  <StatCard v-else label="Worst trade" :value="signed(sum.worst)" :value-class="tone(sum.worst)" />
</template>
