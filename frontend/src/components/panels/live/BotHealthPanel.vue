<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import BotControl from "@/components/trades/BotControl.vue"
import { useAuth } from "@/stores/auth"
import { useLive } from "@/stores/live"

// per bot: what it runs, how it's set up, and anything worth fixing (worst first)
const live = useLive()
const auth = useAuth()
type Check = { key: string; level: "ok" | "info" | "warn" | "bad"; title: string; detail: string }
type Report = { config: Record<string, any> | null; version: string | null; checks: Check[] }
const reports = ref<Record<string, Report>>({})
const error = ref<Record<string, string>>({})

async function load() {
  for (const name of Object.keys(live.bots)) {
    const response = await fetch(`/api/bots/${encodeURIComponent(name)}/checks`).catch(() => null)
    if (response?.ok) { reports.value[name] = await response.json(); delete error.value[name] }
    else error.value[name] = response ? response.statusText : "backend unreachable"
  }
}
watch(() => Object.keys(live.bots).join(), load, { immediate: true })
let timer = 0
onMounted(() => (timer = window.setInterval(load, 30000)))
onBeforeUnmount(() => clearInterval(timer))

const ORDER = { bad: 0, warn: 1, info: 2, ok: 3 }
const sorted = (checks: Check[]) => checks.slice().sort((a, b) => ORDER[a.level] - ORDER[b.level])
const count = (checks: Check[], level: Check["level"]) => checks.filter((check) => check.level === level).length
const ICON = { bad: "✕", warn: "!", info: "i", ok: "✓" }
const TONE = { bad: "text-down border-down/50 bg-down/10", warn: "text-warn border-warn/50 bg-warn/10", info: "text-brand-b border-brand-b/40 bg-brand-b/10", ok: "text-up border-up/40 bg-up/10" }

// settings worth seeing at a glance, in plain words
const onOff = (value: any) => (value == null ? "–" : value ? "on" : "off")
function settings(config: Record<string, any>): [string, string][] {
  const pct = (value: any) => (value == null ? "–" : `${(value * 100).toFixed(1)} %`)
  const roi = Object.entries<number>(config.minimal_roi ?? {}).map(([minutes, ratio]) => `${minutes}m ${pct(ratio)}`).join(" · ")
  const unfilled = config.unfilledtimeout
  return [
    ["Strategy", `${config.strategy ?? "–"} ${config.strategy_version ?? ""}`],
    ["Exchange", `${config.exchange ?? "–"} · ${config.trading_mode ?? ""}${config.margin_mode ? ` · ${config.margin_mode} margin` : ""}`],
    ["Mode", config.dry_run === false ? "real money" : config.dry_run ? "dry run" : "–"],
    ["Timeframe", config.timeframe ?? "–"],
    ["Stake", `${config.stake_amount ?? "–"} ${config.stake_amount === "unlimited" ? "" : config.stake_currency ?? ""}${config.available_capital ? ` · capital ${config.available_capital}` : ""}`],
    ["Max open trades", config.max_open_trades == null ? "–" : String(config.max_open_trades)],
    ["Shorts", onOff(config.short_allowed)],
    ["Stoploss", `${pct(config.stoploss)} · on exchange ${onOff(config.stoploss_on_exchange)} · custom ${onOff(config.use_custom_stoploss)} · trailing ${onOff(config.trailing_stop)}`],
    ["ROI table", roi || "none (strategy exits)"],
    ["Position adjustment", `${onOff(config.position_adjustment_enable)}${config.position_adjustment_enable ? ` · max adds ${config.max_entry_position_adjustment === -1 ? "unlimited" : config.max_entry_position_adjustment}` : ""}`],
    ["Orders", config.order_types ? `entry ${config.order_types.entry} · exit ${config.order_types.exit} · stoploss ${config.order_types.stoploss}` : "–"],
    ["Unfilled timeout", unfilled ? `entry ${unfilled.entry} · exit ${unfilled.exit} ${unfilled.unit}` : "–"],
    ["Force entry", onOff(config.force_entry_enable)],
    ["Run mode", `${config.runmode ?? "–"} · ${config.state ?? ""}`],
  ]
}
const names = computed(() => Object.keys(live.bots))
</script>

<template>
  <div class="h-full overflow-auto space-y-4">
    <div class="flex items-baseline gap-3">
      <span class="text-sm text-dim">checked every 30 s</span>
      <button class="ml-auto text-xs px-3 py-1 rounded-md border border-line text-dim hover:text-ink" @click="load">↻</button>
    </div>

    <div v-for="name in names" :key="name" class="panel p-4 space-y-4">
      <template v-if="reports[name]">
        <div class="flex flex-wrap items-center gap-3">
          <span class="w-2.5 h-2.5 rounded-full" :class="live.bots[name]?.connected ? 'bg-up' : 'bg-down'" />
          <h2 class="text-lg font-semibold">{{ name }}</h2>
          <span v-if="reports[name].config?.dry_run === false" class="text-[11px] px-2 py-0.5 rounded border border-down/60 text-down">REAL MONEY</span>
          <span v-else-if="reports[name].config" class="text-[11px] px-2 py-0.5 rounded border border-line text-dim">DRY RUN</span>
          <span class="text-sm text-dim num">{{ reports[name].config?.strategy }} {{ reports[name].config?.strategy_version }} · freqtrade {{ reports[name].version }}</span>
          <span class="ml-auto flex gap-2 text-xs num">
            <span v-for="level in (['bad', 'warn', 'info'] as const)" v-show="count(reports[name].checks, level)" :key="level" class="px-2 py-0.5 rounded border" :class="TONE[level]">
              {{ count(reports[name].checks, level) }} {{ level === "bad" ? "to fix" : level === "warn" ? "to look at" : "notes" }}</span>
          </span>
        </div>

        <div v-if="auth.isAdmin && live.bots[name]?.trading && live.bots[name]?.connected" class="rounded-md border border-line p-3">
          <div class="panel-title mb-2">Bot control</div>
          <BotControl :bot="name" />
        </div>

        <div class="grid gap-4 xl:grid-cols-2">
          <ul class="space-y-1.5">
            <li v-for="check in sorted(reports[name].checks)" :key="check.key" class="flex gap-3 items-start">
              <span class="mt-0.5 w-5 h-5 shrink-0 grid place-items-center rounded-full border text-[11px] font-bold" :class="TONE[check.level]">{{ ICON[check.level] }}</span>
              <div class="min-w-0">
                <div class="text-sm" :class="check.level === 'ok' ? 'text-dim' : 'text-ink'">{{ check.title }}</div>
                <div v-if="check.detail" class="text-xs text-faint">{{ check.detail }}</div>
              </div>
            </li>
          </ul>
          <table v-if="reports[name].config" class="w-full text-sm self-start">
            <tbody>
              <tr v-for="[label, value] in settings(reports[name].config!)" :key="label" class="border-b border-line last:border-0">
                <td class="py-1.5 pr-4 text-dim whitespace-nowrap align-top">{{ label }}</td>
                <td class="py-1.5 num text-ink [overflow-wrap:anywhere]">{{ value }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
      <div v-else class="text-dim text-sm">{{ name }}: {{ error[name] ?? "loading…" }}</div>
    </div>
    <div v-if="!names.length" class="panel p-8 text-center text-dim">no bots configured</div>
  </div>
</template>
