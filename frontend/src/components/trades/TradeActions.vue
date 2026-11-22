<script setup lang="ts">
import { computed, ref, toRef } from "vue"
import ConfirmStep from "@/components/trades/ConfirmStep.vue"
import EntryForm from "@/components/trades/EntryForm.vue"
import PriceBox from "@/components/trades/PriceBox.vue"
import { money } from "@/lib/format"
import { tradeAction, useTradeAccess } from "@/lib/tradeActions"
import { filledOrders, type Trade } from "@/lib/trades"
import { useLive } from "@/stores/live"

// buttons on an open trade: add, exit (full or part), cancel order, reload, delete; each ends in the confirm step
const props = defineProps<{ trade: Trade; bot: string }>()
const live = useLive()
const { isLive, canAdd } = useTradeAccess(toRef(props, "bot"))
const isNfi = computed(() => !!live.bots[props.bot]?.is_nfi)
type Pick = "" | "add" | "exit" | "cancel" | "reload" | "delete"
const pick = ref<Pick>("")
const sent = ref("")
const shownTrade = computed(() => props.trade)
const coin = computed(() => shownTrade.value.pair.split("/")[0])

// exit: part as % of the coins held
const part = ref(100)
const ordertype = ref<"" | "market" | "limit">("")
const price = ref<number | null>(null)
const now = ref<number | null>(null)  // live exchange price, from the price box
const exitStep = ref<"form" | "check">("form")
const amount = computed(() => (shownTrade.value.amount ?? 0) * Math.min(part.value, 100) / 100)
const orderDefault = computed(() => live.bots[props.bot]?.config?.order_types?.force_exit ?? live.bots[props.bot]?.config?.order_types?.exit ?? "bot default")
// nfi v4 grind levels with an open entry: a manual part exit isn't counted against them
const grindOpen = computed(() => isNfi.value && filledOrders(shownTrade.value).some((order) => /^(grind_\d|buyback_1|rebuy)_entry$/.test(order.ft_order_tag ?? "")))

function choose(option: Pick) { pick.value = pick.value === option ? "" : option; sent.value = ""; exitStep.value = "form"; part.value = 100; price.value = null; ordertype.value = "" }
function done(msg: string) { pick.value = ""; sent.value = msg }

const exitLines = computed(() => [
  part.value >= 100 ? `exit all of ${shownTrade.value.pair} (#${shownTrade.value.trade_id})` : `exit ${part.value}% of ${shownTrade.value.pair}: ${+amount.value.toPrecision(6)} of ${+(shownTrade.value.amount ?? 0).toPrecision(6)} ${coin.value}`,
  `worth about ${money(amount.value * (now.value ?? shownTrade.value.current_rate ?? 0))} at ${+(now.value ?? shownTrade.value.current_rate ?? 0).toPrecision(6)}`,
  `order ${ordertype.value || `${orderDefault.value} (bot default)`}${price.value ? ` at ${price.value}` : ""}`,
])
const exitWarn = computed(() => (part.value < 100 && grindOpen.value
  ? "NFI won't count this as a grind exit: an open grind level may still be sold again later at its own target."
  : ""))
async function sendExit(confirm: string) {
  const body = { tradeid: shownTrade.value.trade_id, confirm, amount: part.value < 100 ? amount.value : null, ordertype: ordertype.value || null, price: price.value || null }
  const result = await tradeAction(props.bot, "exit", body)
  if (result.ok) done(`exit sent for ${shownTrade.value.pair}`)
  return result
}

const SIMPLE: Record<"cancel" | "reload" | "delete", { lines: string[]; warn: string }> = {
  cancel: { lines: ["cancel the open order"], warn: "" },
  reload: { lines: ["reload this trade's orders from the exchange"], warn: "" },
  delete: { lines: ["delete this trade from the bot's database"], warn: "The position stays open on the exchange; the bot stops managing it." },
}
const simple = computed(() => SIMPLE[pick.value as keyof typeof SIMPLE])
async function sendSimple(confirm: string) {
  const what = pick.value as "cancel" | "reload" | "delete"
  const result = await tradeAction(props.bot, what, { tradeid: shownTrade.value.trade_id, confirm })
  if (result.ok) done(`${what} sent for ${shownTrade.value.pair}`)
  return result
}
const btn = "text-xs px-2.5 py-1 rounded-md border"
const inp = "mt-1 w-full rounded-md bg-raised border border-line px-2 py-1.5 text-ink num"
</script>

<template>
  <div class="panel p-3 space-y-3">
    <div class="flex flex-wrap items-center gap-2">
      <span class="panel-title mr-1">Actions</span>
      <button v-if="canAdd" :class="[btn, pick === 'add' ? 'border-brand-b text-ink' : 'border-line text-dim hover:text-ink']" @click="choose('add')">+ add</button>
      <button :class="[btn, pick === 'exit' ? 'border-warn text-ink' : 'border-line text-dim hover:text-ink']" @click="choose('exit')">exit</button>
      <button v-if="shownTrade.has_open_orders" :class="[btn, pick === 'cancel' ? 'border-brand-b text-ink' : 'border-line text-dim hover:text-ink']" @click="choose('cancel')">cancel order</button>
      <button :class="[btn, pick === 'reload' ? 'border-brand-b text-ink' : 'border-line text-dim hover:text-ink']" @click="choose('reload')">reload</button>
      <button :class="[btn, pick === 'delete' ? 'border-down text-down' : 'border-line text-dim hover:text-down']" @click="choose('delete')">delete</button>
      <span v-if="isLive" class="text-xs text-down">live bot</span>
      <span v-if="sent" class="text-xs text-up">✓ {{ sent }}</span>
    </div>

    <EntryForm v-if="pick === 'add'" :bot="bot" :trade="trade" @done="done" @cancel="pick = ''" />

    <template v-else-if="pick === 'exit'">
      <div v-if="exitStep === 'form'" class="space-y-3 text-sm">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-dim">how much</span>
          <button v-for="percent in [25, 50, 75, 100]" :key="percent" :class="[btn, part === percent ? 'border-brand-b text-ink' : 'border-line text-dim hover:text-ink']" @click="part = percent">{{ percent === 100 ? "all" : `${percent}%` }}</button>
          <input v-model.number="part" type="number" min="1" max="100" class="w-20 rounded-md bg-raised border border-line px-2 py-1 text-ink num" /><span class="text-dim">%</span>
        </div>
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="text-dim">Order type
            <select v-model="ordertype" :class="inp"><option value="">bot default ({{ orderDefault }})</option><option value="market">market</option><option value="limit">limit</option></select></label>
          <PriceBox v-model="price" v-model:now="now" :bot="bot" :pair="shownTrade.pair" :buying="!!shownTrade.is_short" />
        </div>
        <div class="flex gap-2">
          <button class="px-3 py-1 rounded-md bg-brand-b/20 border border-brand-b/50 text-ink disabled:opacity-40" :disabled="!(part > 0)" @click="exitStep = 'check'">review</button>
          <button class="px-3 py-1 text-dim hover:text-ink" @click="pick = ''">cancel</button>
        </div>
      </div>
      <ConfirmStep v-else :lines="exitLines" :live="isLive" :coin="coin" :warn="exitWarn" :send="sendExit" @cancel="exitStep = 'form'" />
    </template>

    <ConfirmStep v-else-if="pick" :lines="simple.lines" :live="isLive" :coin="coin" :warn="simple.warn" :send="sendSimple" @cancel="pick = ''" />
  </div>
</template>
