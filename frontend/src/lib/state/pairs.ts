import { computed, ref, watch } from "vue"
import { storeToRefs } from "pinia"
import { useHistory } from "@/lib/history"
import { once, sharedPoll } from "@/lib/shared"
import { age, signed } from "@/lib/format"
import type { Trade } from "@/lib/trades"
import { useLive } from "@/stores/live"
import { useSettings } from "@/stores/settings"

// the Pairs page's data, shared by its panels: whitelist, blacklist, locks, changes and filter reasons for the
// picked bot, plus "find a pair". refreshed every 30 s while any of its panels is on screen
const state = once(() => {
  const live = useLive()
  const settings = useSettings()
  const utc = computed(() => settings.s?.timezone !== "local")
  const { all: history } = useHistory()

  const botNames = computed(() => Object.keys(live.bots))
  const { picked: botName } = storeToRefs(live)
  const bot = computed(() => live.bots[botName.value ?? ""] ?? live.bots[botNames.value[0]])

  type Lock = { id: number; pair: string; side: string; reason: string; lock_end_timestamp: number }
  type Change = { ts: number; pair: string; change: "added" | "removed"; reason: string | null }
  type Filtered = { pair: string; ts: number; filter: string; reason: string }
  type Pairs = { whitelist: string[]; method: string[]; blacklist: string[]; blacklist_expanded: string[]; locks: Lock[]; changes: Change[]; filtered: Filtered[] }
  const data = ref<Pairs | null>(null)
  const logWarning = ref("")

  async function load() {
    if (!bot.value) return
    const encodedName = encodeURIComponent(bot.value.name)
    const [pairsResponse, logsResponse] = await Promise.all([fetch(`/api/bots/${encodedName}/pairs`).catch(() => null), fetch(`/api/bots/${encodedName}/logs?limit=1`).catch(() => null)])
    if (pairsResponse?.ok) data.value = await pairsResponse.json()
    if (logsResponse?.ok) logWarning.value = (await logsResponse.json()).warning ?? ""
  }
  watch(() => bot.value?.name, load, { immediate: true })

  // ===========================================================================
  // WHAT WE KNOW PER PAIR
  // ===========================================================================
  const open = computed(() => new Map(((bot.value?.status ?? []) as Trade[]).map((trade) => [trade.pair, trade])))
  const locks = computed(() => new Map((data.value?.locks ?? []).map((lock) => [lock.pair, lock])))
  const filtered = computed(() => new Map((data.value?.filtered ?? []).map((record) => [record.pair, record])))
  const patterns = computed(() => (data.value?.blacklist ?? []).map((pattern) => { try { return { p: pattern, re: new RegExp(`^${pattern}$`) } } catch { return { p: pattern, re: null } } }))
  const blockedBy = (pair: string) => patterns.value.find((entry) => entry.re?.test(pair))?.p ?? (data.value?.blacklist_expanded.includes(pair) ? "(expanded list)" : null)
  const past = computed(() => {
    const byPair = new Map<string, { n: number; total: number; last: number }>()
    for (const trade of history.value) {
      if (trade._bot !== bot.value?.name) continue
      const stats = byPair.get(trade.pair) ?? { n: 0, total: 0, last: 0 }
      stats.n++; stats.total += trade.close_profit_abs ?? 0; stats.last = Math.max(stats.last, trade.close_timestamp ?? 0)
      byPair.set(trade.pair, stats)
    }
    return byPair
  })

  type Status = { tone: string; text: string }
  function statusOf(pair: string): Status[] {
    const out: Status[] = []
    const trade = open.value.get(pair)
    if (trade) out.push({ tone: "up", text: `in a ${trade.is_short ? "short" : "long"} trade ${signed((trade.profit_ratio ?? 0) * 100, 1)}%` })
    const inWl = data.value?.whitelist.includes(pair)
    if (inWl) out.push({ tone: "ink", text: "on the whitelist" })
    const lock = locks.value.get(pair)
    if (lock) out.push({ tone: "warn", text: `locked ${lock.side !== "*" ? `(${lock.side}) ` : ""}for ${age(Date.now() / 1000, lock.lock_end_timestamp / 1000)}: ${lock.reason || "no reason given"}` })
    const pattern = blockedBy(pair)
    if (pattern) out.push({ tone: "down", text: `blacklisted by ${pattern}` })
    const record = filtered.value.get(pair)
    if (record && !inWl) out.push({ tone: "dim", text: `filtered out by ${record.filter} ${age(record.ts)} ago: ${record.reason}` })
    if (!out.length) out.push({ tone: "faint", text: "not seen: not in the volume list, or dropped before any filter logged it" })
    return out
  }

  // ===========================================================================
  // FIND A PAIR
  // ===========================================================================
  const q = ref("")
  const known = computed(() => {
    const lists = data.value
    return [...new Set([...(lists?.whitelist ?? []), ...(lists?.blacklist_expanded ?? []), ...filtered.value.keys(), ...past.value.keys(), ...open.value.keys(), ...locks.value.keys()])]
  })
  // a typed coin as the bot's pair name ("sol" -> SOL/USDT:USDT on futures); a full pair or "*" stays as typed
  const pairFor = (typed: string) => {
    const coin = typed.trim().toUpperCase()
    if (!coin || coin === "*" || coin.includes("/")) return coin
    const quote = bot.value?.config?.stake_currency ?? "USDT"
    return known.value.find((pair) => pair.split("/")[0] === coin) ?? (bot.value?.config?.trading_mode === "futures" ? `${coin}/${quote}:${quote}` : `${coin}/${quote}`)
  }
  const found = computed(() => {
    const search = q.value.trim().toUpperCase()
    if (!search) return []
    const hits = known.value.filter((pair) => pair.split("/")[0] === search || pair.toUpperCase().startsWith(search))
    return (hits.length ? hits : [pairFor(search)]).slice(0, 8)
  })

  // ===========================================================================
  // WHITELIST TABLE
  // ===========================================================================
  const wl = computed(() => (data.value?.whitelist ?? []).map((pair) => ({ pair, open: open.value.get(pair), lock: locks.value.get(pair), past: past.value.get(pair) }))
    .sort((a, b) => Number(!!b.open) - Number(!!a.open) || Number(!!b.lock) - Number(!!a.lock) || (b.past?.n ?? 0) - (a.past?.n ?? 0) || a.pair.localeCompare(b.pair)))
  const base = (pair: string) => pair.split("/")[0]
  const when = (ts: number) => new Date(ts * 1000).toLocaleString("en-GB", { timeZone: utc.value ? "UTC" : undefined, hour12: false, dateStyle: "short", timeStyle: "short" })
  const blCount = (pattern: string) => { try { const regex = new RegExp(`^${pattern}$`); return (data.value?.blacklist_expanded ?? []).filter((pair) => regex.test(pair)).length } catch { return 0 } }
  const TONES: Record<string, string> = { up: "text-up", ink: "text-ink", warn: "text-warn", down: "text-down", dim: "text-dim", faint: "text-faint" }
  return { live, settings, utc, history, botNames, botName, bot, data, logWarning, load, open, locks, filtered, patterns, blockedBy, past, statusOf, q, known, found, pairFor, wl, base, when, blCount, TONES }
})

const poll = once(() => sharedPoll(() => state().load(), 30000))

export function usePairs() {
  poll()()
  return state()
}
