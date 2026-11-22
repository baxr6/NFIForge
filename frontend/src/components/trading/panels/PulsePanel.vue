<script setup lang="ts">
import { reactive } from "vue"
import CandleChart from "@/components/charts/CandleChart.vue"
import { money, pct, tone } from "@/lib/format"
import { useTrading } from "@/lib/trading"

// btc from the bot's own candles
const trading = reactive(useTrading())
</script>

<template>
  <div class="panel p-3 h-full flex flex-col min-w-0">
    <div class="flex items-baseline justify-between">
      <div class="panel-title">Market pulse</div>
      <div class="text-[11px] text-dim">{{ trading.pulse?.pair ?? "loading BTC" }}</div>
    </div>
    <div v-if="trading.pulse" class="grid grid-cols-4 gap-2 text-center my-2">
      <div v-for="timeframe in ['15m', '1h', '4h', '1d']" :key="timeframe" class="rounded-md bg-raised py-1">
        <div class="text-[10px] text-faint">{{ timeframe }}</div>
        <div class="num text-sm" :class="tone(trading.pulse.change[timeframe])">{{ pct(trading.pulse.change[timeframe]) }}</div>
      </div>
    </div>
    <div class="flex-1 min-h-[180px]">
      <CandleChart v-if="trading.btcCandles.length" :key="trading.picked ?? ''" :candles="trading.btcCandles" height="fill"
        :title="`BTC ${money(trading.btcCandles[trading.btcCandles.length - 1].close, 0)} · RSI 4h ${trading.pulse?.rsi_4h?.toFixed(1) ?? '–'}`" />
      <div v-else class="h-full grid place-items-center text-xs text-faint">waiting for btc candles</div>
    </div>
  </div>
</template>
