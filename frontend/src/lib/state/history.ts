import { computed, ref, watch } from "vue"
import { useHistory, type Row } from "@/lib/history"
import { once } from "@/lib/shared"
import { exitGroup } from "@/lib/trades"
import { useSettings } from "@/stores/settings"

// the Trade History page's data, shared by its panels: every closed trade, the header's filters, the summary,
// paging and the trade open in the inspector
export const useHistoryPage = once(() => {
  const settings = useSettings()
  const utc = computed(() => settings.s?.timezone !== "local")
  const { all, loading, load } = useHistory()

  // ===========================================================================
  // FILTERS
  // ===========================================================================
  const f = ref({ bot: "", pair: "", tag: "", exit: "", result: "", side: "", from: "", to: "" })
  const opts = computed(() => ({
    bots: [...new Set(all.value.map((trade) => trade._bot))],
    tags: [...new Set(all.value.map((trade) => (trade.enter_tag ?? "").trim()).filter(Boolean))].sort((a, b) => Number(a) - Number(b) || a.localeCompare(b)),
    exits: [...new Set(all.value.map((trade) => exitGroup(trade.exit_reason)).filter(Boolean))].sort(),
  }))
  const shown = computed(() => {
    const filters = f.value
    const from = filters.from ? Date.parse(filters.from) : 0, to = filters.to ? Date.parse(filters.to) + 86400000 : Infinity
    return all.value.filter((trade) =>
      (!filters.bot || trade._bot === filters.bot) &&
      (!filters.pair || trade.pair.toLowerCase().includes(filters.pair.toLowerCase())) &&
      (!filters.tag || (trade.enter_tag ?? "").trim() === filters.tag) &&
      (!filters.exit || exitGroup(trade.exit_reason) === filters.exit) &&
      (!filters.side || (filters.side === "short") === !!trade.is_short) &&
      (!filters.result || (filters.result === "win" ? (trade.close_profit_abs ?? 0) > 0 : (trade.close_profit_abs ?? 0) <= 0)) &&
      (trade.close_timestamp ?? 0) >= from && (trade.close_timestamp ?? 0) < to)
  })
  const sum = computed(() => {
    const trades = shown.value, count = trades.length
    const wins = trades.filter((trade) => (trade.close_profit_abs ?? 0) > 0)
    const total = trades.reduce((sum, trade) => sum + (trade.close_profit_abs ?? 0), 0)
    const loss = trades.filter((trade) => (trade.close_profit_abs ?? 0) < 0).reduce((sum, trade) => sum + trade.close_profit_abs, 0)
    return { n: count, win: count ? (wins.length / count) * 100 : 0, total, avg: count ? total / count : 0, loss, worst: count ? Math.min(...trades.map((trade) => trade.close_profit_abs ?? 0)) : 0 }
  })
  function clear() { f.value = { bot: "", pair: "", tag: "", exit: "", result: "", side: "", from: "", to: "" } }

  // paging
  const PAGE = 50
  const page = ref(0)
  watch(f, () => (page.value = 0), { deep: true })
  const pages = computed(() => Math.max(1, Math.ceil(shown.value.length / PAGE)))
  const rows = computed(() => shown.value.slice(page.value * PAGE, (page.value + 1) * PAGE))
  const when = (ms?: number) => (ms ? new Date(ms).toLocaleString("en-GB", { timeZone: utc.value ? "UTC" : undefined, hour12: false, dateStyle: "short", timeStyle: "short" }) : "–")
  const picked = ref<Row | null>(null)
  return { settings, utc, all, loading, load, f, opts, shown, sum, clear, PAGE, page, pages, rows, when, picked }
})
