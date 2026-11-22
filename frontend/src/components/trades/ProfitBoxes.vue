<script setup lang="ts">
import { computed } from "vue"
import { money } from "@/lib/format"
import { currentProfit, totalProfit } from "@/lib/profit"

// total and current profit of an open trade, boxed green / red with an arrow
const props = defineProps<{ trade: Record<string, any>; compact?: boolean }>()
const rows = computed(() => [
  { label: "Total profit", ...totalProfit(props.trade) },
  { label: "Current profit", ...currentProfit(props.trade) },
])
</script>

<template>
  <div class="grid gap-1.5" :class="compact ? 'grid-cols-2' : 'grid-cols-1 sm:grid-cols-2'">
    <div v-for="row in rows" :key="row.label" class="rounded-md border px-2 py-1 num min-w-0"
      :class="row.abs < 0 ? 'border-[var(--red)] bg-[var(--red-dim)]' : 'border-[var(--green)] bg-[var(--green-dim)]'">
      <div class="text-[10px] text-dim font-sans">{{ row.label }}</div>
      <!-- compact (slot cards): the amount goes under the % so narrow cards don't cut it off -->
      <div class="flex items-baseline gap-x-1.5 whitespace-nowrap" :class="compact ? 'flex-wrap text-sm' : 'text-base'">
        <span :class="row.abs < 0 ? 'text-down' : 'text-up'">{{ row.abs < 0 ? "▼" : "▲" }}</span>
        <span class="font-semibold">{{ row.pct.toFixed(2) }}%</span>
        <span class="text-dim text-xs" :class="{ 'basis-full': compact }">{{ compact ? "" : "(" }}{{ money(row.abs) }}{{ compact ? ` ${trade.quote_currency ?? ""}` : ")" }}</span>
      </div>
    </div>
  </div>
</template>
