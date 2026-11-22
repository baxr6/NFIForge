<script setup lang="ts">
import { ref } from "vue"
import LayoutButton from "@/components/layout/LayoutButton.vue"
import PanelGrid, { type Item } from "@/components/layout/PanelGrid.vue"

// Chart as a movable panel; any other panel can be added next to it
const editing = ref(false)
const defaults: Item[] = [{ i: "chart", x: 0, y: 0, w: 24, h: 18 }]
</script>

<template>
  <div class="space-y-3">
    <div class="flex items-center gap-3">
      <h1 class="text-xl font-semibold">Chart</h1>
      <div class="ml-auto"><LayoutButton v-model="editing" /></div>
    </div>
    <PanelGrid v-model:editing="editing" page="chart" :defaults="defaults" />
  </div>
</template>
