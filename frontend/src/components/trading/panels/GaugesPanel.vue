<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue"
import Gauge from "@/components/gauges/Gauge.vue"
import { gaugeById } from "@/lib/gauges"
import { useTrading } from "@/lib/trading"
import { useAuth } from "@/stores/auth"
import { useSettings } from "@/stores/settings"

// gauge cluster; each gauge follows its on/off switch in settings and all of them are sized to fit the box
const trading = reactive(useTrading())
const settings = useSettings()

const values = computed<Record<string, number>>(() => ({
  cpu: trading.host.cpu ?? 0,
  ram: trading.host.ram ?? 0,
  load: trading.host.load ?? 0,
  disk: trading.host.disk ?? 0,
  swap: trading.host.swap ?? 0,
  temp: trading.host.temp ?? 0,
  exchange_ms: trading.bot?.latency_ms ?? 0,
  loop_s: trading.bot?.loop_s ?? 0,
  btc_rsi: trading.pulse?.rsi_4h ?? 50,
  stake_used: trading.stakeUsed,
  slots_used: trading.slotsUsed,
  drawdown: trading.drawdown,
  liq_distance: trading.liqNearest?.dist ?? 60,
}))
// host dials only for who may see the Server page
const auth = useAuth()
const shown = computed(() => Object.keys(values.value).filter((id) => settings.gauge(id).enabled && (gaugeById[id]?.group !== "server" || auth.can("server"))))

// biggest square that fits n gauges in w x h with a gap between them
const box = ref<HTMLDivElement>()
const width = ref(0), height = ref(0)
const GAP = 12, MIN = 84, MAX = 230
const size = computed(() => {
  const count = shown.value.length
  if (!count || !width.value || !height.value) return 150
  let best = MIN
  for (let rows = 1; rows <= count; rows++) {
    const cols = Math.ceil(count / rows)
    const side = Math.min((width.value - GAP * (cols - 1)) / cols, (height.value - GAP * (rows - 1)) / rows)
    best = Math.max(best, Math.floor(side))
  }
  return Math.min(MAX, best)
})

let resizeObserver: ResizeObserver | null = null
onMounted(() => {
  resizeObserver = new ResizeObserver(([entry]) => { width.value = entry.contentRect.width; height.value = entry.contentRect.height })
  resizeObserver.observe(box.value!)
})
onBeforeUnmount(() => resizeObserver?.disconnect())
</script>

<template>
  <div class="panel carbon p-3 h-full min-h-[180px] lg:min-h-0">
    <div ref="box" class="h-full flex flex-wrap justify-center content-center" :style="{ gap: `${GAP}px` }">
      <Gauge v-for="id in shown" :key="id" :id="id" :value="values[id]" :size="size" />
    </div>
  </div>
</template>
