<script setup lang="ts">
import { onMounted, ref } from "vue"
import { disable, enable, pushState, test, type PushState } from "@/lib/push"

// phone alerts for this device: every alert pushed here, even with the app closed
const state = ref<PushState | null>(null)
const busy = ref(false)
const msg = ref("")
const ok = ref(false)
const refresh = async () => (state.value = await pushState())
onMounted(refresh)

async function run(action: () => Promise<string | void>, done: string) {
  busy.value = true
  const error = (await action().catch((failure) => String(failure?.message ?? failure))) || ""
  ok.value = !error
  msg.value = error || done
  busy.value = false
  await refresh()
}
const HINT: Record<string, string> = {
  "needs-https": "needs the dashboard on https (Tailscale serve, see the README); plain http can't receive pushes",
  "needs-home-screen": "on an iPhone: Share → Add to Home Screen, then open NFIForge from the home screen and turn this on there",
  unsupported: "this browser can't receive pushes",
  blocked: "notifications are blocked for this site in the phone's settings",
}
</script>

<template>
  <section class="panel p-4">
    <div class="panel-title">Phone alerts</div>
    <p class="text-xs text-dim mt-1 mb-3">every alert pushed to this device, even with the app closed; each device turns it on for itself</p>
    <div v-if="state && HINT[state]" class="text-sm text-warn">{{ HINT[state] }}</div>
    <div v-else-if="state" class="flex flex-wrap items-center gap-3">
      <button role="switch" :aria-checked="state === 'on'" class="toggle" :class="{ on: state === 'on' }" :disabled="busy"
        @click="state === 'on' ? run(disable, 'phone alerts off on this device') : run(enable, 'phone alerts on for this device')"><span /></button>
      <div class="text-sm">Alerts on this device</div>
      <button v-if="state === 'on'" class="px-3 py-1.5 rounded-md border border-line hover:border-line-bright text-sm" :disabled="busy"
        @click="run(test, 'test alert sent')">Send a test</button>
    </div>
    <div v-if="msg" class="text-sm mt-2" :class="ok ? 'text-up' : 'text-down'">{{ msg }}</div>
  </section>
</template>
