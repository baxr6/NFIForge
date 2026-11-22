import { computed, type Ref } from "vue"
import { useAuth } from "@/stores/auth"
import { useLive } from "@/stores/live"

// trade actions: admins only, and only on bots with write_actions + their own trading switch on (the backend checks
// the same again, and asks the bot fresh whether it is live)
export function useTradeAccess(bot: Ref<string | null | undefined>) {
  const auth = useAuth()
  const live = useLive()
  const state = computed(() => live.bots[bot.value ?? ""])
  const canTrade = computed(() => auth.isAdmin && !!state.value?.trading && !!state.value?.connected)
  const isLive = computed(() => state.value?.config?.dry_run === false)
  const canShort = computed(() => state.value?.config?.trading_mode === "futures" && !!state.value?.config?.short_allowed)
  const canAdd = computed(() => !!state.value?.config?.position_adjustment_enable)
  const futures = computed(() => state.value?.config?.trading_mode === "futures")
  return { canTrade, isLive, canShort, canAdd, futures }
}

export async function tradeAction(bot: string, action: "enter" | "exit" | "cancel" | "reload" | "delete" | "control" | "lock" | "unlock" | "blacklist", body: object) {
  const response = await fetch(`/api/trade/${encodeURIComponent(bot)}/${action}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }).catch(() => null)
  if (!response) return { ok: false, error: "NFIForge isn't reachable" }
  const result = await response.json().catch(() => ({}))
  return { ok: response.ok, error: response.ok ? "" : String(result.detail ?? response.statusText) }
}

// nfi v4 grind levels for an add: the tag goes on the order, nfi then counts it in that level and sells it at
// that level's target (shorts have no buyback)
export function addTags(isShort: boolean, isNfi: boolean): [string, string][] {
  const plain: [string, string][] = [["force_entry", "normal add"]]
  if (!isNfi) return plain
  const grinds: [string, string][] = [1, 2, 3, 4, 5].map((level) => [`grind_${level}_entry`, `grind ${level}`])
  return [...plain, ...grinds, ...(isShort ? [] : [["buyback_1_entry", "buyback"] as [string, string]]), ["rebuy_entry", "rebuy"]]
}
