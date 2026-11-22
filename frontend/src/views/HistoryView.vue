<script setup lang="ts">
import { ref } from "vue"
import DownloadButton from "@/components/DownloadButton.vue"
import LayoutButton from "@/components/layout/LayoutButton.vue"
import PanelGrid, { type Item } from "@/components/layout/PanelGrid.vue"
import { useFiat } from "@/lib/fiat"
import { useHistoryPage } from "@/lib/state/history"
import { closedSheet, ordersSheet } from "@/lib/tradeSheets"

// every closed trade of every bot; the filters here apply to the history panels wherever they are
const { all, loading, load, f, opts, clear, shown } = useHistoryPage()
const fiat = useFiat(() => "USDT")
// the trades the filters show, and every order of them
const sheets = () => [closedSheet(shown.value, fiat.rate.value), ordersSheet(shown.value)]
const editing = ref(false)
const defaults: Item[] = [
  { i: "history-summary", x: 0, y: 0, w: 24, h: 2 },
  { i: "history-table", x: 0, y: 3, w: 24, h: 16 },
]
const sel = "rounded-md bg-raised border border-line px-2 py-1 text-ink text-sm"
</script>

<template>
  <div class="space-y-3">
    <div class="flex flex-wrap items-baseline gap-3">
      <h1 class="text-xl font-semibold">Trade History</h1>
      <span class="text-sm text-dim">{{ loading ? "loading…" : `${all.length} closed trades` }}</span>
      <div class="ml-auto flex items-center gap-2">
        <button class="text-xs px-3 py-1 rounded-md border border-line text-dim hover:text-ink" @click="load">↻ reload</button>
        <DownloadButton name="trades" :sheets="sheets" :disabled="!shown.length" />
        <LayoutButton v-model="editing" />
      </div>
    </div>

    <div class="panel p-3 flex flex-wrap gap-2 items-center">
      <select v-if="opts.bots.length > 1" v-model="f.bot" :class="sel"><option value="">all bots</option><option v-for="name in opts.bots" :key="name">{{ name }}</option></select>
      <input v-model="f.pair" placeholder="pair" :class="sel" class="w-28" />
      <select v-model="f.tag" :class="sel"><option value="">all tags</option><option v-for="tag in opts.tags" :key="tag">{{ tag }}</option></select>
      <select v-model="f.exit" :class="sel" class="max-w-56"><option value="">all exits</option><option v-for="exit in opts.exits" :key="exit">{{ exit }}</option></select>
      <select v-model="f.side" :class="sel"><option value="">long + short</option><option value="long">long</option><option value="short">short</option></select>
      <select v-model="f.result" :class="sel"><option value="">wins + losses</option><option value="win">wins</option><option value="loss">losses</option></select>
      <input v-model="f.from" type="date" :class="sel" /><span class="text-faint text-xs">to</span><input v-model="f.to" type="date" :class="sel" />
      <button class="text-xs text-dim hover:text-ink px-2" @click="clear">clear</button>
    </div>

    <PanelGrid v-model:editing="editing" page="history" :defaults="defaults" />
  </div>
</template>
