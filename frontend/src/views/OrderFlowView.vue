<script setup lang="ts">
import { ref } from "vue"
import LayoutButton from "@/components/layout/LayoutButton.vue"
import PanelGrid, { type Item } from "@/components/layout/PanelGrid.vue"
import { panelSpec } from "@/lib/panels"
import { wide } from "@/lib/viewport"

// order flow chart, dom ladder, tape and depth chart as movable panels (they follow one pair); any other panel can be
// added. phones: one of them at a time, full height, picked by tabs
const editing = ref(false)
const defaults: Item[] = [
  { i: "orderflow", x: 0, y: 0, w: 18, h: 24 },
  { i: "orderflow-dom", x: 18, y: 0, w: 6, h: 11 },
  { i: "orderflow-tape", x: 18, y: 11, w: 6, h: 7 },
  { i: "orderflow-depth", x: 18, y: 18, w: 6, h: 6 },
]
const TABS = [
  { id: "orderflow", label: "Chart" },
  { id: "orderflow-dom", label: "DOM" },
  { id: "orderflow-tape", label: "Tape" },
  { id: "orderflow-depth", label: "Depth" },
]
const tab = ref("orderflow")
</script>

<template>
  <div class="space-y-3">
    <div class="flex items-center gap-3">
      <h1 class="text-xl font-semibold">Order Flow</h1>
      <div v-if="wide" class="ml-auto"><LayoutButton v-model="editing" /></div>
      <div v-else class="ml-auto flex rounded-md border border-line overflow-hidden text-sm">
        <button v-for="option in TABS" :key="option.id" class="px-2.5 py-1" :class="tab === option.id ? 'bg-raised text-ink' : 'text-dim'" @click="tab = option.id">{{ option.label }}</button>
      </div>
    </div>
    <PanelGrid v-if="wide" v-model:editing="editing" page="orderflow" :defaults="defaults" />
    <!-- the screen less the top bar, title row and bottom nav -->
    <div v-else class="h-[calc(100dvh-11rem)] min-h-[28rem]">
      <component :is="panelSpec(tab)!.comp" />
    </div>
  </div>
</template>
