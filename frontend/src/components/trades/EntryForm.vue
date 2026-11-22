<script setup lang="ts">
import { computed, ref, watch } from "vue"
import ConfirmStep from "@/components/trades/ConfirmStep.vue"
import PriceBox from "@/components/trades/PriceBox.vue"
import { money } from "@/lib/format"
import { addTags, tradeAction, useTradeAccess } from "@/lib/tradeActions"
import { filledOrders, isEntry, type Trade } from "@/lib/trades"
import { useLive } from "@/stores/live"

// force entry: a new trade, or (with trade) an add to an open one where nfi bots get a grind level picker
const props = defineProps<{ bot?: string | null; pair?: string; trade?: Trade | null }>()
const emit = defineEmits<{ done: [string]; cancel: [] }>()
const live = useLive()

const tradeBots = computed(() => Object.values(live.bots).filter((bot) => bot.trading && bot.connected).map((bot) => bot.name))
const botName = ref(props.bot ?? tradeBots.value[0] ?? "")
const { canShort, futures, isLive } = useTradeAccess(botName)
const botState = computed(() => live.bots[botName.value])
const isNfi = computed(() => !!botState.value?.is_nfi)
const adding = computed(() => !!props.trade)

const pair = ref(props.trade?.pair ?? props.pair ?? "")
const side = ref<"long" | "short">(props.trade?.is_short ? "short" : "long")
const tag = ref("force_entry")
const stake = ref<number | null>(null)
const leverage = ref<number | null>(null)
const ordertype = ref<"" | "market" | "limit">("")
const price = ref<number | null>(null)
const now = ref<number | null>(null)  // live exchange price, from the price box
const step = ref<"form" | "check">("form")
watch(canShort, (allowed) => { if (!allowed && !adding.value) side.value = "long" })

const whitelist = computed(() => (botState.value?.whitelist?.whitelist ?? []) as string[])
const tags = computed(() => addTags(side.value === "short", isNfi.value))
const orderDefault = computed(() => botState.value?.config?.order_types?.force_entry ?? botState.value?.config?.order_types?.entry ?? "bot default")
const lev = computed(() => leverage.value ?? props.trade?.leverage ?? null)
// first entry's own stake, a guide for grind sizes (nfi sizes grinds off it)
const firstStake = computed(() => {
  const trade = props.trade
  const firstEntry = trade ? filledOrders(trade).find((order) => isEntry(trade, order)) : null
  return firstEntry ? (firstEntry.stake_amount ?? (firstEntry.cost ?? 0) / (trade?.leverage || 1)) : null
})

const coin = computed(() => pair.value.split("/")[0])
const level = computed(() => tags.value.find(([key]) => key === tag.value)?.[1] ?? tag.value)
const lines = computed(() => [
  `${adding.value ? "add to" : "open"} ${side.value} ${pair.value} on ${botName.value}`,
  `tag ${tag.value}${adding.value && isNfi.value ? ` (${level.value})` : ""}`,
  `stake ${stake.value ? money(stake.value) : "bot default"}${stake.value && lev.value ? ` × ${lev.value}x = ${money(stake.value * lev.value)} position` : ""}`,
  `order ${ordertype.value || `${orderDefault.value} (bot default)`}${price.value ? ` at ${price.value}` : ""}${now.value ? ` · now ${+now.value.toPrecision(6)}` : ""}`,
  ...(stake.value && (price.value || now.value) ? [`about ${+((stake.value * (lev.value || 1)) / (price.value || now.value!)).toPrecision(6)} ${coin.value}`] : []),
])
const warn = computed(() => {
  if (adding.value && isNfi.value && tag.value !== "force_entry")
    return `NFI counts this as ${level.value}: it uses one of that level's entries and NFI sells it at that level's target.`
  if (!adding.value && isNfi.value && tag.value === "force_entry")
    return "force_entry skips all of NFI's entry checks. An NFI tag number instead goes through its checks and runs in that mode."
  return ""
})
// adds need a stake: left blank, freqtrade would add a whole new trade's stake
const ready = computed(() => !!botName.value && pair.value.includes("/") && (adding.value ? (stake.value ?? 0) > 0 : stake.value == null || stake.value > 0))

