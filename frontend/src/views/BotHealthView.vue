<script setup lang="ts">
import { ref } from "vue"
import LayoutButton from "@/components/layout/LayoutButton.vue"
import PanelGrid, { type Item } from "@/components/layout/PanelGrid.vue"

// Bot Health as a movable panel; any other panel can be added next to it
const editing = ref(false)
const defaults: Item[] = [{ i: "bot-health", x: 0, y: 0, w: 24, h: 16 }]
</script>

<template>
  <div class="space-y-3">
    <div class="flex items-center gap-3">
      <h1 class="text-xl font-semibold">Bot Health</h1>
      <div class="ml-auto"><LayoutButton v-model="editing" /></div>
    </div>
    <PanelGrid v-model:editing="editing" page="bot-health" :defaults="defaults" />
  </div>
</template>
