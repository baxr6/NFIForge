import { defineStore } from "pinia"
import { ref, watch } from "vue"
import { useAuth } from "./auth"
import { useSettings } from "./settings"

export type BotState = Record<string, any> & { name: string; connected: boolean }
export type LiveEvent = { ts: number; type: string; data: any }
export type Note = { id: number; ts: number; bot: string; kind: "alert" | "trade" | "action" | "signal"; level: "bad" | "warn" | "info" | "ok"; key: string; title: string; detail: string; cleared: number | null }

// one websocket to the backend: snapshot on connect, then state diffs and events
export const useLive = defineStore("live", () => {
  const bots = ref<Record<string, BotState>>({})
  const events = ref<Record<string, LiveEvent[]>>({})
  const online = ref(false)
  const host = ref<Record<string, any>>({})
  // the bot picked on Trading / Chart / Logs / Pairs, the same on every page, remembered in this browser
  const picked = ref<string | null>(null)
  try { picked.value = localStorage.getItem("nfiforge.bot") } catch { /* storage blocked */ }
  watch(picked, (name) => { try { if (name) localStorage.setItem("nfiforge.bot", name) } catch { /* not saved */ } })
  watch(() => Object.keys(bots.value).join(), () => {
    const names = Object.keys(bots.value)
    if (names.length && (!picked.value || !names.includes(picked.value))) picked.value = names[0]
  })
  // notifications: unread count for the sidebar, the newest ones for the page, pop-ups for alerts if allowed
  const unread = ref(0)
  const notes = ref<Note[]>([])
  async function loadNotes() {
    if (!useAuth().can("notifications")) return
    const response = await fetch("/api/notifications?limit=200").catch(() => null)
    if (response?.ok) { const data = await response.json(); notes.value = data.items; unread.value = data.unread }
  }
  function onNote(note: Note) {
    notes.value = [note, ...notes.value].slice(0, 1000)
    unread.value++
    const alerts = useSettings().s?.alerts
    if (alerts?.browser && note.kind === "alert" && "Notification" in window && Notification.permission === "granted")
      new Notification(note.title, { body: note.detail, tag: `${note.bot}:${note.key}` })
  }
  let socket: WebSocket | null = null
  let retry = 1000

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws"
    socket = new WebSocket(`${proto}://${location.host}/ws`)
    socket.onopen = () => { online.value = true; retry = 1000; loadNotes() }
    socket.onclose = (event) => {
      online.value = false
      if (event.code === 4403) return  // a percent-only account: no live state
      setTimeout(connect, retry)
      retry = Math.min(retry * 2, 30000)
    }
    socket.onmessage = (message) => {
      const msg = JSON.parse(message.data)
      if (msg.type === "snapshot") { bots.value = msg.data; events.value = msg.events ?? {} }
      else if (msg.type === "settings") useSettings().adopt(msg.data)
      else if (msg.type === "host") host.value = msg.data
      else if (msg.type === "state_diff" && msg.bot !== "__proto__") Object.assign(bots.value[msg.bot] ??= { name: msg.bot, connected: false }, msg.data)
      else if (msg.type === "bot_removed") { delete bots.value[msg.bot]; delete events.value[msg.bot] }
      else if (msg.type === "notification") onNote(msg.data)
      else if (msg.type === "notifications_read") unread.value = msg.data.unread
      else if (msg.type === "event") {
        const list = (events.value[msg.bot] ??= [])
        list.push(msg.data)
        if (list.length > 500) list.splice(0, list.length - 500)
      }
    }
  }

  return { bots, events, online, host, picked, connect, unread, notes, loadNotes }
})
