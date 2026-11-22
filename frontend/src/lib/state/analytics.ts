import { computed, ref } from "vue"
import { css, ecBase } from "@/components/charts/chartTheme"
import { byPeriod, curve, dayKey, groupOrder, groups, HOLDS, holdBucket, stats, type GroupBy, type Period } from "@/lib/analytics"
import { esc, signed } from "@/lib/format"
import { useHistory } from "@/lib/history"
import { once } from "@/lib/shared"
import { exitFamily } from "@/lib/trades"
import { startOf } from "@/lib/trading"
import { useLive } from "@/stores/live"
import { useSettings } from "@/stores/settings"

// the Analytics page's data, shared by its panels: closed trades, the filters from the page header, every
// chart option and the breakdown table. 95 % ranges so small samples show as small
export const useAnalytics = once(() => {
  const settings = useSettings()
  const live = useLive()
  const utc = computed(() => settings.s?.timezone !== "local")
  const { all, loading, load } = useHistory()

  // ===========================================================================
  // FILTERS
  // ===========================================================================
  const RANGES: [string, number][] = [["7d", 7], ["30d", 30], ["90d", 90], ["1y", 365], ["all", 0]]
  const f = ref({ bot: "", side: "", range: "all" })
  const bots = computed(() => [...new Set(all.value.map((trade) => trade._bot))])
  const shown = computed(() => {
    const days = RANGES.find(([key]) => key === f.value.range)?.[1] ?? 0
    const from = days ? Date.now() - days * 86400000 : 0
    return all.value.filter((trade) =>
      (!f.value.bot || trade._bot === f.value.bot) &&
      (!f.value.side || (f.value.side === "short") === !!trade.is_short) &&
      (trade.close_timestamp ?? 0) >= from)
  })
  // the picked bot's closed trades (all bots when none is picked): the "of" in the header
  const botAll = computed(() => (f.value.bot ? all.value.filter((trade) => trade._bot === f.value.bot) : all.value))
  const quote = computed(() => shown.value[0]?.quote_currency ?? "")

  // ===========================================================================
  // SUMMARY + CURVES
  // ===========================================================================
  const s = computed(() => stats(shown.value))
  // account size when the shown range starts: the bots' starting capital plus everything they closed before it
  const base = computed(() => {
    const picked = f.value.bot ? [f.value.bot] : bots.value
    const first = Math.min(...shown.value.map((trade) => trade.close_timestamp ?? Infinity))
    const cap = picked.reduce((sum, botName) => sum + (Number(startOf(live.bots[botName])) || 0), 0)
    const before = all.value.filter((trade) => picked.includes(trade._bot) && (trade.close_timestamp ?? 0) < first).reduce((sum, trade) => sum + (trade.close_profit_abs ?? 0), 0)
    return cap ? cap + before : 0
  })
  const c = computed(() => curve(shown.value, base.value))
  // funding paid (-) / received (+) on the shown trades; already inside their profit
  const funding = computed(() => {
    const fees = shown.value.map((trade) => trade.funding_fees ?? 0).filter((fee) => fee)
    return { total: fees.reduce((sum, fee) => sum + fee, 0), got: fees.filter((fee) => fee > 0).length, paid: fees.filter((fee) => fee < 0).length }
  })
  const pctRange = (range: [number, number] | null) => (range ? `${(range[0] * 100).toFixed(0)}–${(range[1] * 100).toFixed(0)}%` : "")
  const hold = (hours: number) => (hours < 48 ? `${hours.toFixed(1)}h` : `${(hours / 24).toFixed(1)}d`)

  // ===========================================================================
  // P&L OVER TIME
  // ===========================================================================
  const period = ref<Period>("day")
  const periodOption = computed(() => {
    const theme = ecBase(), rows = byPeriod(shown.value, period.value, utc.value)
    return {
      tooltip: { ...theme.tooltip, trigger: "axis", formatter: (params: any) => { const row = rows[params[0].dataIndex]; return `${esc(row.key)}<br/>${signed(row.total)} ${quote.value}<br/>${row.n} trades` } },
      grid: { left: 52, right: 10, top: 12, bottom: 26 },
      xAxis: { type: "category", data: rows.map((row) => row.key), ...theme.axis },
      yAxis: { type: "value", ...theme.valueAxis },
      series: [{ type: "bar", barMaxWidth: 18, data: rows.map((row) => ({ value: +row.total.toFixed(2), itemStyle: { color: row.total >= 0 ? css("--green") : css("--red"), borderRadius: [3, 3, 0, 0] } })) }],
    }
  })

  // daily calendar, last 12 months of what's shown
  const calendarOption = computed(() => {
    const theme = ecBase(), rows = byPeriod(shown.value, "day", utc.value)
    const end = rows.length ? rows[rows.length - 1].key : dayKey(Date.now(), utc.value)
    const yearBack = dayKey(Date.parse(end) - 364 * 86400000, true)
    const start = rows.length && rows[0].key > yearBack ? rows[0].key : yearBack
    const max = Math.max(1, ...rows.map((row) => Math.abs(row.total)))
    return {
      tooltip: { ...theme.tooltip, formatter: (params: any) => `${esc(params.value[0])}<br/>${signed(params.value[1])} ${quote.value}<br/>${params.value[2]} trades` },
      visualMap: { min: -max, max, show: false, dimension: 1, inRange: { color: theme.diverging } },
      calendar: { range: [start, end], cellSize: ["auto", 16], top: 22, bottom: 4, left: 34, right: 8,
        itemStyle: { color: css("--panel"), borderColor: css("--void"), borderWidth: 3 }, splitLine: { show: false },
        dayLabel: { firstDay: 1, color: css("--text-faint"), fontFamily: "IBM Plex Mono", fontSize: 10 },
        monthLabel: { color: css("--text-dim"), fontFamily: "IBM Plex Sans", fontSize: 11 }, yearLabel: { show: false } },
      series: [{ type: "heatmap", coordinateSystem: "calendar", data: rows.filter((row) => row.key >= start).map((row) => [row.key, +row.total.toFixed(2), row.n]), itemStyle: { borderRadius: 3 } }],
    }
  })

  // ===========================================================================
  // BREAKDOWN TABLE
  // ===========================================================================
  const GROUPS: [GroupBy, string][] = [["tag", "entry tag"], ["exit", "exit type"], ["exitDetail", "exit reason (full)"], ["pair", "pair"], ["side", "side"], ["weekday", "weekday opened"], ["hour", "hour opened"], ["hold", "time held"]]
  const by = ref<GroupBy>("tag")
  const sortKey = ref<"key" | "n" | "win" | "total" | "avg" | "pf" | "worst" | "holdH">("total")
  const desc = ref(true)
  function sortBy(key: typeof sortKey.value) { desc.value = sortKey.value === key ? !desc.value : key !== "key"; sortKey.value = key }
  const table = computed(() => {
    const rows = groups(shown.value, by.value, utc.value).map((group) => ({ ...group, win: group.n ? group.wins / group.n : 0 }))
    const natural = groupOrder(by.value)
    if (sortKey.value === "key" && natural) return desc.value ? rows.sort(natural).reverse() : rows.sort(natural)
    const key = sortKey.value
    return rows.sort((left, right) => {
      const leftValue = left[key] ?? -Infinity, rightValue = right[key] ?? -Infinity
      const order = typeof leftValue === "string" ? leftValue.localeCompare(rightValue as string, undefined, { numeric: true }) : (leftValue as number) - (rightValue as number)
      return desc.value ? -order : order
    })
  })
  const cols: [typeof sortKey.value, string][] = [["key", ""], ["n", "trades"], ["win", "won"], ["total", "total"], ["avg", "avg / trade"], ["pf", "profit factor"], ["worst", "worst"], ["holdH", "avg held"]]

  // ===========================================================================
  // TAG x EXIT + HOLD TIME
  // ===========================================================================
  const tagExitOption = computed(() => {
    const theme = ecBase()
    const tags = groups(shown.value, "tag", utc.value).sort((left, right) => right.n - left.n).slice(0, 14).map((group) => group.key).sort((left, right) => Number(left) - Number(right) || left.localeCompare(right))
    const top = groups(shown.value, "exit", utc.value).sort((left, right) => right.n - left.n).map((group) => group.key)
    const exits = top.length > 12 ? [...top.slice(0, 11), "other"] : top
    const exitOf = (trade: Record<string, any>) => { const family = exitFamily(trade.exit_reason) || "(none)"; return exits.includes(family) ? family : "other" }
    const cell = new Map<string, { total: number; n: number }>()
    for (const trade of shown.value) {
      const key = `${(trade.enter_tag ?? "").trim() || "(none)"}|${exitOf(trade)}`
      const entry = cell.get(key) ?? { total: 0, n: 0 }
      entry.total += trade.close_profit_abs ?? 0; entry.n++
      cell.set(key, entry)
    }
    const data: [number, number, number, number][] = []
    tags.forEach((tag, i) => exits.forEach((exit, j) => { const entry = cell.get(`${tag}|${exit}`); if (entry) data.push([j, i, +entry.total.toFixed(1), entry.n]) }))
    const max = Math.max(1, ...data.map((point) => Math.abs(point[2])))
    return {
      tooltip: { ...theme.tooltip, formatter: (params: any) => `tag ${esc(tags[params.value[1]])} · ${esc(exits[params.value[0]])}<br/>${signed(params.value[2])} ${quote.value}<br/>${params.value[3]} trades` },
      grid: { left: 48, right: 8, top: 8, bottom: 70 },
      xAxis: { type: "category", data: exits, ...theme.axis, axisLabel: { ...theme.axis.axisLabel, rotate: 35, fontFamily: "IBM Plex Sans" } },
      yAxis: { type: "category", data: tags, ...theme.axis },
      visualMap: { min: -max, max, show: false, dimension: 2, inRange: { color: theme.diverging } },
      series: [{ type: "heatmap", data, label: { show: true, color: css("--text"), fontFamily: "IBM Plex Mono", fontSize: 10, formatter: (params: any) => Math.round(params.value[2]) },
        itemStyle: { borderColor: css("--void"), borderWidth: 3, borderRadius: 4 } }],
    }
  })
  const tagExitHeight = computed(() => 90 + Math.min(14, new Set(shown.value.map((trade) => trade.enter_tag)).size) * 26)

  const holdOption = computed(() => {
    const theme = ecBase()
    const rows = HOLDS.map(([, label]) => ({ label, ...stats(shown.value.filter((trade) => holdBucket(trade) === label)) }))
    return {
      tooltip: { ...theme.tooltip, trigger: "axis", formatter: (params: any) => { const row = rows[params[0].dataIndex]; return `held ${esc(row.label)}<br/>${row.n} trades<br/>total ${signed(row.total)}<br/>avg ${signed(row.avg)}` } },
      grid: { left: 40, right: 8, top: 12, bottom: 26 },
      xAxis: { type: "category", data: rows.map((row) => row.label), ...theme.axis, axisLabel: { ...theme.axis.axisLabel, interval: 0 } },
      yAxis: { type: "value", minInterval: 1, ...theme.valueAxis },
      series: [{ type: "bar", barMaxWidth: 34, data: rows.map((row) => ({ value: row.n, itemStyle: { color: row.n === 0 ? css("--line") : row.avg >= 0 ? css("--green") : css("--red"), borderRadius: [3, 3, 0, 0] } })) }],
    }
  })
  return { utc, all, botAll, loading, load, RANGES, f, bots, shown, quote, s, c, base, funding, pctRange, hold, period, periodOption, calendarOption, GROUPS, by, sortKey, desc, sortBy, table, cols, tagExitOption, tagExitHeight, holdOption }
})
