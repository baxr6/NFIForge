<script setup lang="ts">
import { computed } from "vue"
import AnalogGauge from "./AnalogGauge.vue"
import SegmentGauge from "./SegmentGauge.vue"
import { gaugeById } from "@/lib/gauges"
import { useSettings } from "@/stores/settings"

// any gauge by id: looks up its definition and the user's on/off + thresholds; renders nothing when switched off
const props = withDefaults(defineProps<{ id: string; value: number; size?: number }>(), { size: 200 })
const settings = useSettings()
const def = computed(() => gaugeById[props.id])
const cfg = computed(() => settings.gauge(props.id))
const style = computed(() => cfg.value.style ?? def.value?.style)
const palette = computed(() => def.value?.palette ?? (cfg.value.warn != null && !def.value?.lowIsBad ? "risk" : "rising"))
</script>

<template>
  <template v-if="def && cfg.enabled">
    <AnalogGauge v-if="style === 'analog'" :value="value" :min="def.min" :max="def.max" :label="def.label" :unit="def.unit"
      :decimals="def.decimals" :majors="def.majors ?? 6" :warn="cfg.warn" :danger="cfg.danger" :low-is-bad="def.lowIsBad" :size="size" />
    <SegmentGauge v-else :value="value" :min="def.min" :max="def.max" :label="def.label" :unit="def.unit"
      :decimals="def.decimals" :palette="palette" :warn="cfg.warn" :danger="cfg.danger" :low-is-bad="def.lowIsBad" :size="size" />
  </template>
</template>