async function send(confirm: string) {
  const body = {
    pair: pair.value, side: side.value, entry_tag: tag.value.trim() || "force_entry", confirm,
    stakeamount: stake.value || null, leverage: adding.value ? null : leverage.value || null,
    ordertype: ordertype.value || null, price: price.value || null,
  }
  const result = await tradeAction(botName.value, "enter", body)
  if (result.ok) emit("done", `${adding.value ? "add" : "entry"} sent for ${pair.value}; the bot shows it within a few seconds`)
  return result
}
const inp = "mt-1 w-full rounded-md bg-raised border border-line px-2 py-1.5 text-ink num"
</script>

<template>
  <div class="space-y-3 text-sm">
    <div v-if="!adding" class="text-lg font-semibold">New entry</div>
    <p v-if="!tradeBots.length" class="text-warn">No bot allows trade actions. Turn trading on for a bot in Manage Bots (write_actions must be on in config.yaml).</p>
    <template v-else-if="step === 'form'">
      <div class="grid gap-3 sm:grid-cols-2">
        <label v-if="!adding && !bot" class="text-dim">Bot
          <select v-model="botName" :class="inp"><option v-for="name in tradeBots" :key="name">{{ name }}</option></select></label>
        <label v-if="!adding" class="text-dim">Pair
          <input v-model.trim="pair" list="entry-pairs" :class="inp" placeholder="BTC/USDT:USDT" autocomplete="off" />
          <datalist id="entry-pairs"><option v-for="pairName in whitelist" :key="pairName" :value="pairName" /></datalist></label>
        <div v-if="!adding" class="text-dim">Side
          <div class="mt-1 flex rounded-md border border-line overflow-hidden w-fit">
            <button type="button" class="px-4 py-1.5" :class="side === 'long' ? 'bg-[var(--green-dim)] text-up' : 'text-dim'" @click="side = 'long'">▲ long</button>
            <button type="button" class="px-4 py-1.5 disabled:opacity-40" :class="side === 'short' ? 'bg-[var(--red-dim)] text-down' : 'text-dim'" :disabled="!canShort" :title="canShort ? '' : 'this bot does not short'" @click="side = 'short'">▼ short</button>
          </div></div>
        <label class="text-dim">{{ adding ? "Add as" : "Entry tag" }}
          <select v-if="adding" v-model="tag" :class="inp"><option v-for="[value, label] in tags" :key="value" :value="value">{{ label }}{{ value === "force_entry" ? "" : ` · ${value}` }}</option></select>
          <input v-else v-model="tag" :class="inp" maxlength="64" /></label>
        <label class="text-dim">Stake <span class="text-faint">{{ botState?.config?.stake_currency }}</span>
          <input v-model.number="stake" type="number" min="0" step="any" :class="inp" :placeholder="adding ? 'needed for an add' : 'bot default'" :required="adding" />
          <span v-if="adding && firstStake" class="text-xs text-faint">first entry stake {{ money(firstStake) }} · trade now {{ money(trade?.stake_amount) }}</span></label>
        <label v-if="!adding && futures" class="text-dim">Leverage
          <input v-model.number="leverage" type="number" min="1" step="any" :class="inp" placeholder="strategy default" /></label>
        <label class="text-dim">Order type
          <select v-model="ordertype" :class="inp"><option value="">bot default ({{ orderDefault }})</option><option value="market">market</option><option value="limit">limit</option></select></label>
        <PriceBox v-model="price" v-model:now="now" :bot="botName" :pair="pair" :buying="side === 'long'" />
      </div>
      <div class="flex gap-2">
        <button class="px-3 py-1 rounded-md bg-brand-b/20 border border-brand-b/50 text-ink disabled:opacity-40" :disabled="!ready" @click="step = 'check'">review</button>
        <button class="px-3 py-1 text-dim hover:text-ink" @click="emit('cancel')">cancel</button>
        <span v-if="isLive" class="text-xs text-down self-center">live bot: real money</span>
      </div>
    </template>
    <ConfirmStep v-else :lines="lines" :live="isLive" :coin="coin" :warn="warn" :send="send" @cancel="step = 'form'" />
  </div>
</template>
