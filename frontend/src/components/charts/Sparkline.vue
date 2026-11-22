<script setup lang="ts">
import AreaChart from "./AreaChart.vue"

// tiny gradient line for header and slot cards
defineProps<{ data: { time: number; value: number }[]; pnl?: boolean; height?: number }>()
</script>

<template>
  <AreaChart :data="data" :mode="pnl ? 'pnl' : 'equity'" minimal :height="height ?? 44" />
</template>
