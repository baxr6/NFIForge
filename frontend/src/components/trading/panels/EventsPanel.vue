<script setup lang="ts">
import { computed, reactive } from "vue"
import EventStream from "../EventStream.vue"
import { coinOf } from "@/lib/btcgate"
import { useTrading } from "@/lib/trading"
import { useLive } from "@/stores/live"

const trading = reactive(useTrading())
const live = useLive()
// btcgate alerts (Notifications, kind signal) join the stream for coins this bot trades or watches
const coins = computed(() => {
  const bot = trading.bot as any
  return new Set([...((bot?.whitelist?.whitelist ?? []) as string[]), ...((bot?.status ?? []) as { pair: string }[]).map((trade) => trade.pair)].map(coinOf))
})
const events = computed(() => {
  const gate = live.notes
    .filter((note) => note.kind === "signal" && coins.value.has(coinOf(note.key.split(":")[1] ?? "")))  // key = type:COIN
    .map((note) => ({ ts: note.ts, type: "btcgate", data: { status: `BTCGate ${note.title}`, note: note } }))
  return gate.length ? [...trading.events, ...gate].sort((a, b) => a.ts - b.ts) : trading.events
})
</script>

<template>
  <EventStream class="h-full" :events="events" :utc="trading.utc" :bot="trading.picked ?? ''" />
</template>
