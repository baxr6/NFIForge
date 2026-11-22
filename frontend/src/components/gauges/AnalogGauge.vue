<script setup lang="ts">
import { computed, toRef } from "vue"
import ChromeBezel from "./ChromeBezel.vue"
import { arcPath, bandPath, clamp, pt, uid } from "./geometry"
import { useSpring } from "./useSpring"

// needle gauge: black face, chrome bezel, brand-blue accent ring, warning/danger zones, red needle
const props = withDefaults(defineProps<{
  value: number
  min?: number
  max?: number
  label: string
  unit?: string
  majors?: number
  minors?: number
  decimals?: number
  warn?: number | null
  danger?: number | null
  lowIsBad?: boolean
  size?: number
}>(), { min: 0, max: 100, unit: "", majors: 6, minors: 4, decimals: 0, warn: null, danger: null, lowIsBad: false, size: 200 })

const A0 = -135
const A1 = 135
const id = uid("ag")
const shown = useSpring(toRef(props, "value"))
const ang = (value: number) => A0 + ((clamp(value, props.min, props.max) - props.min) / (props.max - props.min)) * (A1 - A0)

const ticks = computed(() => {
  const out: { major: boolean; a: number; label?: string }[] = []
  const steps = (props.majors - 1) * (props.minors + 1)
  for (let i = 0; i <= steps; i++) {
    const value = props.min + ((props.max - props.min) * i) / steps
    const major = i % (props.minors + 1) === 0
    out.push({ major, a: ang(value), label: major ? fmtTick(value) : undefined })
  }
  return out
})

function fmtTick(value: number) {
  const span = props.max - props.min
  return span <= 10 && !Number.isInteger(value) ? value.toFixed(1) : Math.round(value).toString()
}

// zone bands sit just inside the ticks
const zones = computed(() => {
  const bands: { d: string; c: string }[] = []
  const { warn, danger, min, max, lowIsBad } = props
  if (warn != null) bands.push({ d: bandPath(lowIsBad ? ang(danger ?? min) : ang(warn), lowIsBad ? ang(warn) : ang(danger ?? max), 69, 73), c: "var(--amber)" })
  if (danger != null) bands.push({ d: bandPath(lowIsBad ? ang(min) : ang(danger), lowIsBad ? ang(danger) : ang(max), 69, 73), c: "var(--red)" })
  return bands
})

const needle = computed(() => {
  const angle = ang(shown.value)
  const tip = pt(angle, 74)
  const leftPoint = pt(angle - 90, 3.2)
  const rightPoint = pt(angle + 90, 3.2)
  const tail = pt(angle + 180, 16)
  return `M ${tip[0]} ${tip[1]} L ${leftPoint[0]} ${leftPoint[1]} L ${tail[0]} ${tail[1]} L ${rightPoint[0]} ${rightPoint[1]} Z`
})

const valueText = computed(() => props.value.toFixed(props.decimals))
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 200 200" class="select-none">
    <defs>
      <radialGradient :id="`${id}f`" cx="0.5" cy="0.42" r="0.6">
        <stop offset="0" stop-color="#151b22" />
        <stop offset="0.75" stop-color="#07090c" />
        <stop offset="1" stop-color="#020304" />
      </radialGradient>
      <radialGradient :id="`${id}c`" cx="0.35" cy="0.3" r="0.8">
        <stop offset="0" stop-color="#4a525c" />
        <stop offset="0.5" stop-color="#11151a" />
        <stop offset="1" stop-color="#000" />
      </radialGradient>
      <linearGradient :id="`${id}n`" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="#ff7a5c" />
        <stop offset="0.5" stop-color="#f0566a" />
        <stop offset="1" stop-color="#c2384a" />
      </linearGradient>
      <filter :id="`${id}ns`" x="-50%" y="-50%" width="200%" height="200%">
        <feDropShadow dx="1.5" dy="2.5" stdDeviation="1.6" flood-color="#000" flood-opacity="0.7" />
      </filter>
      <filter :id="`${id}gl`" x="-20%" y="-20%" width="140%" height="140%">
        <feGaussianBlur stdDeviation="1.4" result="b" />
        <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
      </filter>
    </defs>

    <ChromeBezel layer="back" />
    <circle cx="100" cy="100" r="85" :fill="`url(#${id}f)`" />

    <!-- brand-blue accent ring outside the ticks -->
    <path :d="arcPath(A0, A1, 80.5)" stroke="var(--brand-b)" stroke-width="2.6" fill="none" stroke-linecap="round" :filter="`url(#${id}gl)`" />
    <path v-for="(zone, i) in zones" :key="i" :d="zone.d" :fill="zone.c" opacity="0.9" />

    <g v-for="(tick, i) in ticks" :key="i">
      <line :x1="pt(tick.a, 77)[0]" :y1="pt(tick.a, 77)[1]" :x2="pt(tick.a, tick.major ? 66 : 72)[0]" :y2="pt(tick.a, tick.major ? 66 : 72)[1]"
        stroke="#f2f4f7" :stroke-width="tick.major ? 2.6 : 1.1" :opacity="tick.major ? 1 : 0.75" stroke-linecap="round" />
      <text v-if="tick.label" :x="pt(tick.a, 55)[0]" :y="pt(tick.a, 55)[1] + 4.5" text-anchor="middle"
        fill="#f2f4f7" font-family="IBM Plex Sans" font-weight="600" font-size="13">{{ tick.label }}</text>
    </g>

    <text x="100" y="125" text-anchor="middle" fill="#f2f4f7" font-family="IBM Plex Sans" font-weight="600" font-size="10.5" letter-spacing="1.4">{{ label.toUpperCase() }}</text>
    <text x="100" y="143" text-anchor="middle" fill="var(--brand-b)" font-family="IBM Plex Mono" font-size="11.5">{{ valueText }}<tspan fill="#8695a7" font-size="9"> {{ unit }}</tspan></text>

    <path :d="needle" :fill="`url(#${id}n)`" :filter="`url(#${id}ns)`" />
    <circle cx="100" cy="100" r="9.5" :fill="`url(#${id}c)`" stroke="#000" stroke-width="0.8" />
    <circle cx="97" cy="97" r="2.4" fill="#fff" opacity="0.18" />

    <ChromeBezel layer="glass" />
  </svg>
</template>
