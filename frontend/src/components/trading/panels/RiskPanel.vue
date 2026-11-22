<script setup lang="ts">
import { computed, reactive } from "vue"
import { money, signed, tone } from "@/lib/format"
import { shock } from "@/lib/risk"
import { useTrading } from "@/lib/trading"
import { useSettings } from "@/stores/settings"

// risk and exposure of the picked bot: margin used, real leverage on the account, trades near liquidation, and what
// the open book does if every coin moves the same % from here
const trading = reactive(useTrading())
const settings = useSettings()
const near = computed(() => settings.gauge("liq_distance").warn ?? 20)
const realLev = computed(() => (trading.equity ? trading.notional / trading.equity : null))
const nearLiq = computed(() =>
  trading.open.filter((trade) => trade.liquidation_price && trade.current_rate && (Math.abs(trade.current_rate - trade.liquidation_price) / trade.current_rate) * 100 < near.value),
)
const MOVES = [-0.3, -0.2, -0.1, -0.05, 0.05, 0.1, 0.2, 0.3]
const rows = computed(() => MOVES.map((move) => ({ m: move, ...shock(trading.open, move) })))
const ofEquity = (amount: number) => (trading.equity ? (amount / trading.equity) * 100 : null)
</script>

<template>
  <div class="panel p-3 h-full min-w-0 flex flex-col gap-2 overflow-auto">
    <div class="panel-title">Risk &amp; exposure</div>
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
      <div class="rounded-md bg-raised p-2"><div class="text-faint">margin used</div>
        <div class="num text-ink">{{ trading.stakeUsed.toFixed(1) }}% <span class="text-dim">{{ money(trading.stakeIn) }} {{ trading.quote }}</span></div></div>
      <div class="rounded-md bg-raised p-2" title="all open positions' size ÷ equity"><div class="text-faint">real leverage</div>
        <div class="num text-ink">{{ realLev == null ? "–" : `${realLev.toFixed(2)}x` }} <span class="text-dim">{{ money(trading.notional) }}</span></div></div>
      <div class="rounded-md bg-raised p-2"><div class="text-faint">within {{ near }}% of liq</div>
        <div class="num" :class="nearLiq.length ? 'text-down' : 'text-ink'">{{ nearLiq.length }} <span class="text-dim">of {{ trading.open.length }}</span></div></div>
      <div class="rounded-md bg-raised p-2"><div class="text-faint">nearest liq</div>
        <div class="num" :class="trading.liqNearest && trading.liqNearest.dist < near ? 'text-down' : 'text-ink'">{{ trading.liqNearest ? `${trading.liqNearest.dist.toFixed(1)}% ${trading.liqNearest.pair}` : "–" }}</div></div>
    </div>
    <table class="w-full text-xs num">
      <thead class="text-faint text-left"><tr><th class="font-normal pb-1">if every coin moves</th><th class="font-normal text-right">open P&amp;L change</th><th class="font-normal text-right">of equity</th><th class="font-normal pl-3">liquidated</th></tr></thead>
      <tbody>
        <tr v-for="row in rows" :key="row.m" class="border-t border-line">
          <td class="py-1" :class="row.m < 0 ? 'text-down' : 'text-up'">{{ row.m > 0 ? "+" : "" }}{{ (row.m * 100).toFixed(0) }}%</td>
          <td class="text-right" :class="tone(row.change)">{{ signed(row.change) }}</td>
          <td class="text-right" :class="tone(row.change)">{{ ofEquity(row.change) == null ? "–" : `${ofEquity(row.change)!.toFixed(1)}%` }}</td>
          <td class="pl-3" :class="row.liquidated.length ? 'text-down' : 'text-faint'">{{ row.liquidated.length ? row.liquidated.join(", ") : "none" }}</td>
        </tr>
      </tbody>
    </table>
    <div class="text-[11px] text-faint">Every coin moved by the same % from now; alts usually move more than that. Fees and funding left out.</div>
  </div>
</template>
