import { ref, watch } from "vue"
import type { Trade } from "@/lib/trades"
import { useLive } from "@/stores/live"

// closed trades of every bot, fetched once and shared by the History and Analytics pages
export type Row = Trade & { _bot: string; _nfi: boolean }

const all = ref<Row[]>([])
const loading = ref(false)
let started = false

async function load() {
  const live = useLive()
  loading.value = true
  const out: Row[] = []
  for (const bot of Object.values(live.bots)) {
    const response = await fetch(`/api/bots/${encodeURIComponent(bot.name)}/history`).catch(() => null)
    if (response?.ok) out.push(...((await response.json()) as Trade[]).map((trade) => ({ ...trade, _bot: bot.name, _nfi: !!bot.is_nfi })))
  }
  all.value = out.sort((left, right) => (right.close_timestamp ?? 0) - (left.close_timestamp ?? 0))
  loading.value = false
}

export function useHistory() {
  if (!started) {
    started = true
    const live = useLive()
    watch(() => Object.keys(live.bots).join(), load, { immediate: true })
  }
  return { all, loading, load }
}
