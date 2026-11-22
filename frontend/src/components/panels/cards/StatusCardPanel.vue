<script setup lang="ts">
import { computed, reactive, ref } from "vue"
import BotControl from "@/components/trades/BotControl.vue"
import Drawer from "@/components/trades/Drawer.vue"
import StatusCard from "@/components/trading/StatusCard.vue"
import { age } from "@/lib/format"
import { useTradeAccess } from "@/lib/tradeActions"
import { useTrading } from "@/lib/trading"

// one status card as its own panel: bot, exchange, data, server or risk
const props = defineProps<{ card: "bot" | "exchange" | "data" | "server" | "risk" }>()
const trading = reactive(useTrading())
// bot card: a small control button when bot control is allowed for this bot
const { canTrade } = useTradeAccess(computed(() => trading.bot?.name))
const controlling = ref(false)
</script>

<template>
  <div v-if="props.card === 'bot'" class="h-full relative">
    <StatusCard class="h-full" title="Bot" :value="trading.botCard.value" :detail="trading.botCard.detail" :sub="trading.botCard.sub" :level="trading.botCard.level" />
    <button v-if="canTrade" class="absolute top-2 right-2 text-[11px] px-2 py-0.5 rounded border border-line text-dim hover:text-ink bg-raised" @click="controlling = true">control</button>
    <Drawer v-if="controlling && trading.bot" @close="controlling = false">
      <div class="text-lg font-semibold mb-3">Bot control · {{ trading.bot.name }}</div>
      <BotControl :bot="trading.bot.name" />
    </Drawer>
  </div>
  <StatusCard v-else-if="props.card === 'exchange'" class="h-full" title="Exchange" :value="trading.bot?.latency_ms != null ? `API ${Math.round(trading.bot.latency_ms)} ms` : '–'" detail="round trip to the bot" :level="trading.apiLevel" />
  <StatusCard v-else-if="props.card === 'data'" class="h-full" title="Data" :value="trading.lastCandle ? `Fresh · ${age(trading.lastCandle, trading.now)} ago` : 'Waiting for candle'"
    :detail="`${trading.bot?.whitelist?.whitelist?.length ?? 0} pairs · last candle`" :level="trading.lastCandle && trading.now - trading.lastCandle > 900 ? 'warn' : 'ok'" />
  <StatusCard v-else-if="props.card === 'server'" class="h-full" title="Server" :value="trading.host.cpu != null ? `CPU ${trading.host.cpu.toFixed(0)}% · RAM ${trading.host.ram.toFixed(0)}%` : '–'"
    :detail="trading.host.disk != null ? `disk ${trading.host.disk.toFixed(0)}% · load ${trading.host.load.toFixed(2)}/core` : ''" :level="trading.serverLevel" />
  <StatusCard v-else class="h-full" title="Risk" :value="trading.riskLevel === 'ok' ? 'Safe' : trading.riskLevel === 'warn' ? 'Watch' : 'At risk'"
    :detail="`DD ${trading.drawdown.toFixed(1)}% · ${trading.liqNearest ? `liq ${trading.liqNearest.dist.toFixed(1)}% ${trading.liqNearest.pair}` : 'no liq'} · ${trading.open.length}/${trading.maxSlots}`" :level="trading.riskLevel" />
</template>
