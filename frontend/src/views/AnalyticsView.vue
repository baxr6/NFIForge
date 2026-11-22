<script setup lang="ts">
import { ref } from "vue"
import LayoutButton from "@/components/layout/LayoutButton.vue"
import PanelGrid, { type Item } from "@/components/layout/PanelGrid.vue"
import { useAnalytics } from "@/lib/state/analytics"

// how the closed trades did; the filters here apply to every Analytics panel, on this page or any other
const { all, botAll, loading, load, RANGES, f, bots, shown } = useAnalytics()
const editing = ref(false)
const defaults: Item[] = [
  { i: "analytics-summary", x: 0, y: 0, w: 24, h: 2 },
  { i: "analytics-curve", x: 0, y: 3, w: 16, h: 9 },
  { i: "analytics-period", x: 16, y: 3, w: 8, h: 9 },
  { i: "analytics-calendar", x: 0, y: 12, w: 24, h: 5 },
  { i: "analytics-breakdown", x: 0, y: 17, w: 16, h: 10 },
  { i: "analytics-hold", x: 16, y: 17, w: 8, h: 10 },
  { i: "analytics-tag-exit", x: 0, y: 27, w: 24, h: 9 },
  { i: "analytics-excursion", x: 0, y: 36, w: 24, h: 11 },
]
const sel = "rounded-md bg-raised border border-line px-2 py-1 text-ink text-sm"
</script>

<template>
  <div class="space-y-3">
    <div class="flex flex-wrap items-center gap-3">
      <h1 class="text-xl font-semibold">Analytics</h1>
      <span class="text-sm text-dim">{{ loading ? "loading…" : `${shown.length} of ${botAll.length} closed trades` }}</span>
      <div class="ml-auto flex flex-wrap items-center gap-2">
        <select v-if="bots.length > 1" v-model="f.bot" :class="sel"><option value="">all bots</option><option v-for="name in bots" :key="name">{{ name }}</option></select>
        <select v-model="f.side" :class="sel"><option value="">long + short</option><option value="long">long</option><option value="short">short</option></select>
        <div class="flex rounded-md border border-line overflow-hidden text-sm">
          <button v-for="[label] in RANGES" :key="label" class="px-3 py-1" :class="f.range === label ? 'bg-raised text-ink' : 'text-dim hover:text-ink'" @click="f.range = label">{{ label }}</button>
        </div>
        <button class="text-xs px-3 py-1 rounded-md border border-line text-dim hover:text-ink" @click="load">↻</button>
        <LayoutButton v-model="editing" />
      </div>
    </div>
    <PanelGrid v-model:editing="editing" page="analytics" :defaults="defaults" />
  </div>
</template>
