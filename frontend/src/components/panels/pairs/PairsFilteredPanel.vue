<script setup lang="ts">
import PanelCard from "@/components/layout/PanelCard.vue"
import { age } from "@/lib/format"
import { usePairs } from "@/lib/state/pairs"

const { data, base, logWarning } = usePairs()
</script>

<template>
  <PanelCard title="Filtered out">
    <div class="text-xs text-faint mb-2">latest reason a filter gave for dropping each pair, from the bot's log since NFIForge started
      <span v-if="logWarning" class="text-warn">· the bot logs at debug level, so many of these lines are missed</span></div>
    <table class="w-full text-sm">
      <tbody>
        <tr v-for="record in data?.filtered ?? []" :key="record.pair" class="border-b border-line last:border-0">
          <td class="py-1 pr-3 font-semibold num whitespace-nowrap">{{ base(record.pair) }}</td>
          <td class="py-1 pr-3 text-dim whitespace-nowrap">{{ record.filter }}</td>
          <td class="py-1 pr-3 text-dim">{{ record.reason }}</td>
          <td class="py-1 text-faint num whitespace-nowrap text-right">{{ age(record.ts) }} ago</td>
        </tr>
      </tbody>
    </table>
    <div v-if="!data?.filtered.length" class="text-sm text-faint">nothing logged yet</div>
  </PanelCard>
</template>
