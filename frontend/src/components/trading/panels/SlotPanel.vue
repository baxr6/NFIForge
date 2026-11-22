<script setup lang="ts">
import { computed, reactive, ref } from "vue"
import SlotCard from "../SlotCard.vue"
import Drawer from "@/components/trades/Drawer.vue"
import TradeInspector from "@/components/trades/TradeInspector.vue"
import { useTrading, walletOf } from "@/lib/trading"

// one slot as its own panel, so each can be placed anywhere; open trades fill the slots in order. a click opens the trade in full
const props = defineProps<{ index: number }>()
const trading = reactive(useTrading())
const trade = computed(() => trading.open[props.index])
const pickedId = ref<number | null>(null)
// keep the open drawer on live data, by trade id since slots reorder as trades close
const picked = computed(() => (pickedId.value === null ? null : trading.open.find((trade: any) => trade.trade_id === pickedId.value) ?? null))
</script>

<template>
  <SlotCard class="h-full" :class="trade ? 'cursor-pointer hover:bg-raised' : ''" :index="props.index" :trade="trade"
    :prices="trade ? trading.bot?.pair_prices?.[trade.pair] : undefined" :is-nfi="trading.bot?.is_nfi" :loop-age="trading.loopAgo"
    @click="trade && (pickedId = trade.trade_id)" />
  <Drawer v-if="picked && trading.picked" @close="pickedId = null">
    <TradeInspector :trade="picked" :bot="trading.picked" :is-nfi="trading.bot?.is_nfi"
      :custom-data="trading.bot?.custom_data" :history="trading.bot?.trades?.trades" :wallet="walletOf(trading.bot?.balance)" />
  </Drawer>
</template>
