<script setup lang="ts">
import { ref } from "vue"
import LayoutButton from "@/components/layout/LayoutButton.vue"
import PanelGrid, { type Item } from "@/components/layout/PanelGrid.vue"
import { usePairs } from "@/lib/state/pairs"

// which pairs the bot can trade and why not the others, as movable panels
const { data, open, botNames, botName } = usePairs()
const editing = ref(false)
const defaults: Item[] = [
  { i: "pairs-find", x: 0, y: 0, w: 24, h: 3 },
  { i: "pairs-whitelist", x: 0, y: 3, w: 16, h: 12 },
  { i: "pairs-locks", x: 16, y: 3, w: 8, h: 4 },
  { i: "pairs-blacklist", x: 16, y: 7, w: 8, h: 8 },
  { i: "pairs-filtered", x: 0, y: 15, w: 16, h: 8 },
  { i: "pairs-changes", x: 16, y: 15, w: 8, h: 8 },
]
</script>

<template>
  <div class="space-y-3">
    <div class="flex flex-wrap items-center gap-3">
      <h1 class="text-xl font-semibold">Pairs</h1>
      <span v-if="data" class="text-sm text-dim num">{{ data.whitelist.length }} on the whitelist · {{ open.size }} in trades · {{ data.locks.length }} locked · {{ data.blacklist_expanded.length }} blacklisted</span>
      <div class="ml-auto flex items-center gap-2">
        <select v-if="botNames.length > 1" v-model="botName" class="rounded-md bg-raised border border-line px-2 py-1 text-ink text-sm"><option v-for="name in botNames" :key="name" :value="name">{{ name }}</option></select>
        <LayoutButton v-model="editing" />
      </div>
    </div>
    <PanelGrid v-model:editing="editing" page="pairs" :defaults="defaults" />
  </div>
</template>
