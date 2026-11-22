import { defineStore } from "pinia"
import { computed, ref } from "vue"
import { current } from "@/lib/push"

// who is signed in (the session itself is an HttpOnly cookie the page never sees)
// what a viewer may see (the server checks every request; this only shapes the menu). null = all
export const SECTIONS = ["radar", "orderflow", "btcgate", "logs", "server", "notifications"] as const
export type Section = (typeof SECTIONS)[number]
export type Access = { bots: string[] | null; pages: Section[] | null; percent: boolean }
export type User = { id: number; username: string; role: "admin" | "viewer"; access?: Access }

export const useAuth = defineStore("auth", () => {
  const user = ref<User | null>(null)
  const hasUsers = ref(true)
  const checked = ref(false)
  const isAdmin = computed(() => user.value?.role === "admin")
  const access = computed<Access>(() => (isAdmin.value ? null : user.value?.access) ?? { bots: null, pages: null, percent: false })
  const percent = computed(() => access.value.percent)
  const can = (section: Section | string | undefined) => !section || (!percent.value && (access.value.pages ?? (SECTIONS as readonly string[])).includes(section))

  async function status() {
    const response = await fetch("/api/auth/status").catch(() => null)
    if (response?.ok) { const data = await response.json(); user.value = data.user; hasUsers.value = data.has_users }
    checked.value = true
  }
  async function post(path: string, body: object) {
    const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).catch(() => null)
    const data = response ? await response.json().catch(() => ({})) : {}
    return { ok: !!response?.ok, d: data, error: response ? (data.detail ?? response.statusText) : "NFIForge isn't reachable" }
  }
  async function login(username: string, password: string) {
    const result = await post("/api/auth/login", { username, password })
    if (result.ok) user.value = result.d
    return result.ok ? "" : result.error
  }
  async function logout(everywhere = false) {
    // this device's phone alerts stop with its sign-out
    const sub = await current().catch(() => null)
    await post("/api/auth/logout", { everywhere, push: sub?.endpoint })
    await sub?.unsubscribe().catch(() => {})
    location.reload()
  }
  // a phone link from ./install.sh --phone carries ?pair=<code>: swap it once for a session, then drop it from the address
  async function claimPairCode(): Promise<string> {
    const url = new URL(location.href)
    const code = url.searchParams.get("pair")
    if (!code) return ""
    url.searchParams.delete("pair")
    history.replaceState(null, "", url.pathname + url.search + url.hash)
    const result = await post("/api/auth/pair", { code })
    if (result.ok) user.value = result.d
    return result.ok ? "" : result.error
  }
  return { user, hasUsers, checked, isAdmin, access, percent, can, status, post, login, logout, claimPairCode }
})
