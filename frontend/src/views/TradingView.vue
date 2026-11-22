<script setup lang="ts">
import { computed, ref } from "vue"
import { useRoute } from "vue-router"
import LayoutButton from "@/components/layout/LayoutButton.vue"
import PanelGrid, { type Item } from "@/components/layout/PanelGrid.vue"
import { MAX_SLOT_PANELS } from "@/lib/panels"
import { useTrading } from "@/lib/trading"
import { storeToRefs } from "pinia"
import { useLive } from "@/stores/live"

const live = useLive()
const names = computed(() => Object.keys(live.bots))
const { picked } = storeToRefs(live)
const trading = useTrading()
const bot = trading.bot
// ?edit=1 opens the page straight into layout editing
const editing = ref(useRoute().query.edit === "1")

// default layout on the 24 column grid, 40 px rows ("status" and "money" stand for their card sets); one panel
// per slot, four to a row
const defaults = computed<Item[]>(() => {
  const count = Math.min(Math.max(trading.maxSlots.value, trading.open.value.length, 1), MAX_SLOT_PANELS)
  const rows = Math.ceil(count / 4), below = 10 + rows * 5
  const slots = Array.from({ length: count }, (_, index) => ({ i: `slot-${index + 1}`, x: (index % 4) * 6, y: 10 + Math.floor(index / 4) * 5, w: 6, h: 5 }))
  const head = [
    { i: "status", x: 0, y: 0, w: 24, h: 2 },
    { i: "money", x: 0, y: 2, w: 24, h: 4 },
    { i: "gauges", x: 0, y: 6, w: 24, h: 4 },
  ]
  // the grid pulls panels up into free space, so a part-full last slot row gets the event stream, sized to the gap
  const left = count % 4
  if (left) return [
    ...head, ...slots,
    { i: "events", x: left * 6, y: below - 5, w: 24 - left * 6, h: 5 },
    { i: "today", x: 0, y: below, w: 12, h: 8 },
    { i: "pulse", x: 12, y: below, w: 12, h: 8 },
  ]
  return [
    ...head, ...slots,
    { i: "today", x: 0, y: below, w: 8, h: 8 },
    { i: "pulse", x: 8, y: below, w: 8, h: 8 },
    { i: "events", x: 16, y: below, w: 8, h: 8 },
  ]
})
</script>

<template>
  <div v-if="!bot" class="panel p-6 text-dim">waiting for the backend… check that NFIForge is running and a bot is configured</div>
  <div v-else>
    <!-- bot tabs: bordered, current one lifted with the brand underline -->
    <div class="flex items-end gap-1 border-b border-line mb-3">
      <button v-for="name in names" :key="name" class="tab" :class="{ active: name === picked }" @click="picked = name">
        <span class="h-1.5 w-1.5 rounded-full" :style="{ background: live.bots[name].connected ? 'var(--green)' : 'var(--red)', boxShadow: live.bots[name].connected ? '0 0 6px var(--green)' : 'none' }" />
        <span>{{ name }}</span>
        <span v-if="live.bots[name].config && !live.bots[name].config.dry_run" class="live-badge">LIVE</span>
      </button>
      <div class="ml-auto flex items-center gap-3 pb-1.5 min-w-0">
        <span class="text-xs text-dim truncate hidden md:inline">{{ bot.config?.strategy }} · {{ bot.config?.exchange }} {{ bot.config?.trading_mode }} · {{ bot.config?.dry_run ? "dry run" : "live" }}</span>
        <LayoutButton v-model="editing" />
      </div>
    </div>

    <PanelGrid v-model:editing="editing" page="trading" :defaults="defaults" />
  </div>
</template>

<style scoped>
.tab {
  position: relative; display: inline-flex; align-items: center; gap: 8px;
  padding: 7px 14px; margin-bottom: -1px; font-size: 13px; color: var(--text-dim);
  background: var(--panel); border: 1px solid var(--line); border-bottom-color: var(--line);
  border-radius: 8px 8px 0 0; transition: color 0.15s var(--ease), background 0.15s var(--ease);
}
.tab:hover { color: var(--text); background: var(--panel-hover); }
.tab.active { color: var(--text); background: var(--panel-raised); border-bottom-color: var(--panel-raised); font-weight: 600; }
.tab.active::after {
  content: ""; position: absolute; left: 10px; right: 10px; top: -1px; height: 2px; border-radius: 2px;
  background: linear-gradient(90deg, var(--brand-a), var(--brand-b)); box-shadow: 0 0 8px var(--brand-glow);
}
.live-badge { font-size: 9px; font-weight: 700; letter-spacing: 0.08em; padding: 1px 5px; border-radius: 4px; color: var(--amber); background: var(--amber-dim); }
</style>
