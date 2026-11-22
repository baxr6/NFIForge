<script setup lang="ts">
import { ref } from "vue"
import LayoutButton from "@/components/layout/LayoutButton.vue"
import PanelGrid, { type Item } from "@/components/layout/PanelGrid.vue"
import { RANGES, useServer } from "@/lib/state/server"

// the machine the bots run on: gauges, containers and history, as movable panels
const server = useServer()
const editing = ref(false)
const defaults: Item[] = [
  { i: "server-gauges", x: 0, y: 0, w: 24, h: 5 },
  { i: "server-stats", x: 0, y: 5, w: 24, h: 2 },
  { i: "server-containers", x: 0, y: 7, w: 24, h: 9 },
  { i: "server-cpu", x: 0, y: 16, w: 12, h: 5 },
  { i: "server-ram", x: 12, y: 16, w: 12, h: 5 },
  { i: "server-container-mem", x: 0, y: 21, w: 24, h: 7 },
  { i: "server-disk", x: 0, y: 28, w: 12, h: 4 },
  { i: "server-loops", x: 12, y: 28, w: 12, h: 4 },
]
</script>

<template>
  <div class="space-y-3">
    <div class="flex flex-wrap items-center gap-3">
      <h1 class="text-xl font-semibold">Server</h1>
      <span class="text-xs text-faint">alert levels in Settings → Alerts</span>
      <div class="ml-auto flex items-center gap-2">
        <span class="text-xs text-dim">history</span>
        <div class="flex rounded-md border border-line overflow-hidden text-xs">
          <button v-for="[label, hours] in RANGES" :key="label" class="px-2.5 py-0.5" :class="server.range.value === hours ? 'bg-raised text-ink' : 'text-dim hover:text-ink'" @click="server.range.value = hours">{{ label }}</button>
        </div>
        <LayoutButton v-model="editing" />
      </div>
    </div>
    <PanelGrid v-model:editing="editing" page="server" :defaults="defaults" />
  </div>
</template>
