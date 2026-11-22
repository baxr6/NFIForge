import { computed, inject, onBeforeUnmount, onMounted, provide, ref, watch, type InjectionKey, type Ref } from "vue"
import { age, wilson } from "@/lib/format"
import { useLive } from "@/stores/live"
import { useSettings } from "@/stores/settings"

// everything the trading panels show, computed once per page and shared through provide/inject

export function createTradingData(picked: Ref<string | null>) {
  const live = useLive()
  const settings = useSettings()
  const now = ref(Date.now() / 1000)

  const bot = computed(() => (picked.value ? live.bots[picked.value] : null))
  const utc = computed(() => settings.s?.timezone !== "local")
  const host = computed(() => live.host)
  const events = computed(() => live.events[picked.value ?? ""] ?? [])

  // ===========================================================================
  // POSITIONS + MONEY
  // ===========================================================================
  const open = computed<Record<string, any>[]>(() => bot.value?.status ?? [])
  const maxSlots = computed(() => Math.max(Number(bot.value?.config?.max_open_trades) || 0, 0) || open.value.length)
  const wallet = computed<number | null>(() => walletOf(bot.value?.balance))
  const start = computed<number | null>(() => startOf(bot.value))
  const openPnl = computed(() => open.value.reduce((sum, trade) => sum + (trade.profit_abs ?? 0), 0))
  const equity = computed(() => (wallet.value == null ? null : wallet.value + openPnl.value))
  const stakeIn = computed(() => open.value.reduce((sum, trade) => sum + (trade.stake_amount ?? 0), 0))
  const notional = computed(() => open.value.reduce((sum, trade) => sum + (trade.stake_amount ?? 0) * (trade.leverage ?? 1), 0))
  const stakeUsed = computed(() => (wallet.value ? (stakeIn.value / wallet.value) * 100 : 0))
  const slotsUsed = computed(() => (maxSlots.value ? (open.value.length / maxSlots.value) * 100 : 0))
  const profit = computed<Record<string, any>>(() => bot.value?.profit ?? {})
  const drawdown = computed(() => (profit.value.current_drawdown ?? 0) * 100)
  const liqNearest = computed(() => {
    const distances = open.value
      .filter((trade) => trade.liquidation_price && trade.current_rate)
      .map((trade) => ({ pair: trade.pair.split("/")[0], dist: (Math.abs(trade.current_rate - trade.liquidation_price) / trade.current_rate) * 100 }))
    return distances.sort((left, right) => left.dist - right.dist)[0] ?? null
  })
  const wins = computed(() => profit.value.winning_trades ?? 0)
  const losses = computed(() => profit.value.losing_trades ?? 0)
  const ci = computed(() => wilson(wins.value, wins.value + losses.value))
  const quote = computed(() => bot.value?.config?.stake_currency ?? "")

  // ===========================================================================
  // TODAY
  // ===========================================================================
  const dayStart = computed(() => {
    const date = new Date(now.value * 1000)
    const startMs = utc.value ? Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()) : new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
    return startMs / 1000
  })
  const todayCloses = computed(() =>
    ((bot.value?.trades?.trades ?? []) as Record<string, any>[])
      .filter((trade) => !trade.is_open && trade.close_timestamp && trade.close_timestamp / 1000 >= dayStart.value)
      .sort((left, right) => left.close_timestamp - right.close_timestamp),
  )
  const todayRealised = computed(() => todayCloses.value.reduce((sum, trade) => sum + (trade.close_profit_abs ?? 0), 0))

  // equity snapshots from the backend, one a minute
  const eqHist = ref<{ time: number; value: number }[]>([])
  const eqOpen = ref<{ time: number; open: number }[]>([])
  async function loadEquity() {
    if (!picked.value) return
    const response = await fetch(`/api/bots/${encodeURIComponent(picked.value)}/equity?hours=24`)
    if (!response.ok) return
    const rows = await response.json()
    eqHist.value = rows.map((point: any) => ({ time: Math.floor(point.ts), value: +point.equity.toFixed(2) }))
    eqOpen.value = rows.map((point: any) => ({ time: point.ts, open: point.open_pnl }))
  }
  watch(picked, loadEquity)

  // regular 5 min grid (lightweight-charts spaces points by index, so gaps must be filled):
  // realised so far + open p&l from the minute snapshots; the live bucket uses the current open p&l
  const STEP = 300
  const todaySeries = computed(() => {
    const start = Math.floor(dayStart.value / STEP) * STEP
    const end = Math.floor(now.value / STEP) * STEP
    const closes = todayCloses.value
    const snaps = eqOpen.value
    const pts: { time: number; value: number }[] = []
    let closeIndex = 0, snapIndex = 0, run = 0, open = 0
    for (let time = start; time <= end; time += STEP) {
      while (closeIndex < closes.length && closes[closeIndex].close_timestamp / 1000 < time + STEP) run += closes[closeIndex++].close_profit_abs ?? 0
      while (snapIndex < snaps.length && snaps[snapIndex].time < time + STEP) open = snaps[snapIndex++].open
      pts.push({ time: time, value: +(run + (time === end ? openPnl.value : open)).toFixed(4) })
    }
    return pts
  })

  // ===========================================================================
  // STATUS STRIP
  // ===========================================================================
  type Level = "ok" | "warn" | "bad"
  const lastLoopAge = computed(() => (bot.value?.health?.last_process_ts ? now.value - bot.value.health.last_process_ts : null))
  const loopAgo = computed(() => (lastLoopAge.value != null ? age(now.value - lastLoopAge.value, now.value) : undefined))
  const lastCandle = computed(() => {
    const candleEvents = events.value.filter((event) => event.type === "new_candle")
    return candleEvents.length ? candleEvents[candleEvents.length - 1].ts : null
  })
  const botCard = computed(() => {
    const state = bot.value?.config?.state ?? "unknown"
    const stale = lastLoopAge.value != null && lastLoopAge.value > 60
    // slots used: open trades / max_open_trades (-1 or unset = no limit, count only)
    const max = Number(bot.value?.config?.max_open_trades)
    const slots = max > 0 ? `${open.value.length}/${max}` : `${open.value.length} open`
    return {
      value: !bot.value?.connected ? "Disconnected" : `${state === "running" ? "Running" : state} · ${slots}`,
      detail: loopAgo.value ? `last loop ${loopAgo.value} ago${bot.value?.loop_s ? ` · ${bot.value.loop_s.toFixed(1)}s` : ""}` : bot.value?.error,
      sub: bot.value?.container,
      level: (!bot.value?.connected ? "bad" : stale ? "warn" : "ok") as Level,
    }
  })
  const apiLevel = computed<Level>(() => {
    const gauge = settings.gauge("exchange_ms"), latency = bot.value?.latency_ms ?? 0
    return gauge.danger && latency > gauge.danger ? "bad" : gauge.warn && latency > gauge.warn ? "warn" : "ok"
  })
  const serverLevel = computed<Level>(() => {
    const hostStats = host.value, cpuGauge = settings.gauge("cpu"), ramGauge = settings.gauge("ram")
    if ((cpuGauge.danger && hostStats.cpu > cpuGauge.danger) || (ramGauge.danger && hostStats.ram > ramGauge.danger)) return "bad"
    if ((cpuGauge.warn && hostStats.cpu > cpuGauge.warn) || (ramGauge.warn && hostStats.ram > ramGauge.warn)) return "warn"
    return "ok"
  })
  const riskLevel = computed<Level>(() => {
    const liqDistance = liqNearest.value?.dist, liqGauge = settings.gauge("liq_distance"), drawdownGauge = settings.gauge("drawdown")
    if ((liqDistance != null && liqGauge.danger != null && liqDistance < liqGauge.danger) || (drawdownGauge.danger && drawdown.value > drawdownGauge.danger)) return "bad"
    if ((liqDistance != null && liqGauge.warn != null && liqDistance < liqGauge.warn) || (drawdownGauge.warn && drawdown.value > drawdownGauge.warn)) return "warn"
    return "ok"
  })

  const pulse = computed(() => bot.value?.pulse ?? null)
  const btcCandles = computed(() =>
    (pulse.value?.candles ?? []).map((candle: number[]) => ({ time: Math.floor(candle[0] / 1000), open: candle[1], high: candle[2], low: candle[3], close: candle[4], volume: candle[5] ?? 0 })),
  )

  let clock = 0, eqTimer = 0
  onMounted(() => {
    clock = window.setInterval(() => (now.value = Date.now() / 1000), 1000)
    loadEquity()
    eqTimer = window.setInterval(loadEquity, 60000)
  })
  onBeforeUnmount(() => { clearInterval(clock); clearInterval(eqTimer) })

  return {
    picked, bot, utc, host, events, now, open, maxSlots, wallet, start, openPnl, equity, stakeIn, notional, stakeUsed, slotsUsed,
    profit, drawdown, liqNearest, wins, losses, ci, quote, dayStart, todayCloses, todayRealised, todaySeries, eqHist,
    lastLoopAge, loopAgo, lastCandle, botCard, apiLevel, serverLevel, riskLevel, pulse, btcCandles,
  }
}

