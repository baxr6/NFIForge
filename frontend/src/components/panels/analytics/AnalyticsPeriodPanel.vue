<script setup lang="ts">
import EChart from "@/components/charts/EChart.vue"
import PanelCard from "@/components/layout/PanelCard.vue"
import { useAnalytics } from "@/lib/state/analytics"

const { period, periodOption } = useAnalytics()
</script>

<template>
  <PanelCard title="Profit per">
    <template #actions>
      <div class="flex rounded-md border border-line overflow-hidden text-xs">
        <button v-for="choice in (['day', 'week', 'month'] as const)" :key="choice" class="px-2 py-0.5" :class="period === choice ? 'bg-raised text-ink' : 'text-dim hover:text-ink'" @click="period = choice">{{ choice }}</button>
      </div>
    </template>
    <EChart :option="periodOption" height="fill" />
  </PanelCard>
</template>
