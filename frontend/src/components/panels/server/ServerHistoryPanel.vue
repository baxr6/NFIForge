<script setup lang="ts">
import { computed } from "vue"
import AreaChart from "@/components/charts/AreaChart.vue"
import EChart from "@/components/charts/EChart.vue"
import PanelCard from "@/components/layout/PanelCard.vue"
import { RANGES, useServer } from "@/lib/state/server"

// one history chart: cpu, ram or disk %, memory per container, or every bot's loop time
const props = defineProps<{ kind: "cpu" | "ram" | "disk" | "containers" | "loops" }>()
const server = useServer()
const TITLES = { cpu: "CPU %", ram: "RAM %", disk: "Disk %", containers: "Container memory", loops: "Bot loop time (s)" }
const rangeLabel = computed(() => RANGES.find(([, hours]) => hours === server.range.value)?.[0] ?? "")
</script>

<template>
  <PanelCard :title="`${TITLES[props.kind]} · ${rangeLabel}`">
    <div v-if="!server.enough.value" class="text-xs text-faint">one point a minute; fills in as NFIForge runs</div>
    <EChart v-else-if="props.kind === 'containers'" :option="server.memOption.value" height="fill" />
    <div v-else-if="props.kind === 'loops'" class="h-full flex flex-col gap-2">
      <div v-for="bot in server.loopBots.value" :key="bot" class="flex-1 min-h-0 flex flex-col">
        <div class="text-xs text-dim">{{ bot }}</div>
        <div class="flex-1 min-h-0"><AreaChart :key="`loop${bot}${server.range.value}`" :data="server.loopSeries(bot)" height="fill" /></div>
      </div>
    </div>
    <AreaChart v-else :key="`${props.kind}${server.range.value}`" :data="server.series(props.kind)" height="fill" />
  </PanelCard>
</template>
