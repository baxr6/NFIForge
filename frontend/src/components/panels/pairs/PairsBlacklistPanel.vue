<script setup lang="ts">
import { computed, ref } from "vue"
import PanelCard from "@/components/layout/PanelCard.vue"
import ConfirmStep from "@/components/trades/ConfirmStep.vue"
import { usePairs } from "@/lib/state/pairs"
import { tradeAction, useTradeAccess } from "@/lib/tradeActions"

// blacklist rules; add / remove when the bot's trading switch is on (typed confirm on a live bot). freqtrade keeps
// these edits until the bot restarts or reloads its config, then the config's blacklist is back
const { data, blCount, bot, load, pairFor, base } = usePairs()
const { canTrade, isLive } = useTradeAccess(computed(() => bot.value?.name))
const adding = ref(false)
const typed = ref("")
const pending = ref<{ action: "add" | "remove"; pair: string } | null>(null)
const sent = ref("")
// a pattern (has regex characters) is sent as typed, a coin becomes the bot's pair name
const entry = computed(() => (/[.*()|[\]^$+?]/.test(typed.value) ? typed.value.trim() : pairFor(typed.value)))

async function send(confirm: string) {
  const request = pending.value!
  const result = await tradeAction(bot.value!.name, "blacklist", { ...request, confirm })
  if (result.ok) {
    sent.value = `${request.pair} ${request.action === "add" ? "blacklisted" : "removed"}`
    pending.value = null
    adding.value = false
    typed.value = ""
    load()
  }
  return result
}
</script>

<template>
  <PanelCard :title="`Blacklist · ${data?.blacklist.length ?? 0} rules · ${data?.blacklist_expanded.length ?? 0} pairs`">
    <template v-if="canTrade" #actions>
      <span v-if="sent" class="text-xs text-up">✓ {{ sent }}</span>
      <button class="text-xs px-2 py-0.5 rounded border border-line text-dim hover:text-ink" @click="adding = !adding; pending = null; sent = ''">+ add</button>
    </template>
    <div v-if="adding && !pending" class="flex flex-wrap gap-2 items-center mb-2 pb-2 border-b border-line text-xs">
      <input v-model="typed" placeholder="coin, pair or pattern" class="w-44 rounded-md bg-raised border border-line px-2 py-1 text-ink num" @keyup.enter="entry && (pending = { action: 'add', pair: entry })" />
      <span v-if="entry" class="text-dim num">{{ entry }}</span>
      <button class="px-3 py-1 rounded-md border border-brand-b/50 bg-brand-b/20 text-ink disabled:opacity-40" :disabled="!entry" @click="pending = { action: 'add', pair: entry }">next</button>
    </div>
    <ConfirmStep v-if="pending" class="mb-2" :live="isLive" :coin="pending.pair.includes('/') && !/[.*()|]/.test(pending.pair) ? base(pending.pair) : pending.pair"
      :lines="[`${pending.action === 'add' ? 'blacklist' : 'remove from blacklist'} ${pending.pair}`]"
      :warn="pending.action === 'add' ? 'No new entries on it. Open trades are still managed. Lasts until the bot restarts or reloads its config.' : 'Lasts until the bot restarts or reloads its config (then the config blacklist is back).'"
      :send="send" @cancel="pending = null" />
    <div class="flex flex-wrap gap-1.5 min-w-0">
      <span v-for="pattern in data?.blacklist ?? []" :key="pattern" class="text-xs num rounded border border-line px-1.5 py-0.5 text-dim max-w-full min-w-0 inline-flex items-center gap-1" :title="`${pattern}\n${blCount(pattern)} pairs`"><span class="truncate min-w-0">{{ pattern }}</span>
        <button v-if="canTrade" class="text-faint hover:text-down min-h-8 min-w-8" :title="`remove ${pattern}`" @click="pending = { action: 'remove', pair: pattern }; adding = false; sent = ''">✕</button></span>
    </div>
  </PanelCard>
</template>
