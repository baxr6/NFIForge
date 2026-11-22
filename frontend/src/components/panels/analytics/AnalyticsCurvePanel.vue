<script setup lang="ts">
import { computed, ref } from "vue"
import AreaChart from "@/components/charts/AreaChart.vue"
import PanelCard from "@/components/layout/PanelCard.vue"
import { signed } from "@/lib/format"
import { useAnalytics } from "@/lib/state/analytics"

const { c, f, quote, shown, base, utc } = useAnalytics()
// drawdown in quote or as % of the account at its high (needs the bots' starting capital)
const asPct = ref(false)
const pct = computed(() => asPct.value && !!base.value)
const days = (seconds: number) => (seconds < 86400 ? `${(seconds / 3600).toFixed(0)}h` : `${(seconds / 86400).toFixed(1)}d`)
const day = (seconds: number) => new Date(seconds * 1000).toLocaleDateString("en-GB", { timeZone: utc.value ? "UTC" : undefined, day: "2-digit", month: "short", year: "2-digit" })
</script>

<template>
  <PanelCard :title="`Realised profit (${quote})`">
    <div v-if="shown.length" class="h-full flex flex-col gap-2">
      <div class="flex-[2] min-h-0"><AreaChart :key="`eq-${f.bot}-${f.side}-${f.range}`" :data="c.eq" height="fill" /></div>
      <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-dim num">
        <span>below the high</span>
        <span v-if="c.maxDd > -0.005" class="text-faint">never below its high in this range</span>
        <span v-else>deepest <span class="text-down">{{ signed(c.maxDd) }}<template v-if="base"> ({{ c.maxDdPct.toFixed(1) }}%)</template></span> on {{ day(c.deepAt) }}</span>
        <span v-if="c.maxDd <= -0.005 && c.longest">longest under water {{ days(c.longest) }} ({{ day(c.longFrom) }} → {{ c.longTo ? day(c.longTo) : "still under" }})</span>
        <span v-if="c.under" class="text-warn">now {{ signed(c.now) }}, {{ days(c.under) }} under</span>
        <div v-if="base" class="ml-auto flex rounded-md border border-line overflow-hidden">
          <button class="px-2 py-0.5" :class="!asPct ? 'bg-raised text-ink' : 'hover:text-ink'" @click="asPct = false">{{ quote || "abs" }}</button>
          <button class="px-2 py-0.5" :class="asPct ? 'bg-raised text-ink' : 'hover:text-ink'" @click="asPct = true">% of account</button>
        </div>
      </div>
      <div class="flex-1 min-h-0"><AreaChart :key="`dd-${f.bot}-${f.side}-${f.range}-${pct}`" :data="pct ? c.ddPct : c.dd" mode="pnl" height="fill" /></div>
    </div>
    <div v-else class="text-sm text-dim">no closed trades in this range</div>
  </PanelCard>
</template>
