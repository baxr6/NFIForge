<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { short } from "@/lib/orderflow"
import { useTape } from "@/lib/orderflowBook"
import { look, pair } from "@/lib/orderflowState"

// time & sales of the Order Flow pair: newest trade on top, green bought / red sold, big trades (the pair's big-trade
// size) bold. trades of one moment and side can be shown as one line (one order filling many resting orders)
const { data, error } = useTape()

const box = ref<HTMLDivElement>()
const fit = ref(30)
let resizeObserver: ResizeObserver | null = null
onMounted(() => {
  resizeObserver = new ResizeObserver(([entry]) => (fit.value = Math.max(5, Math.floor((entry.contentRect.height - 16) / 17))))
  resizeObserver.observe(box.value!)
})
onBeforeUnmount(() => resizeObserver?.disconnect())

type Line = { ms: number; price: number; qty: number; usd: number; buy: boolean; n: number }
const tape = computed(() => {
  const current = data.value
  if (!current?.trades?.length) return null
  const lines: Line[] = []
  for (const [ms, price, qty, buy] of current.trades) {
    const last = lines[lines.length - 1]
    if (look.tapeAgg && last && last.ms === ms && last.buy === !!buy) {
      last.usd += price * qty; last.qty += qty; last.price = last.usd / last.qty; last.n++
    } else lines.push({ ms, price, qty, usd: price * qty, buy: !!buy, n: 1 })
  }
  const min = look.tapeMin || 0
  const out = lines.filter((line) => line.usd >= min).reverse().slice(0, fit.value)
  const decimals = current.step ? Math.max(0, Math.ceil(-Math.log10(current.step) - 1e-9)) : 6
  return { out, decimals, big: current.big_usd ?? Infinity }
})
const time = (ms: number) => new Date(ms).toLocaleTimeString(undefined, { hour12: false })
const sel = "rounded-md bg-raised border border-line px-1.5 py-0.5 text-ink text-xs"
</script>

<template>
  <div class="flex flex-col h-full min-h-0 panel p-2 text-xs">
    <div class="flex items-center gap-2 pb-1.5">
      <span class="text-ink font-semibold">Tape</span>
      <span class="text-faint truncate">{{ pair }}</span>
      <label class="ml-auto flex items-center gap-1 text-dim" title="hide trades smaller than this (USD)">min $
        <input v-model.number="look.tapeMin" type="number" min="0" step="100" :class="sel" class="w-20" />
      </label>
      <label class="flex items-center gap-1 text-dim" title="trades at the same moment on the same side as one line"><input v-model="look.tapeAgg" type="checkbox" /> join</label>
    </div>
    <div ref="box" class="flex-1 min-h-0 overflow-hidden num">
      <template v-if="tape">
        <div class="grid grid-cols-[auto_1fr_1fr_1fr] gap-x-2 text-faint text-[10px] pb-0.5">
          <span>time</span><span class="text-right">price</span><span class="text-right">size</span><span class="text-right">$</span>
        </div>
        <div v-for="(line, index) in tape.out" :key="`${line.ms}-${index}`" class="grid grid-cols-[auto_1fr_1fr_1fr] gap-x-2 h-[17px] items-center"
          :class="[line.buy ? 'text-up' : 'text-down', line.usd >= tape.big ? 'font-semibold bg-raised' : '']">
          <span class="text-dim">{{ time(line.ms) }}</span>
          <span class="text-right">{{ line.price.toFixed(tape.decimals) }}</span>
          <span class="text-right" :title="line.n > 1 ? `${line.n} trades` : ''">{{ short(line.qty) }}<span v-if="line.n > 1" class="text-faint"> ×{{ line.n }}</span></span>
          <span class="text-right">{{ short(line.usd) }}</span>
        </div>
      </template>
      <div v-else class="h-full grid place-items-center text-dim text-center px-3">{{ error || (data?.pending ? "starting the trade stream…" : "waiting for trades…") }}</div>
    </div>
  </div>
</template>
