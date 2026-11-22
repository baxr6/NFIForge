<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue"

// limit price box with the live exchange price under it: "use" copies it in, the limit shows its distance and
// whether it would fill straight away (buy at or above the ask, sell at or below the bid)
const props = defineProps<{ bot: string; pair: string; buying: boolean }>()
const price = defineModel<number | null>({ default: null })
const now = defineModel<number | null>("now", { default: null })
const tick = ref<{ last: number | null; bid: number | null; ask: number | null; ts: number } | null>(null)
const error = ref("")
const clock = ref(Date.now() / 1000)
let timer: ReturnType<typeof setInterval> | undefined

async function load() {
  clock.value = Date.now() / 1000
  if (!props.bot || !props.pair.includes("/")) { tick.value = null; return }
  const query = new URLSearchParams({ pair: props.pair })
  const response = await fetch(`/api/bots/${encodeURIComponent(props.bot)}/ticker?${query}`).catch(() => null)
  if (!response?.ok) { error.value = response ? (await response.json().catch(() => ({}))).detail ?? `price failed (${response.status})` : "backend not reachable"; return }
  tick.value = await response.json()
  error.value = ""
}
// every 3 s while the form is open; a new pair loads at once
watch(() => `${props.bot}|${props.pair}`, () => { tick.value = null; load() }, { immediate: true })
timer = setInterval(load, 3000)
onBeforeUnmount(() => clearInterval(timer))
watch(() => tick.value?.last ?? null, (value) => { now.value = value }, { immediate: true })

const age = computed(() => (tick.value ? Math.max(0, Math.round(clock.value - tick.value.ts)) : null))
const quote = computed(() => (props.buying ? tick.value?.ask : tick.value?.bid) ?? tick.value?.last ?? null)
const dist = computed(() => (price.value && tick.value?.last ? ((price.value - tick.value.last) / tick.value.last) * 100 : null))
const fillsNow = computed(() => !!price.value && !!quote.value && (props.buying ? price.value >= quote.value : price.value <= quote.value))
const fmt = (value: number | null | undefined) => (value == null ? "–" : +value.toPrecision(6))
</script>

<template>
  <div class="text-dim">
    <label>Price
      <div class="mt-1 flex gap-1">
        <input v-model.number="price" type="number" min="0" step="any" class="w-full rounded-md bg-raised border border-line px-2 py-1.5 text-ink num" placeholder="current price" />
        <button type="button" class="px-2 rounded-md border border-line text-xs text-dim hover:text-ink disabled:opacity-40" :disabled="!quote" :title="buying ? 'the ask' : 'the bid'" @click="price = quote">use</button>
      </div>
    </label>
    <div class="mt-1 text-xs num">
      <span v-if="error" class="text-down">{{ error }}</span>
      <template v-else-if="tick">
        <span class="text-ink">now {{ fmt(tick.last) }}</span>
        <span class="text-faint"> · bid {{ fmt(tick.bid) }} / ask {{ fmt(tick.ask) }} · {{ age }}s ago</span>
      </template>
      <span v-else class="text-faint">loading price…</span>
    </div>
    <div v-if="dist != null" class="text-xs num" :class="fillsNow ? 'text-warn' : 'text-faint'">
      limit {{ dist >= 0 ? "+" : "" }}{{ dist.toFixed(2) }}% from now{{ fillsNow ? ` · fills straight away (${buying ? "at or above the ask" : "at or below the bid"})` : "" }}
    </div>
  </div>
</template>