export type TradingData = ReturnType<typeof createTradingData>
const KEY: InjectionKey<TradingData> = Symbol("trading")

export function provideTrading(picked: Ref<string | null>) {
  const data = createTradingData(picked)
  provide(KEY, data)
  return data
}

export function useTrading(): TradingData {
  const data = inject(KEY)
  if (!data) throw new Error("trading data not provided (App.vue provides it)")
  return data
}

// the stake coin's own wallet balance, without open p&l (freqtrade's "total" adds the positions' collateral, which on
// live futures already holds their unrealised p&l, so wallet + open p&l from it counted the open loss twice)
export function walletOf(bal: Record<string, any> | null | undefined): number | null {
  if (!bal) return null
  const currency = (bal.currencies ?? []).find((entry: Record<string, any>) => entry.currency === bal.stake && !entry.is_position)
  return currency?.balance ?? bal.total ?? null
}

// what the bot started with: wallet minus closed profit minus the partial-exit profit of open trades. freqtrade's
// starting_capital leaves that last part out, so grind and de-risk sells on open trades moved its start
export function startOf(bot: Record<string, any> | null | undefined): number | null {
  const wallet = walletOf(bot?.balance)
  const closed = bot?.profit?.profit_closed_coin
  if (wallet == null || closed == null) return bot?.balance?.starting_capital ?? null
  return wallet - closed - ((bot?.status ?? []) as Record<string, any>[]).reduce((sum, trade) => sum + (trade.realized_profit ?? 0), 0)
}
