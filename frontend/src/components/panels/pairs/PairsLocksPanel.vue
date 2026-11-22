<script setup lang="ts">
import { computed, ref } from "vue"
import PanelCard from "@/components/layout/PanelCard.vue"
import ConfirmStep from "@/components/trades/ConfirmStep.vue"
import { age } from "@/lib/format"
import { usePairs } from "@/lib/state/pairs"
import { tradeAction, useTradeAccess } from "@/lib/tradeActions"

// pair locks; lock / unlock when the bot's trading switch is on (typed confirm on a live bot)
const { data, base, bot, load, pairFor } = usePairs()
const { canTrade, isLive } = useTradeAccess(computed(() => bot.value?.name))
const adding = ref(false)
const coin = ref("")
const side = ref("*")
const minutes = ref(60)
const reason = ref("")
const PRESETS: [string, number][] = [["30m", 30], ["1h", 60], ["4h", 240], ["24h", 1440], ["7d", 10080]]
// what is being confirmed: a new lock, or an unlock of lock id
const pending = ref<{ kind: "lock"; pair: string } | { kind: "unlock"; id: number; pair: string } | null>(null)
const sent = ref("")
const pair = computed(() => pairFor(coin.value))
const confirmWord = (pair: string) => (pair === "*" ? bot.value?.name ?? "" : base(pair))
const sideText = (side: string) => (side === "*" ? "both sides" : `${side} only`)

async function send(confirm: string) {
  const request = pending.value!
  const result = request.kind === "lock"
    ? await tradeAction(bot.value!.name, "lock", { pair: request.pair, side: side.value, minutes: minutes.value, reason: reason.value, confirm })
    : await tradeAction(bot.value!.name, "unlock", { lockid: request.id, confirm })
  if (result.ok) {
    sent.value = request.kind === "lock" ? `${request.pair === "*" ? "all pairs" : base(request.pair)} locked` : `${base(request.pair)} unlocked`
    pending.value = null
    adding.value = false
    load()
  }
  return result
}
const input = "rounded-md bg-raised border border-line px-2 py-1 text-ink text-xs num"
</script>

<template>
  <PanelCard title="Locks">
    <template v-if="canTrade" #actions>
      <span v-if="sent" class="text-xs text-up">✓ {{ sent }}</span>
      <button class="text-xs px-2 py-0.5 rounded border border-line text-dim hover:text-ink" @click="adding = !adding; pending = null; sent = ''">+ lock</button>
    </template>
    <div v-if="adding && !pending" class="space-y-2 mb-2 pb-2 border-b border-line text-xs">
      <div class="flex flex-wrap gap-2 items-center">
        <input v-model="coin" placeholder="coin, pair or * (all)" :class="[input, 'w-40']" />
        <select v-model="side" :class="input"><option value="*">both sides</option><option value="long">long only</option><option value="short">short only</option></select>
      </div>
      <div class="flex flex-wrap gap-1 items-center">
        <button v-for="[label, presetMinutes] in PRESETS" :key="label" class="px-2 py-0.5 rounded border" :class="minutes === presetMinutes ? 'border-brand-b text-ink' : 'border-line text-dim hover:text-ink'" @click="minutes = presetMinutes">{{ label }}</button>
        <input v-model.number="minutes" type="number" min="1" :class="[input, 'w-20']" /> <span class="text-dim">min</span>
      </div>
      <input v-model="reason" placeholder="reason (optional)" maxlength="100" :class="[input, 'w-full']" />
      <button class="px-3 py-1 rounded-md border border-brand-b/50 bg-brand-b/20 text-ink disabled:opacity-40" :disabled="!pair || !(minutes > 0)" @click="pending = { kind: 'lock', pair }">next</button>
    </div>
    <ConfirmStep v-if="pending" class="mb-2" :live="isLive" :coin="confirmWord(pending.pair)"
      :lines="pending.kind === 'lock' ? [`lock ${pending.pair === '*' ? 'ALL pairs' : pending.pair} · ${sideText(side)} · ${minutes} min`, reason ? `reason: ${reason}` : 'reason: locked from NFIForge'] : [`unlock ${pending.pair}`]"
      :warn="pending.kind === 'lock' ? 'No new entries on it until the lock ends. Open trades are still managed.' : ''"
      :send="send" @cancel="pending = null" />
    <div v-for="lock in data?.locks ?? []" :key="lock.id ?? lock.pair + lock.side" class="text-sm py-1 border-b border-line last:border-0 flex items-start gap-2">
      <div class="min-w-0 flex-1">
        <span class="font-semibold num">{{ lock.pair === "*" ? "ALL pairs" : base(lock.pair) }}</span> <span class="text-dim">{{ lock.side !== "*" ? lock.side : "" }}</span>
        <span class="text-warn num"> {{ age(Date.now() / 1000, lock.lock_end_timestamp / 1000) }} left</span>
        <div class="text-xs text-faint">{{ lock.reason || "no reason given" }}</div>
      </div>
      <button v-if="canTrade && lock.id != null" class="text-[11px] px-2 py-0.5 rounded border border-line text-dim hover:text-ink shrink-0" @click="pending = { kind: 'unlock', id: lock.id, pair: lock.pair }; sent = ''">unlock</button>
    </div>
    <div v-if="!data?.locks.length" class="text-sm text-faint">none</div>
  </PanelCard>
</template>
