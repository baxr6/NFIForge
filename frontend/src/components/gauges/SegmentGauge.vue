<script setup lang="ts">
import { computed, toRef } from "vue"
import ChromeBezel from "./ChromeBezel.vue"
import { bandPath, clamp, uid } from "./geometry"
import { useSpring } from "./useSpring"

// digital gauge: arc of segments that light up to the value, glowing readout in a recessed window
const props = withDefaults(defineProps<{
  value: number
  min?: number
  max?: number
  label: string
  unit?: string
  decimals?: number
  segments?: number
  palette?: "rising" | "risk"
  warn?: number | null
  danger?: number | null
  lowIsBad?: boolean
  size?: number
}>(), { min: 0, max: 100, unit: "", decimals: 1, segments: 26, palette: "rising", warn: null, danger: null, lowIsBad: false, size: 200 })

const A0 = -120
const A1 = 120
const id = uid("sg")
const shown = useSpring(toRef(props, "value"), 90, 14)
const frac = computed(() => clamp((shown.value - props.min) / (props.max - props.min), 0, 1))

// user warn/danger levels win; otherwise rising: blue -> green (more is good), risk: green -> amber -> red
function segColor(fraction: number) {
  const { warn, danger, lowIsBad, min, max } = props
  if (warn != null || danger != null) {
    const value = min + fraction * (max - min)
    const past = (lvl: number | null | undefined) => lvl != null && (lowIsBad ? value <= lvl : value >= lvl)
    return past(danger) ? "var(--red)" : past(warn) ? "var(--amber)" : "var(--green)"
  }
  if (props.palette === "risk") return fraction < 0.5 ? "var(--green)" : fraction < 0.78 ? "var(--amber)" : "var(--red)"
  return fraction < 0.62 ? "var(--brand-b)" : "var(--green)"
}

const segs = computed(() => {
  const count = props.segments
  const span = (A1 - A0) / count
  return Array.from({ length: count }, (_, i) => {
    const fromAngle = A0 + i * span + 1.1
    const toAngle = A0 + (i + 1) * span - 1.1
    const fraction = (i + 0.5) / count
    return { d: bandPath(fromAngle, toAngle, 70, 83), color: segColor(fraction), on: fraction <= frac.value + 1e-9 }
  })
})

const text = computed(() => props.value.toFixed(props.decimals))
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 200 200" class="select-none">
    <defs>
      <radialGradient :id="`${id}f`" cx="0.5" cy="0.4" r="0.65">
        <stop offset="0" stop-color="#10151b" />
        <stop offset="1" stop-color="#020304" />
      </radialGradient>
      <filter :id="`${id}g`" x="-30%" y="-30%" width="160%" height="160%">
        <feGaussianBlur stdDeviation="2" result="b" />
        <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
      </filter>
      <linearGradient :id="`${id}w`" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#000" />
        <stop offset="1" stop-color="#0b1118" />
      </linearGradient>
    </defs>

    <ChromeBezel layer="back" />
    <circle cx="100" cy="100" r="85" :fill="`url(#${id}f)`" />

    <path v-for="(segment, i) in segs" :key="i" :d="segment.d" :fill="segment.color" :opacity="segment.on ? 1 : 0.11" :filter="segment.on ? `url(#${id}g)` : undefined" />

    <text x="100" y="80" text-anchor="middle" fill="#f2f4f7" font-family="IBM Plex Sans" font-weight="600" font-size="11" letter-spacing="1.5">{{ label.toUpperCase() }}</text>
    <rect x="52" y="87" width="96" height="36" rx="5" :fill="`url(#${id}w)`" stroke="#1f2833" stroke-width="1.2" />
    <rect x="53" y="88" width="94" height="3" rx="2" fill="#000" opacity="0.6" />
    <text x="100" y="114" text-anchor="middle" fill="var(--brand-b)" font-family="IBM Plex Mono" font-weight="600" font-size="22" :filter="`url(#${id}g)`">{{ text }}</text>
    <text x="141" y="119" text-anchor="end" fill="#8695a7" font-family="IBM Plex Mono" font-size="8">{{ unit }}</text>

    <ChromeBezel layer="glass" />
  </svg>
</template>
