<script setup lang="ts">
import PanelCard from "@/components/layout/PanelCard.vue"
import { usePairs } from "@/lib/state/pairs"

const { data, base, when } = usePairs()
</script>

<template>
  <PanelCard title="Whitelist changes">
    <div v-for="change in data?.changes ?? []" :key="change.ts + change.pair + change.change" class="text-sm py-1 border-b border-line last:border-0">
      <span class="inline-flex gap-2 items-baseline">
        <span :class="change.change === 'added' ? 'text-up' : 'text-down'">{{ change.change === "added" ? "+ added" : "− removed" }}</span>
        <span class="font-semibold num">{{ base(change.pair) }}</span>
        <span class="text-faint num text-xs">{{ when(change.ts) }}</span>
      </span>
      <div v-if="change.reason" class="text-xs text-faint">{{ change.reason }}</div>
    </div>
    <div v-if="!data?.changes.length" class="text-sm text-faint">no changes since NFIForge started</div>
  </PanelCard>
</template>
