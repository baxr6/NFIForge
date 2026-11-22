<script setup lang="ts">
import { uid } from "./geometry"

// shared chrome ring + glass highlight, drawn behind / over each gauge face
defineProps<{ layer: "back" | "glass" }>()
const id = uid("bz")
</script>

<template>
  <g v-if="layer === 'back'">
    <defs>
      <linearGradient :id="`${id}o`" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#fbfcfd" />
        <stop offset="0.22" stop-color="#9aa3ae" />
        <stop offset="0.45" stop-color="#eef1f4" />
        <stop offset="0.62" stop-color="#6b7480" />
        <stop offset="0.82" stop-color="#d9dee4" />
        <stop offset="1" stop-color="#7d8692" />
      </linearGradient>
      <linearGradient :id="`${id}i`" x1="1" y1="1" x2="0" y2="0">
        <stop offset="0" stop-color="#f4f6f8" />
        <stop offset="0.5" stop-color="#7a838e" />
        <stop offset="1" stop-color="#dfe3e8" />
      </linearGradient>
      <filter :id="`${id}s`" x="-20%" y="-20%" width="140%" height="140%">
        <feDropShadow dx="0" dy="3" stdDeviation="3" flood-color="#000" flood-opacity="0.6" />
      </filter>
    </defs>
    <circle cx="100" cy="100" r="98" :fill="`url(#${id}o)`" :filter="`url(#${id}s)`" />
    <circle cx="100" cy="100" r="91" :fill="`url(#${id}i)`" />
    <circle cx="100" cy="100" r="86.5" fill="#05070a" />
  </g>
  <g v-else pointer-events="none">
    <defs>
      <linearGradient :id="`${id}g`" x1="0" y1="0" x2="0.7" y2="0.8">
        <stop offset="0" stop-color="#fff" stop-opacity="0.13" />
        <stop offset="0.45" stop-color="#fff" stop-opacity="0.03" />
        <stop offset="0.46" stop-color="#fff" stop-opacity="0" />
      </linearGradient>
    </defs>
    <circle cx="100" cy="100" r="85" :fill="`url(#${id}g)`" />
  </g>
</template>
