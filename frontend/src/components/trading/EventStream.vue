<script setup lang="ts">
import { computed, ref } from "vue"
import NoteDetail from "@/components/panels/notifications/NoteDetail.vue"
import type { LiveEvent, Note } from "@/stores/live"
import { wide } from "@/lib/viewport"

// live bot events, newest first; candle ticks are counted, not listed. a click opens the event in full
const props = defineProps<{ events: LiveEvent[]; utc: boolean; bot: string }>()
const tab = ref<"all" | "trades" | "warnings">("all")
const TRADE = new Set(["entry", "entry_fill", "entry_cancel", "exit", "exit_fill", "exit_cancel"])
const WARN = new Set(["warning", "exception", "protection_trigger", "protection_trigger_global", "liquidation_warning"])

const all = computed(() =>
  props.events
    .filter((event) => event.type !== "new_candle" && event.type !== "whitelist")
    .filter((event) => tab.value === "all" || (tab.value === "trades" ? TRADE.has(event.type) : WARN.has(event.type)))
    .slice(-150)
    .reverse(),
)
// phones: the list is part of the page (no inner scroll), so the newest 20 first and more on request
const more = ref(false)
const shown = computed(() => (wide.value || more.value ? all.value : all.value.slice(0, 20)))

function label(event: LiveEvent): string {
  const payload = event.data ?? {}
  if (TRADE.has(event.type)) return `${event.type.replace("_", " ")} ${payload.pair ?? ""} ${payload.enter_tag ?? payload.exit_reason ?? ""}`.trim()
  if (typeof payload === "string") return payload
  return payload.status ?? payload.msg ?? JSON.stringify(payload).slice(0, 120)
}
// btcgate rows carry their notification; bot events become one, with the event's plain fields as the detail
const picked = ref<Note | null>(null)
function open(event: LiveEvent) {
  const payload = event.data ?? {}
  if (payload.note) return (picked.value = payload.note)
  const detail = typeof payload === "object" ? Object.entries(payload).filter(([, value]) => value !== null && typeof value !== "object").map(([key, value]) => `${key}: ${value}`).join(" · ") : ""
  picked.value = { id: 0, ts: event.ts, bot: props.bot, kind: TRADE.has(event.type) ? "trade" : "alert", level: WARN.has(event.type) ? "warn" : "info", key: event.type, title: label(event), detail, cleared: null }
}
const color = (type: string) => (type.startsWith("entry") ? "var(--brand-b)" : type.startsWith("exit") ? "var(--amber)" : WARN.has(type) ? "var(--red)" : type === "btcgate" ? "var(--brand-a)" : "var(--text-dim)")
const time = (ts: number) => new Date(ts * 1000).toLocaleTimeString("en-GB", { timeZone: props.utc ? "UTC" : undefined })
</script>

<template>
  <div class="panel p-3 flex flex-col min-h-0">
    <div class="flex items-center gap-2">
      <div class="panel-title">Event stream</div>
      <div class="ml-auto flex gap-1 text-[11px]">
        <button v-for="tabName in (['all', 'trades', 'warnings'] as const)" :key="tabName" class="px-2 py-0.5 rounded"
          :class="tab === tabName ? 'bg-hover text-ink' : 'text-dim hover:text-ink'" @click="tab = tabName">{{ tabName }}</button>
      </div>
    </div>
    <div class="mt-2 overflow-auto flex-1 min-h-[160px] text-xs">
      <button v-for="(event, i) in shown" :key="i" class="w-full text-left flex gap-2 py-1 border-b border-line last:border-0 hover:bg-raised" @click="open(event)">
        <span class="num text-faint shrink-0">{{ time(event.ts) }}</span>
        <span class="h-1.5 w-1.5 rounded-full mt-1.5 shrink-0" :style="{ background: color(event.type) }" />
        <span class="truncate">{{ label(event) }}</span>
      </button>
      <button v-if="shown.length < all.length" class="w-full py-2 text-dim hover:text-ink" @click="more = true">show {{ all.length - shown.length }} more</button>
      <div v-if="!shown.length" class="text-dim py-6 text-center">no trade or warning events yet; they appear here live</div>
    </div>
    <NoteDetail v-if="picked" :note="picked" @close="picked = null" />
  </div>
</template>
