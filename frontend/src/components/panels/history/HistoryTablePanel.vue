<script setup lang="ts">
import Drawer from "@/components/trades/Drawer.vue"
import TradeInspector from "@/components/trades/TradeInspector.vue"
import { money, pct, signed, tone } from "@/lib/format"
import { useHistoryPage } from "@/lib/state/history"
import { duration, exitGroup } from "@/lib/trades"

const { all, loading, opts, rows, page, pages, when, picked } = useHistoryPage()
</script>

<template>
  <div class="h-full flex flex-col gap-2 min-h-0">
    <!-- phones: one card per trade -->
    <div class="md:hidden flex flex-col gap-2">
      <button v-for="trade in rows" :key="`${trade._bot}-${trade.trade_id}`" class="panel p-3 text-left num active:bg-hover" @click="picked = trade">
        <div class="flex items-baseline gap-2">
          <span class="font-semibold text-ink">{{ trade.pair.split("/")[0] }}</span>
          <span :class="trade.is_short ? 'text-down' : 'text-up'">{{ trade.is_short ? "▼" : "▲" }}</span><span class="text-dim text-xs">{{ trade.leverage }}x</span>
          <span class="ml-auto text-lg font-semibold" :class="tone(trade.close_profit_abs)">{{ signed(trade.close_profit_abs) }}</span>
          <span class="text-sm w-16 text-right" :class="tone(trade.close_profit)">{{ pct((trade.close_profit ?? 0) * 100) }}</span>
        </div>
        <div class="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-dim">
          <span>{{ when(trade.close_timestamp) }}</span>
          <span v-if="opts.bots.length > 1">{{ trade._bot }}</span>
          <span>{{ trade.enter_tag }}</span>
          <span>{{ exitGroup(trade.exit_reason) }}</span>
          <span>held {{ duration(trade) }}</span>
          <span>stake {{ money(trade.stake_amount) }}</span>
        </div>
      </button>
      <div v-if="!rows.length" class="panel px-3 py-8 text-center text-dim">{{ loading ? "loading…" : "no trades match" }}</div>
    </div>

    <div class="panel overflow-auto flex-1 min-h-0 hidden md:block">
      <table class="w-full text-sm num">
        <thead class="text-xs text-dim text-left border-b border-line sticky top-0 bg-panel">
          <tr><th v-if="opts.bots.length > 1" class="px-3 py-2 font-normal">bot</th><th class="px-3 py-2 font-normal">closed</th><th class="px-3 py-2 font-normal">pair</th><th class="px-3 py-2 font-normal">side</th><th class="px-3 py-2 font-normal">tag</th><th class="px-3 py-2 font-normal">exit</th><th class="px-3 py-2 font-normal">held</th><th class="px-3 py-2 font-normal text-right">stake</th><th class="px-3 py-2 font-normal text-right">P&amp;L</th><th class="px-3 py-2 font-normal text-right">%</th></tr>
        </thead>
        <tbody>
          <tr v-for="trade in rows" :key="`${trade._bot}-${trade.trade_id}`" class="border-b border-line last:border-0 hover:bg-hover cursor-pointer" @click="picked = trade">
            <td v-if="opts.bots.length > 1" class="px-3 py-1.5 text-dim">{{ trade._bot }}</td>
            <td class="px-3 py-1.5 whitespace-nowrap text-dim">{{ when(trade.close_timestamp) }}</td>
            <td class="px-3 py-1.5 font-semibold">{{ trade.pair.split("/")[0] }}</td>
            <td class="px-3 py-1.5"><span :class="trade.is_short ? 'text-down' : 'text-up'">{{ trade.is_short ? "▼" : "▲" }}</span> <span class="text-dim">{{ trade.leverage }}x</span></td>
            <td class="px-3 py-1.5 text-dim">{{ trade.enter_tag }}</td>
            <td class="px-3 py-1.5 text-dim truncate max-w-64" :title="trade.exit_reason">{{ exitGroup(trade.exit_reason) }}</td>
            <td class="px-3 py-1.5">{{ duration(trade) }}</td>
            <td class="px-3 py-1.5 text-right">{{ money(trade.stake_amount) }}</td>
            <td class="px-3 py-1.5 text-right" :class="tone(trade.close_profit_abs)">{{ signed(trade.close_profit_abs) }}</td>
            <td class="px-3 py-1.5 text-right" :class="tone(trade.close_profit)">{{ pct((trade.close_profit ?? 0) * 100) }}</td>
          </tr>
          <tr v-if="!rows.length"><td colspan="10" class="px-3 py-8 text-center text-dim">{{ loading ? "loading…" : "no trades match" }}</td></tr>
        </tbody>
      </table>
    </div>
    <div v-if="pages > 1" class="flex items-center justify-center gap-3 text-sm shrink-0">
      <button class="px-3 py-2 md:py-1 rounded-md border border-line disabled:opacity-40" :disabled="page === 0" @click="page--">‹ newer</button>
      <span class="num text-dim">page {{ page + 1 }} / {{ pages }}</span>
      <button class="px-3 py-2 md:py-1 rounded-md border border-line disabled:opacity-40" :disabled="page >= pages - 1" @click="page++">older ›</button>
    </div>

    <Drawer v-if="picked" @close="picked = null">
      <TradeInspector :trade="picked" :bot="picked._bot" :is-nfi="picked._nfi" :history="all.filter((other) => other._bot === picked!._bot)" />
    </Drawer>
  </div>
</template>
