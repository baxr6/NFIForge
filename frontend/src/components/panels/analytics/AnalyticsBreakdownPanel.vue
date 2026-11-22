<script setup lang="ts">
import DownloadButton from "@/components/DownloadButton.vue"
import PanelCard from "@/components/layout/PanelCard.vue"
import { signed, tone } from "@/lib/format"
import { useAnalytics } from "@/lib/state/analytics"
import { breakdownSheet } from "@/lib/tradeSheets"

const { GROUPS, by, cols, sortBy, sortKey, desc, table, pctRange, hold, shown, utc } = useAnalytics()
// csv: the table picked; excel: that one first, then every other breakdown
const sheets = () => [...GROUPS].sort(([left], [right]) => Number(right === by.value) - Number(left === by.value)).map(([key, label]) => breakdownSheet(shown.value, key, label, utc.value))
</script>

<template>
  <PanelCard :pad="false">
    <template #actions>
      <span class="panel-title">By</span>
      <select v-model="by" class="rounded-md bg-raised border border-line px-2 py-1 text-ink text-sm"><option v-for="[key, label] in GROUPS" :key="key" :value="key">{{ label }}</option></select>
      <span class="text-xs text-faint">ranges are 95 %; few trades = wide range</span>
      <DownloadButton name="analytics" :sheets="sheets" :disabled="!table.length" />
    </template>
    <table class="w-full text-sm num whitespace-nowrap">
      <thead class="text-xs text-dim text-left border-b border-line sticky top-0 bg-panel">
        <tr><th v-for="[key, label] in cols" :key="key" class="px-3 py-2 font-normal cursor-pointer select-none hover:text-ink" :class="key !== 'key' && 'text-right'" @click="sortBy(key)">
          {{ key === "key" ? GROUPS.find(([group]) => group === by)![1] : label }}<span v-if="sortKey === key" class="text-brand-b">{{ desc ? " ↓" : " ↑" }}</span></th></tr>
      </thead>
      <tbody>
        <tr v-for="row in table" :key="row.key" class="border-b border-line last:border-0 hover:bg-hover">
          <td class="px-3 py-1.5 font-semibold">{{ row.key }}</td>
          <td class="px-3 py-1.5 text-right">{{ row.n }}</td>
          <td class="px-3 py-1.5 text-right">{{ (row.win * 100).toFixed(0) }}% <span class="text-faint text-xs">{{ pctRange(row.winCi) }}</span></td>
          <td class="px-3 py-1.5 text-right" :class="tone(row.total)">{{ signed(row.total) }}</td>
          <td class="px-3 py-1.5 text-right"><span :class="tone(row.avg)">{{ signed(row.avg) }}</span>
            <div v-if="row.avgCi" class="text-faint text-xs">{{ signed(row.avgCi[0]) }} to {{ signed(row.avgCi[1]) }}</div></td>
          <td class="px-3 py-1.5 text-right">{{ row.pf == null ? "–" : row.pf.toFixed(2) }}</td>
          <td class="px-3 py-1.5 text-right" :class="tone(row.worst)">{{ signed(row.worst) }}</td>
          <td class="px-3 py-1.5 text-right text-dim">{{ hold(row.holdH) }}</td>
        </tr>
      </tbody>
    </table>
  </PanelCard>
</template>
