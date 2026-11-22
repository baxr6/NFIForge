import { computed, ref, watch } from "vue"
import { once } from "@/lib/shared"
import { useLive, type Note } from "@/stores/live"
import { useSettings } from "@/stores/settings"

// the Notifications page's data, shared by its panels: open alerts, the list (newest from the live socket, older
// pages on request) and the list's filters
export const ICON = { bad: "✕", warn: "!", info: "•", ok: "✓" }
export const TONE = { bad: "text-down border-down/50 bg-down/10", warn: "text-warn border-warn/50 bg-warn/10", info: "text-brand-b border-brand-b/40 bg-brand-b/10", ok: "text-up border-up/40 bg-up/10" }

export const useNotifications = once(() => {
  const live = useLive()
  const settings = useSettings()
  const utc = computed(() => settings.s?.timezone !== "local")
  const active = ref<Note[]>([])
  const older = ref<Note[]>([])
  const more = ref(true)

  async function loadActive() {
    const response = await fetch("/api/notifications?limit=1").catch(() => null)
    if (response?.ok) active.value = (await response.json()).active
  }
  // a new note can open or close an alert
  watch(() => live.notes[0]?.id, loadActive, { immediate: true })

  async function loadMore() {
    const all = [...live.notes, ...older.value]
    const response = await fetch(`/api/notifications?limit=200&before=${all[all.length - 1]?.id ?? 0}`).catch(() => null)
    if (!response?.ok) return
    const items = (await response.json()).items as Note[]
    older.value.push(...items)
    more.value = items.length === 200
  }

  const kind = ref<"" | "alert" | "trade" | "action" | "signal">("")
  const bot = ref("")
  const bots = computed(() => [...new Set([...live.notes, ...older.value].map((note) => note.bot))])
  const shown = computed(() => [...live.notes, ...older.value].filter((note) => (!kind.value || note.kind === kind.value) && (!bot.value || note.bot === bot.value)))
  const when = (ts: number) => new Date(ts * 1000).toLocaleString("en-GB", { timeZone: utc.value ? "UTC" : undefined, hour12: false, dateStyle: "short", timeStyle: "medium" })
  const pairOf = (note: Note) => /([A-Z0-9]{2,20}\/[A-Z]{3,5}(?::[A-Z]{3,5})?)/.exec(note.title)?.[1]
  return { live, active, loadActive, more, loadMore, kind, bot, bots, shown, when, pairOf }
})
