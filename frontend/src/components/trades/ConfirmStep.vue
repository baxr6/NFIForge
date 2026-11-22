<script setup lang="ts">
import { computed, ref } from "vue"

// last step of every trade action: what will be sent, the coin typed back on a live bot, one send, the bot's answer
const props = defineProps<{ lines: string[]; live: boolean; coin: string; warn?: string; send: (confirm: string) => Promise<{ ok: boolean; error: string }> }>()
const emit = defineEmits<{ done: []; cancel: [] }>()
const typed = ref("")
const busy = ref(false)
const error = ref("")
const ready = computed(() => !props.live || typed.value.trim().toUpperCase() === props.coin.toUpperCase())

async function go() {
  busy.value = true
  error.value = ""
  const result = await props.send(typed.value)
  busy.value = false
  if (result.ok) emit("done")
  else error.value = result.error
}
</script>

<template>
  <div class="rounded-md border p-3 space-y-2 text-sm" :class="live ? 'border-down/60 bg-[var(--red-dim)]' : 'border-line bg-raised'">
    <div class="font-semibold" :class="live ? 'text-down' : ''">{{ live ? "Live bot: real money" : "Check and send" }}</div>
    <div v-for="line in lines" :key="line" class="num">{{ line }}</div>
    <p v-if="warn" class="text-xs text-warn">{{ warn }}</p>
    <label v-if="live" class="block text-xs text-dim">type <span class="text-ink font-semibold">{{ coin }}</span> to confirm
      <input v-model="typed" class="mt-1 w-40 rounded-md bg-void border border-line px-2 py-1 text-ink num" autocomplete="off" @keyup.enter="ready && !busy && go()" />
    </label>
    <div class="flex items-center gap-2">
      <button class="px-3 py-1 rounded-md border text-ink disabled:opacity-40" :class="live ? 'bg-down/30 border-down/60' : 'bg-brand-b/20 border-brand-b/50'" :disabled="!ready || busy" @click="go">{{ busy ? "sending…" : "send" }}</button>
      <button class="px-3 py-1 text-dim hover:text-ink" :disabled="busy" @click="emit('cancel')">back</button>
      <span v-if="error" class="text-down text-xs">✕ {{ error }}</span>
    </div>
  </div>
</template>
