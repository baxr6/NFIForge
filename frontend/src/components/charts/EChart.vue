<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue"
import * as echarts from "echarts/core"
import { HeatmapChart, BarChart, LineChart, ScatterChart } from "echarts/charts"
import { CalendarComponent, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent } from "echarts/components"
import { CanvasRenderer } from "echarts/renderers"

echarts.use([HeatmapChart, BarChart, LineChart, ScatterChart, CalendarComponent, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent, CanvasRenderer])

// thin wrapper: pass a full echarts option, resizes with its box
const props = withDefaults(defineProps<{ option: Record<string, any>; height?: number | "fill" }>(), { height: 260 })
const el = ref<HTMLDivElement>()
let inst: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  inst = echarts.init(el.value!, undefined, { renderer: "canvas" })
  inst.setOption(props.option)
  resizeObserver = new ResizeObserver(() => inst?.resize())
  resizeObserver.observe(el.value!)
})
watch(() => props.option, (next) => inst?.setOption(next, true), { deep: true })
onBeforeUnmount(() => { resizeObserver?.disconnect(); inst?.dispose() })
</script>

<template>
  <div ref="el" class="w-full min-h-0" :style="{ height: height === 'fill' ? '100%' : `${height}px` }" />
</template>
