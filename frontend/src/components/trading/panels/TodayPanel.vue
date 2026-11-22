<script setup lang="ts">
import { reactive } from "vue"
import AreaChart from "@/components/charts/AreaChart.vue"
import { signed, tone } from "@/lib/format"
import { useTrading } from "@/lib/trading"

// realised + open p&l through the day
const trading = reactive(useTrading())
</script>

<template>
  <div class="panel p-3 h-full flex flex-col min-w-0">
    <div class="flex items-baseline justify-between">
      <div class="panel-title">Today's P&amp;L</div>
      <div class="num text-sm" :class="tone(trading.todayRealised + trading.openPnl)">{{ signed(trading.todayRealised + trading.openPnl) }} {{ trading.quote }}</div>
    </div>
    <div class="text-[11px] text-dim">realised {{ signed(trading.todayRealised) }} · open {{ signed(trading.openPnl) }} · day from {{ trading.utc ? "00:00 UTC" : "local midnight" }}</div>
    <div class="flex-1 min-h-[200px]">
      <AreaChart :key="`${trading.picked}-${trading.dayStart}`" :data="trading.todaySeries" mode="pnl" height="fill" />
    </div>
  </div>
</template>
