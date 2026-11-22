import { defineStore } from "pinia"
import { ref, watch } from "vue"
import { useAuth } from "@/stores/auth"

export type GaugeSetting = { enabled: boolean; warn: number | null; danger: number | null; style?: "analog" | "segment" | null }
export type PageLayout = { cols?: number; items: { i: string; x: number; y: number; w: number; h: number }[]; hidden: string[] }
export type AlertSettings = { api_down_s: number; stuck_min: number; liq_pct: number; drawdown_pct: number; disk_pct: number; ram_pct: number; container_mem_pct: number; trade_events: boolean; browser: boolean }
export type Settings = {
  timezone: "utc" | "local"; day_boundary: "utc" | "freqtrade"; fiat?: string | null; gauges: Record<string, GaugeSetting>; alerts: AlertSettings
  layouts?: Record<string, PageLayout>
  colorblind?: boolean  // up / down in blue / orange
  orderflow?: Record<string, number | boolean>  // order flow worker options changed here, over config.yaml's
}

// settings live on the server so every device sees the same; the live socket pushes changes from other tabs
export const useSettings = defineStore("settings", () => {
  const s = ref<Settings | null>(null)
  const saving = ref(false)
  const error = ref<string | null>(null)
  const savedAt = ref<Date | null>(null)
  let clean = ""  // last state the server has; changes are saved only when they differ from it

  // server copy (first load or pushed from another tab): take it without saving it back
  function adopt(data: Settings) {
    clean = JSON.stringify(data)
    s.value = data
  }

  async function load() {
    const response = await fetch("/api/settings")
    if (response.ok) adopt(await response.json())
    else error.value = `could not load settings (${response.status})`
  }

  // only admins change settings (layouts included); a viewer's edits stay on that screen
  async function save() {
    if (!s.value || !useAuth().isAdmin) return
    const body = JSON.stringify(s.value)
    if (body === clean) return
    saving.value = true
    error.value = null
    try {
      const response = await fetch("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body })
      if (!response.ok) {
        const detail = (await response.json().catch(() => ({}))).detail
        error.value = typeof detail === "string" ? `not saved: ${detail}` : `save failed (${response.status})`
        return
      }
      clean = body
      savedAt.value = new Date()
    } catch {
      error.value = "save failed: backend not reachable"
    } finally {
      saving.value = false
    }
  }

  // every change saves itself half a second later
  let timer = 0
  watch(s, () => {
    clearTimeout(timer)
    timer = window.setTimeout(save, 500)
  }, { deep: true })

  function gauge(id: string): GaugeSetting {
    return s.value?.gauges[id] ?? { enabled: true, warn: null, danger: null }
  }

  return { s, saving, error, savedAt, load, save, adopt, gauge }
})
