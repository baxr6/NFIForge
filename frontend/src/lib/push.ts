// phone alerts (web push) for this device: needs https, and on an iphone the app added to the home screen
export type PushState = "on" | "off" | "blocked" | "needs-https" | "needs-home-screen" | "unsupported"

const ios = /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
const standalone = () => matchMedia("(display-mode: standalone)").matches || (navigator as any).standalone === true

async function reg(): Promise<ServiceWorkerRegistration | null> {
  if (!("serviceWorker" in navigator)) return null
  return (await navigator.serviceWorker.getRegistration("/")) ?? navigator.serviceWorker.register("/sw.js", { scope: "/" })
}

export async function current(): Promise<PushSubscription | null> {
  if (!window.isSecureContext || !("serviceWorker" in navigator)) return null
  const registration = await navigator.serviceWorker.getRegistration("/")
  return (await registration?.pushManager.getSubscription()) ?? null
}

export async function pushState(): Promise<PushState> {
  if (!window.isSecureContext) return "needs-https"
  if (ios && !standalone()) return "needs-home-screen"
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) return "unsupported"
  if (Notification.permission === "denied") return "blocked"
  return (await current()) ? "on" : "off"
}

function key(b64: string): Uint8Array<ArrayBuffer> {
  const raw = atob(b64.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (b64.length % 4)) % 4))
  return Uint8Array.from(raw, (char) => char.charCodeAt(0))
}

const post = (path: string, body: object) =>
  fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })

// returns an error message, or "" when on
export async function enable(): Promise<string> {
  if ((await Notification.requestPermission()) !== "granted") return "notifications weren't allowed"
  const registration = await reg()
  if (!registration) return "this browser can't do push"
  await navigator.serviceWorker.ready
  const vapid = await fetch("/api/push/key").then((response) => response.json())
  const sub = (await registration.pushManager.getSubscription()) ?? (await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key(vapid.key) }))
  const res = await post("/api/push/subscribe", sub.toJSON())
  if (res.ok) return ""
  await sub.unsubscribe()
  return (await res.json().catch(() => ({}))).detail ?? "NFIForge refused the subscription"
}

export async function disable(): Promise<void> {
  const sub = await current()
  if (!sub) return
  await post("/api/push/unsubscribe", { endpoint: sub.endpoint })
  await sub.unsubscribe()
}

export async function test(): Promise<string> {
  const result = await post("/api/push/test", {}).then((response) => response.json()).catch(() => ({}))
  return result.ok ? "" : "the push service didn't take it"
}
