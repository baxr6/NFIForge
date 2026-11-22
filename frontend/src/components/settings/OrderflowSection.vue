<script setup lang="ts">
import { onMounted, ref, watch } from "vue"
import { useSettings } from "@/stores/settings"

// the order flow recorder's options: config.yaml's, with the changes made here over them (saved with the other
// settings; the recorder picks them up within 30 s). switching order flow on / off stays in config.yaml
const settings = useSettings()
const running = ref<Record<string, number | boolean> | null>(null)  // what the recorder runs with now
const defaults = ref<Record<string, number | boolean>>({})  // config.yaml's, what reset goes back to

async function load() {
  const response = await fetch("/api/orderflow/status").catch(() => null)
  if (!response?.ok) return
  const status = await response.json()
  running.value = { ...status.settings, memory_mb: status.memory_mb }
  defaults.value = status.defaults ?? {}
}
onMounted(load)
watch(() => settings.savedAt, load)

const NUMBERS: { k: string; label: string; hint: string; min: number; max?: number; step: number }[] = [
  { k: "max_pairs", label: "Pairs recorded at once", hint: "the chart's pair first, then open trades", min: 1, max: 50, step: 1 },
  { k: "history_days", label: "Trade history to fill (days)", hint: "from the exchanges' archives and api", min: 0, max: 60, step: 1 },
  { k: "retention_days", label: "Keep trades (days)", hint: "footprint, open interest, funding, liquidations", min: 1, max: 365, step: 1 },
  { k: "book_history_days", label: "Order book history to fill (days)", hint: "bybit / gate archives, binance depth bands: large downloads", min: 0, max: 14, step: 1 },
  { k: "book_retention_days", label: "Keep the order book (days)", hint: "about 5-10 MB per pair per day", min: 1, max: 90, step: 1 },
  { k: "big_pct", label: "Big trade: top % of trades", hint: "by value, over the pair's last ~20,000 trades, updated every 10 min", min: 0.1, max: 10, step: 0.1 },
  { k: "big_usd", label: "Big trade: fixed size (USD)", hint: "0 = use the top % above", min: 0, step: 100 },
  { k: "memory_mb", label: "Memory limit (MB)", hint: "the recorder restarts when it uses more", min: 256, step: 128 },
]
const SWITCHES: { k: string; label: string; hint: string }[] = [
  { k: "watch_open_trades", label: "Record open-trade pairs", hint: "every bot's open trades, besides the pair on screen" },
  { k: "book", label: "Record the order book", hint: "heatmap, DOM, depth, large orders; for pairs started after the change" },
]

const value = (key: string) => settings.s?.orderflow?.[key] ?? running.value?.[key]
// a value set back to the default is dropped, so only real changes are kept
function set(key: string, value: number | boolean) {
  if (typeof value === "number" && !Number.isFinite(value)) return
  const { [key]: _, ...rest } = settings.s!.orderflow ?? {}
  settings.s!.orderflow = value === defaults.value[key] ? rest : { ...rest, [key]: value }
}
const changed = (key: string) => key in defaults.value && value(key) !== defaults.value[key]
const anyChanged = () => [...NUMBERS, ...SWITCHES].some((field) => changed(field.k))
const reset = (key: string) => set(key, defaults.value[key])
</script>

<template>
  <section class="panel p-4">
    <div class="flex items-center gap-3">
      <div class="panel-title">Order Flow</div>
      <button v-if="anyChanged()" class="ml-auto text-xs rounded-md border border-line px-2 py-1 text-dim hover:text-ink" @click="settings.s!.orderflow = {}">Reset to defaults</button>
    </div>
    <p class="text-xs text-dim mt-1 mb-3">the recorder behind the Order Flow page; changes reach it within 30 s. Switching it on or off stays in
      config.yaml (orderflow: enabled), with a restart</p>
    <div v-if="running" class="grid gap-4 sm:grid-cols-2">
      <label v-for="field in NUMBERS" :key="field.k" class="text-sm text-dim">{{ field.label }}
        <input type="number" :min="field.min" :max="field.max" :step="field.step" :value="value(field.k)"
          class="mt-1 w-full rounded-md bg-raised border border-line px-2 py-1.5 num text-ink"
          @change="set(field.k, Number(($event.target as HTMLInputElement).value))" />
        <span class="block text-xs text-faint mt-1">{{ field.hint }}<template v-if="changed(field.k)"> · default {{ defaults[field.k] }}
          <button class="text-dim hover:text-ink underline" @click.prevent="reset(field.k)">reset</button></template></span>
      </label>
    </div>
    <div v-if="running" class="mt-4 space-y-3">
      <div v-for="field in SWITCHES" :key="field.k" class="flex items-center gap-3">
        <button role="switch" :aria-checked="!!value(field.k)" class="toggle" :class="{ on: !!value(field.k) }" @click="set(field.k, !value(field.k))"><span /></button>
        <div class="text-sm">{{ field.label }} <span class="text-xs text-dim">{{ field.hint }}</span>
          <template v-if="changed(field.k)"><span class="text-xs text-faint ml-1">· default {{ defaults[field.k] ? "on" : "off" }}</span>
            <button class="text-xs text-dim hover:text-ink underline ml-1" @click="reset(field.k)">reset</button></template></div>
      </div>
    </div>
    <div v-else class="text-sm text-dim">loading…</div>
  </section>
</template>
