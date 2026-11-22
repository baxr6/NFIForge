<script setup lang="ts">
import { RouterLink } from "vue-router"
import PanelCard from "@/components/layout/PanelCard.vue"
import { age, signed, tone } from "@/lib/format"
import { usePairs } from "@/lib/state/pairs"

const { data, wl, bot, base } = usePairs()
</script>

<template>
  <PanelCard title="Whitelist" :pad="false">
    <template #actions><span class="text-xs text-faint truncate">{{ data?.method.join(" → ") }}</span></template>
    <table class="w-full text-sm num">
      <thead class="text-xs text-dim text-left border-b border-line sticky top-0 bg-panel">
        <tr><th class="px-4 py-2 font-normal">pair</th><th class="px-3 py-2 font-normal">now</th><th class="px-3 py-2 font-normal text-right">past trades</th><th class="px-3 py-2 font-normal text-right">P&amp;L</th><th class="px-4 py-2 font-normal text-right">last</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in wl" :key="row.pair" class="border-b border-line last:border-0 hover:bg-hover">
          <td class="px-4 py-1.5"><RouterLink :to="{ path: '/chart', query: { bot: bot?.name, pair: row.pair } }" class="font-semibold hover:text-brand-b">{{ base(row.pair) }}</RouterLink></td>
          <td class="px-3 py-1.5">
            <span v-if="row.open" :class="tone(row.open.profit_ratio)">{{ row.open.is_short ? "▼" : "▲" }} {{ signed((row.open.profit_ratio ?? 0) * 100, 1) }}%</span>
            <span v-if="row.lock" class="text-warn ml-2" :title="row.lock.reason">locked</span>
          </td>
          <td class="px-3 py-1.5 text-right text-dim">{{ row.past?.n ?? "" }}</td>
          <td class="px-3 py-1.5 text-right" :class="tone(row.past?.total)">{{ row.past ? signed(row.past.total) : "" }}</td>
          <td class="px-4 py-1.5 text-right text-faint">{{ row.past ? `${age(row.past.last / 1000)} ago` : "" }}</td>
        </tr>
        <tr v-if="!wl.length"><td colspan="5" class="px-4 py-6 text-center text-dim">{{ data ? "whitelist is empty" : "loading…" }}</td></tr>
      </tbody>
    </table>
  </PanelCard>
</template>
