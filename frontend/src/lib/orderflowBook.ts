import { onBeforeUnmount, onMounted, ref, watch, computed } from "vue"
import { storeToRefs } from "pinia"
import { pair } from "@/lib/orderflowState"
import { useLive } from "@/stores/live"

// the latest book sample (dom, depth chart) and trades (tape) of the Order Flow pair, polled every second while a panel
// shows them
export type BookNow = {
  pending: boolean
  stale?: boolean
  step?: number
  book?: { ts: number; bids: [number, number][]; asks: [number, number][]; wall_usd: number; step: number } | null
  traded?: [number, number, number][]  // stored row, bought, sold today (utc)
  last?: [number, number, number, boolean] | null  // the latest trade: ms, price, amount, taker bought
}

export type TapeNow = {
  pending: boolean
  trades?: [number, number, number, boolean][]  // ms, price, amount, taker bought; oldest first
  big_usd?: number
  step?: number  // price row size (sets the decimals)
}

export const useBookNow = () => usePairPoll<BookNow>("book")
export const useTape = () => usePairPoll<TapeNow>("tape")

function usePairPoll<T>(what: "book" | "tape") {
  const live = useLive()
  const { picked } = storeToRefs(live)
  const bot = computed(() => live.bots[picked.value ?? ""] ?? Object.values(live.bots)[0])
  const data = ref<T | null>(null)
  const error = ref("")
  let timer = 0, busy = false
  async function load() {
    if (!bot.value || !pair.value || busy) return
    busy = true
    try {
      const query = new URLSearchParams({ bot: bot.value.name, pair: pair.value })
      const response = await fetch(`/api/orderflow/${what}?${query}`)
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail ?? response.statusText)
      data.value = await response.json()
      error.value = ""
    } catch (e) {
      error.value = String((e as Error).message ?? e)
    } finally {
      busy = false
    }
  }
  watch([() => bot.value?.name, pair], () => { data.value = null; load() })
  onMounted(() => { load(); timer = window.setInterval(load, 1000) })
  onBeforeUnmount(() => clearInterval(timer))
  return { data, error }
}
