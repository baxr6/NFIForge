import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { features } from "@/lib/features"
import { useAuth } from "@/stores/auth"

// the BTCGate page only shows when btcgate.enabled is on in config.yaml, and to whoever may see it
export const btcgateOn = computed(() => features.btcgate && useAuth().can("btcgate"))

// label values from btcgate (README: turbulence 0/1/2, trend -1/0/1, lock kinds)
// -9 = not enough history yet (new coin, or direction without its coinalyze data)
export const TURB: Record<number, string> = { [-9]: "warming up", 0: "normal", 1: "elevated", 2: "HIGH" }
export const TREND: Record<number, string> = { [-9]: "warming up", [-1]: "bear", 0: "neutral", 1: "bull" }
export const DIRECTION: Record<number, string> = { [-9]: "warming up", [-1]: "down", 0: "flat", 1: "up" }
export const LOCK: Record<number, string> = { 1: "warning", 2: "monitoring tag", 3: "delisting", 4: "hack" }
export const label = (map: Record<number, string>, value: number | null | undefined) => (value == null || !(value in map) ? "–" : map[value])

// single-candle signals (fast_events layers)
export const SIGNAL: Record<string, { label: string; tone: string }> = {
  forced_dump: { label: "forced dump", tone: "text-up" }, forced_squeeze: { label: "forced squeeze", tone: "text-down" },
  fp_contested: { label: "contested spike", tone: "text-warn" }, dir_catchup: { label: "catch-up", tone: "text-up" },
  dir_catchup_base: { label: "catch-up (base)", tone: "text-up" }, warn_absorb: { label: "absorb warning", tone: "text-down" },
}
// coin scanner labels (btcgate scanner.ICON)
export const SCAN_LABEL: Record<string, { icon: string; text: string }> = {
  PUMP: { icon: "🚀", text: "pump" }, VOLATILE: { icon: "⚡", text: "volatile" }, SLOW_PUMP: { icon: "📈", text: "slow pump" },
  SLOW_BLEED: { icon: "📉", text: "slow bleed" }, APPROACHING: { icon: "👀", text: "approaching" },
}
export const scanText = (layer: string) => { const label = SCAN_LABEL[layer]; return label ? `${label.icon} ${label.text}` : layer }
export const sig = (layer: string) => SIGNAL[layer] ?? { label: layer, tone: "text-dim" }

// a coin as both exchanges name it: 1000PEPE on one is PEPE's 1000 lot, the same coin
// (the worker strips it in front or behind, SHIB1000 too)
export const coinOf = (pair: string) => { const base = pair.split("/")[0].toUpperCase(); return base.replace(/^1000+|1000+$/g, "") || base }

// btcgate's latest per coin for other pages (Positions badges): one shared poll while any of them is open
type Row = Record<string, any>
const byCoin = ref<Record<string, Row>>({})
const noData = ref<Set<string>>(new Set())  // bot coins binance has no perpetual for
const mode = ref("full")
const lastSig = ref<Record<string, { layer: string; ts: number }>>({})
let users = 0
let timer = 0
async function poll() {
  const [snapshot, events] = await Promise.all(["snapshot", "events"].map((path) => fetch(`/api/btcgate/${path}`).then((response) => (response.ok ? response.json() : null)).catch(() => null)))
  if (snapshot?.coins) byCoin.value = Object.fromEntries(Object.entries(snapshot.coins as Record<string, Row>).map(([pair, row]) => [coinOf(pair), row]))
  if (snapshot) { noData.value = new Set(snapshot.missing ?? []); mode.value = snapshot.mode ?? "full" }
  if (Array.isArray(events)) {
    const out: Record<string, { layer: string; ts: number }> = {}
    for (const event of events) out[coinOf(event.pair)] ??= { layer: event.layer, ts: Date.parse(event.date.replace(" ", "T")) / 1000 }  // newest first
    lastSig.value = out
  }
}
function sync() {
  const want = users > 0 && btcgateOn.value  // btcgateOn may arrive after the page mounted
  if (want && !timer) { poll(); timer = window.setInterval(poll, 60_000) }
  else if (!want && timer) { clearInterval(timer); timer = 0 }
}
watch(btcgateOn, sync)
export function useBtcgateCoins() {
  onMounted(() => { users++; sync() })
  onBeforeUnmount(() => { users--; sync() })
}

export type Badge = { text: string; tone: string; title: string }
// what btcgate says about a coin right now: lock, unlock soon, turbulence HIGH, big move risk, a signal in the last 24 h
export function badges(pair: string, now = Date.now() / 1000): Badge[] {
  const row = byCoin.value[coinOf(pair)]
  const out: Badge[] = []
  if (!row && noData.value.has(coinOf(pair)))
    out.push({ text: "no Binance data", tone: "text-faint border-line", title: "Binance has no perpetual for this coin, so BTCGate can't label it" })
  else if (!row && Object.keys(byCoin.value).length)
    out.push({ text: "not watched", tone: "text-faint border-line", title: mode.value === "bots"
      ? "not in the bots' whitelists yet (BTCGate picks them up within a minute)"
      : "not in BTCGate's coin list (about 150 by Binance volume); open trades are added within a minute" })
  if (row?.lock_kind) out.push({ text: `locked: ${LOCK[row.lock_kind] ?? "news"}`, tone: "text-down border-down/50", title: "exchange news against the coin: avoid adding" })
  if (row?.unlock_days != null && row.unlock_days <= 7) out.push({ text: `unlock ${Math.round(row.unlock_days)} d`, tone: "text-warn border-warn/50", title: "a token unlock of 5 %+ of supply is due" })
  if (row?.d_turb === 2 || row?.r_turb === 2) out.push({ text: "turbulence HIGH", tone: "text-warn border-warn/50", title: `day ${label(TURB, row.d_turb)}, 24 h ${label(TURB, row.r_turb)}: bigger moves, either way` })
  if (row?.risk_prob != null && row.risk_prob >= 0.3) out.push({ text: `move risk ${Math.round(row.risk_prob * 100)}%`, tone: "text-warn border-warn/50", title: "chance of a big move in the next 4 h" })
  const signal = lastSig.value[coinOf(pair)]
  if (signal) out.push({ text: `${sig(signal.layer).label} ${Math.max(1, Math.round((now - signal.ts) / 3600))}h`, tone: `${sig(signal.layer).tone} border-line`, title: "BTCGate signal in the last 24 h" })
  return out
}
