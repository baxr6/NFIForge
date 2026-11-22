<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { short } from "@/lib/orderflow"
import { useBookNow } from "@/lib/orderflowBook"
import { look, pair } from "@/lib/orderflowState"

// dom ladder of the Order Flow pair: resting bids / asks per price (grouped), what traded there today, the mid in the
// middle; large orders (wall size) in amber; the row of the latest trade flashes. display only: trading stays on the
// Positions page
const { data, error } = useBookNow()
const flash = ref<{ price: number; buy: boolean } | null>(null)
let flashTimer = 0
watch(() => data.value?.last?.[0], (ts, before) => {
  const last = data.value?.last
  if (!last || ts == null || ts === before) return
  flash.value = { price: last[1], buy: !!last[3] }
  clearTimeout(flashTimer)
  flashTimer = window.setTimeout(() => (flash.value = null), 600)
})
onBeforeUnmount(() => clearTimeout(flashTimer))
const GROUPS = [1, 2, 5, 10, 20, 50]

const box = ref<HTMLDivElement>()
const fit = ref(40)
let resizeObserver: ResizeObserver | null = null
onMounted(() => {
  resizeObserver = new ResizeObserver(([entry]) => (fit.value = Math.max(10, Math.floor((entry.contentRect.height - 24) / 18))))
  resizeObserver.observe(box.value!)
})
onBeforeUnmount(() => resizeObserver?.disconnect())

type Row = { i: number; price: number; bid: number; ask: number; bought: number; sold: number; wall: boolean; mid: boolean }
const ladder = computed(() => {
  const current = data.value
  const book = current?.book
  if (!current || !book || !book.bids.length || !book.asks.length) return null
  const size = (current.step ?? book.step) * look.domGroup
  const rows = new Map<number, Row>()
  const row = (index: number) => {
    let level = rows.get(index)
    if (!level) rows.set(index, (level = { i: index, price: index * size, bid: 0, ask: 0, bought: 0, sold: 0, wall: false, mid: false }))
    return level
  }
  for (const [price, amount] of book.bids) { const level = row(Math.floor(price / size + 1e-9)); level.bid += amount; level.wall ||= price * amount >= book.wall_usd }
  for (const [price, amount] of book.asks) { const level = row(Math.floor(price / size + 1e-9)); level.ask += amount; level.wall ||= price * amount >= book.wall_usd }
  for (const [index, bought, sold] of current.traded ?? []) {
    const level = rows.get(Math.floor(index / look.domGroup))
    if (level) { level.bought += bought; level.sold += sold }
  }
  const mid = (book.bids[0][0] + book.asks[0][0]) / 2
  const center = Math.floor(mid / size)
  const half = Math.floor(fit.value / 2)
  const out: Row[] = []
  for (let i = center + half; i > center - half; i--) out.push(rows.get(i) ?? { i, price: i * size, bid: 0, ask: 0, bought: 0, sold: 0, wall: false, mid: false })
  for (const level of out) level.mid = level.i === center
  if (look.domCum) {
    // asks add up from the best ask upwards, bids from the best bid downwards
    let run = 0
    for (let index = out.length - 1; index >= 0; index--) { run += out[index].ask; if (out[index].ask || run) out[index].ask = run }
    run = 0
    for (const level of out) { run += level.bid; if (level.bid || run) level.bid = run }
  }
  const maxSize = Math.max(1e-12, ...out.map((level) => Math.max(level.bid, level.ask)))
  const maxTraded = Math.max(1e-12, ...out.map((level) => level.bought + level.sold))
  const decimals = Math.max(0, Math.ceil(-Math.log10(size) - 1e-9))
  return { out, size, maxSize, maxTraded, decimals, mid, stale: current.stale, levels: `${book.bids.length}/${book.asks.length}` }
})
const sel = "rounded-md bg-raised border border-line px-1.5 py-0.5 text-ink text-xs"
</script>

<template>
  <div class="flex flex-col h-full min-h-0 panel p-2 text-xs">
    <div class="flex items-center gap-2 pb-1.5">
      <span class="text-ink font-semibold">DOM</span>
      <span class="text-faint truncate">{{ pair }}</span>
      <label class="ml-auto flex items-center gap-1 text-dim">rows
        <select v-model.number="look.domGroup" :class="sel"><option v-for="group in GROUPS" :key="group" :value="group">{{ group }}×</option></select>
      </label>
      <label class="flex items-center gap-1 text-dim" title="sizes added up from the best price outwards"><input v-model="look.domCum" type="checkbox" /> cum</label>
    </div>
    <div ref="box" class="flex-1 min-h-0 overflow-hidden num">
      <template v-if="ladder">
        <div class="grid grid-cols-[1fr_1fr_auto_1fr] gap-x-1 text-faint text-[10px] pb-0.5">
          <span title="traded here today (UTC): sold / bought">traded</span><span class="text-right">bid</span><span class="text-center px-1">price</span><span>ask</span>
        </div>
        <div v-for="level in ladder.out" :key="level.i" class="grid grid-cols-[1fr_1fr_auto_1fr] gap-x-1 h-[18px] items-center transition-colors duration-300"
          :class="[level.mid ? 'border-y border-line-bright' : '', flash && Math.floor(flash.price / ladder.size + 1e-9) === level.i ? (flash.buy ? 'bg-[var(--green-dim)]' : 'bg-[var(--red-dim)]') : '']">
          <div class="relative h-full flex items-center">
            <div class="absolute left-0 top-[3px] bottom-[3px] flex" :style="{ width: `${((level.bought + level.sold) / ladder.maxTraded) * 100}%` }">
              <div class="h-full bg-[var(--red)] opacity-40" :style="{ width: `${(level.sold / (level.bought + level.sold || 1)) * 100}%` }" />
              <div class="h-full bg-[var(--green)] opacity-40 flex-1" />
            </div>
          </div>
          <div class="relative h-full flex items-center justify-end pr-1">
            <div class="absolute right-0 top-[2px] bottom-[2px] bg-[var(--green)] opacity-25" :style="{ width: `${(level.bid / ladder.maxSize) * 100}%` }" />
            <span v-if="level.bid" class="relative" :class="level.wall && level.bid ? 'text-warn font-semibold' : 'text-up'">{{ short(level.bid) }}</span>
          </div>
          <span class="text-center px-1" :class="level.mid ? 'text-ink font-semibold' : 'text-dim'">{{ level.price.toFixed(ladder.decimals) }}</span>
          <div class="relative h-full flex items-center pl-1">
            <div class="absolute left-0 top-[2px] bottom-[2px] bg-[var(--red)] opacity-25" :style="{ width: `${(level.ask / ladder.maxSize) * 100}%` }" />
            <span v-if="level.ask" class="relative" :class="level.wall && level.ask ? 'text-warn font-semibold' : 'text-down'">{{ short(level.ask) }}</span>
          </div>
        </div>
      </template>
      <div v-else class="h-full grid place-items-center text-dim text-center px-3">{{ error || (data?.pending ? "starting the book stream…" : "waiting for the book…") }}</div>
    </div>
    <div v-if="ladder" class="pt-1 text-faint text-[10px]">{{ ladder.levels }} levels from the exchange<span v-if="ladder.stale" class="text-warn"> · not updating</span></div>
  </div>
</template>
