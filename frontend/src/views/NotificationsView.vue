<script setup lang="ts">
import { onMounted, ref, watch } from "vue"
import { RouterLink } from "vue-router"
import LayoutButton from "@/components/layout/LayoutButton.vue"
import PanelGrid, { type Item } from "@/components/layout/PanelGrid.vue"
import { useLive } from "@/stores/live"
import { useSettings } from "@/stores/settings"

// alerts and trade events as movable panels; having this page open marks everything read
const live = useLive()
const settings = useSettings()
const editing = ref(false)
const defaults: Item[] = [
  { i: "alerts", x: 0, y: 0, w: 24, h: 3 },
  { i: "notifications", x: 0, y: 3, w: 24, h: 14 },
]

async function markRead() {
  const top = live.notes[0]?.id
  if (top && live.unread) await fetch("/api/notifications/read", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: top }) }).catch(() => {})
}
onMounted(async () => { await live.loadNotes(); markRead() })
// new ones while the page is open count as read
watch(() => live.notes[0]?.id, markRead)

// desktop pop-ups need the browser's permission once
const perm = ref("Notification" in window ? Notification.permission : "unsupported")
async function allow() { if ("Notification" in window) perm.value = await Notification.requestPermission() }
</script>

<template>
  <div class="space-y-3">
    <div class="flex flex-wrap items-baseline gap-3">
      <h1 class="text-xl font-semibold">Notifications</h1>
      <span class="text-sm text-dim">alert levels in <RouterLink to="/settings" class="text-brand-b hover:underline">Settings</RouterLink></span>
      <span v-if="settings.s?.alerts.browser && perm !== 'granted'" class="text-xs text-warn">
        desktop pop-ups are on but this browser {{ perm === "denied" ? "blocks them" : "hasn't allowed them" }}
        <button v-if="perm === 'default'" class="underline ml-1" @click="allow">allow</button></span>
      <div class="ml-auto"><LayoutButton v-model="editing" /></div>
    </div>
    <PanelGrid v-model:editing="editing" page="notifications" :defaults="defaults" />
  </div>
</template>
