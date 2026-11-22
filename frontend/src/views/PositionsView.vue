<script setup lang="ts">
import { ref } from "vue"
import LayoutButton from "@/components/layout/LayoutButton.vue"
import PanelGrid, { type Item } from "@/components/layout/PanelGrid.vue"

// Positions as a movable panel; any other panel can be added next to it
const editing = ref(false)
const defaults: Item[] = [{ i: "positions", x: 0, y: 0, w: 24, h: 14 }]
</script>

<template>
  <div class="space-y-3">
    <div class="flex items-center gap-3">
      <h1 class="text-xl font-semibold">Positions</h1>
      <div class="ml-auto"><LayoutButton v-model="editing" /></div>
    </div>
    <PanelGrid v-model:editing="editing" page="positions" :defaults="defaults" />
  </div>
</template>
