import { computed, effectScope, ref, watch } from "vue"
import { money, signed } from "@/lib/format"
import { useSettings } from "@/stores/settings"

// usdt money also in the currency picked in settings, at a real usdt market rate fetched by the server every
// minute. no fresh rate (sources down 5 minutes) -> nothing shown rather than an old number
export const FIATS = ["AUD", "USD", "EUR", "GBP", "CAD", "CHF", "JPY"] as const
type Rate = { currency: string; rate: number; ts: number; source: string }

const rate = ref<Rate | null>(null)
const now = ref(Date.now())
let started = false

async function load(cur: string | null | undefined) {
  if (!cur) { rate.value = null; return }
  const data = await fetch(`/api/fx/${cur}`).then((response) => (response.ok ? response.json() : null)).catch(() => null)
  rate.value = data?.rate ?? null
}

export function useFiat(quote: () => string) {
  const settings = useSettings()
  const cur = () => settings.s?.fiat
  if (!started) {
    started = true
    // detached so the watch outlives the card that first asked
    effectScope(true).run(() => watch(cur, load, { immediate: true }))
    setInterval(() => { now.value = Date.now(); load(cur()) }, 60000)
  }
  const active = computed(() => (quote() === "USDT" && rate.value?.currency === cur() ? rate.value : null))
  const digits = () => (active.value?.currency === "JPY" ? 0 : 2)
  return {
    on: computed(() => !!active.value),
    rate: computed(() => active.value),  // for files: the number, not the text
    // "1,013.42 AUD" / "+385.60 AUD"
    amount: (value: number | null | undefined) => (active.value && value != null ? `${money(value * active.value.rate, digits())} ${active.value.currency}` : ""),
    change: (value: number | null | undefined) => (active.value && value != null ? `${signed(value * active.value.rate, digits())} ${active.value.currency}` : ""),
    // "1 USDT = 1.4317 AUD · kraken · 20s ago"
    note: computed(() => {
      if (!active.value) return ""
      const ago = Math.max(0, Math.round((now.value - active.value.ts * 1000) / 1000))
      return `1 USDT = ${active.value.rate.toFixed(active.value.currency === "JPY" ? 2 : 4)} ${active.value.currency} · ${active.value.source} · ${ago < 90 ? `${ago}s` : `${Math.round(ago / 60)}m`} ago`
    }),
  }
}
