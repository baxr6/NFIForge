<script setup lang="ts">
import { computed } from "vue"
import { btcgateOn } from "@/lib/btcgate"
import { useAuth } from "@/stores/auth"
import { useLive } from "@/stores/live"

// phones: the pages used most, within thumb reach; More opens the full menu
defineProps<{ menuOpen: boolean }>()
const emit = defineEmits<{ more: [] }>()
const live = useLive()
const auth = useAuth()
const tabs = computed(() => [
  { path: "/trading", label: "Trading", icon: "M4 19V9M10 19V5M16 19v-7M22 19H2" },
  { path: "/positions", label: "Positions", icon: "M4 6h16M4 12h16M4 18h10" },
  ...(btcgateOn.value ? [{ path: "/btcgate", label: "BTCGate", icon: "M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7z" }] : []),
  ...(auth.can("notifications") ? [{ path: "/notifications", label: "Alerts", icon: "M6 9a6 6 0 0 1 12 0c0 6 2.5 7.5 2.5 7.5h-17S6 15 6 9M10 20a2 2 0 0 0 4 0" }] : []),
])
</script>

<template>
  <nav class="flex border-t border-line bg-panel">
    <RouterLink v-for="tab in tabs" :key="tab.path" :to="tab.path" class="tab" active-class="tab-on">
      <span class="relative">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path :d="tab.icon" /></svg>
        <span v-if="tab.path === '/notifications' && live.unread" class="absolute -top-1 -right-2 num text-[9px] leading-none px-1 py-0.5 rounded-full bg-down text-ink">{{ live.unread > 99 ? "99+" : live.unread }}</span>
      </span>
      <span>{{ tab.label }}</span>
    </RouterLink>
    <button class="tab" :class="menuOpen && 'tab-on'" aria-label="more pages" @click="emit('more')">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16" /></svg>
      <span>More</span>
    </button>
  </nav>
</template>

<style scoped>
.tab { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 6px 0 4px; font-size: 11px; color: var(--text-dim); min-height: 52px; }
.tab-on { color: var(--text); box-shadow: inset 0 2px 0 var(--brand-b); }
</style>
