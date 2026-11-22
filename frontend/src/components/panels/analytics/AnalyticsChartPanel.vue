<script setup lang="ts">
import EChart from "@/components/charts/EChart.vue"
import PanelCard from "@/components/layout/PanelCard.vue"
import { useAnalytics } from "@/lib/state/analytics"

// the single-chart panels: daily calendar, time held, tag x exit heatmap
const props = defineProps<{ kind: "calendar" | "hold" | "tagExit" }>()
const { calendarOption, holdOption, tagExitOption, quote } = useAnalytics()
const titles = { calendar: () => "Daily profit", hold: () => "Time held (colour = avg trade)", tagExit: () => `Entry tag × exit type (${quote.value}, cell = total)` }
const options = { calendar: calendarOption, hold: holdOption, tagExit: tagExitOption }
</script>

<template>
  <PanelCard :title="titles[props.kind]()">
    <EChart :option="options[props.kind].value" height="fill" />
  </PanelCard>
</template>
