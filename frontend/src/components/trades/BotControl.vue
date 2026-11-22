<script setup lang="ts">
import { computed, ref, toRef } from "vue"
import ConfirmStep from "@/components/trades/ConfirmStep.vue"
import { tradeAction, useTradeAccess } from "@/lib/tradeActions"
import { useLive } from "@/stores/live"

// pause / start / stop / reload config for one bot; same switches as trade actions, the bot's name typed on a live bot
const props = defineProps<{ bot: string }>()
const live = useLive()
const { isLive } = useTradeAccess(toRef(props, "bot"))
const state = computed(() => String(live.bots[props.bot]?.config?.state ?? "unknown"))
type Act = "pause" | "start" | "stop" | "reload_config"
const pick = ref<Act | null>(null)
const sent = ref("")

const INFO: Record<Act, { label: string; lines: string[]; warn: string }> = {
  pause: { label: "pause entries", lines: ["pause entries: no new trades"], warn: "Open trades are still managed (exits, grinds, stops)." },
  start: { label: "start", lines: ["start the bot (new entries on again)"], warn: "" },
  stop: { label: "stop", lines: ["stop the bot loop"], warn: "Open trades are NOT managed while stopped: no exits, no grinds. Only stop orders already on the exchange stay." },
  reload_config: { label: "reload config", lines: ["reload config and strategy files"], warn: "If the config or strategy file has an error the bot stays stopped." },
}
// what makes sense from the current state
const acts = computed<Act[]>(() =>
  state.value === "running" ? ["pause", "stop", "reload_config"] : state.value === "paused" ? ["start", "stop", "reload_config"] : ["start", "reload_config"],
)
const TONE: Record<string, string> = { running: "text-up border-up/40", paused: "text-warn border-warn/50", stopped: "text-down border-down/50" }

async function send(confirm: string) {
  const action = pick.value!
  const result = await tradeAction(props.bot, "control", { action: action, confirm })
  if (result.ok) { sent.value = `${INFO[action].label} sent`; pick.value = null }
  return result
}
const btn = "text-xs px-2.5 py-1 rounded-md border"
</script>

<template>
  <div class="space-y-2">
    <div class="flex flex-wrap items-center gap-2">
      <span class="text-[11px] px-2 py-0.5 rounded border uppercase" :class="TONE[state] ?? 'text-dim border-line'">{{ state }}</span>
      <button v-for="action in acts" :key="action" :class="[btn, pick === action ? 'border-brand-b text-ink' : action === 'stop' ? 'border-line text-dim hover:text-down' : 'border-line text-dim hover:text-ink']"
        @click="pick = pick === action ? null : action; sent = ''">{{ INFO[action].label }}</button>
      <span v-if="sent" class="text-xs text-up">✓ {{ sent }}</span>
    </div>
    <ConfirmStep v-if="pick" :key="pick" :lines="[`${bot}: ${INFO[pick].lines[0]}`]" :live="isLive" :coin="bot" :warn="INFO[pick].warn" :send="send" @cancel="pick = null" />
  </div>
</template>
