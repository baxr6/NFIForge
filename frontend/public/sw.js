// phone alerts: show each pushed alert, open the notifications page on a tap. nothing is cached here,
// the dashboard always loads live
self.addEventListener("install", () => self.skipWaiting())
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()))

self.addEventListener("push", (e) => {
  let m = { title: "NFIForge alert", body: "" }
  try { m = e.data ? e.data.json() : m } catch { /* keep the plain title */ }
  e.waitUntil(self.registration.showNotification(m.title, {
    body: m.body, tag: m.tag, renotify: !!m.tag, icon: "/icon-192.png", badge: "/icon-192.png", data: { url: "/notifications" },
  }))
})

self.addEventListener("notificationclick", (e) => {
  e.notification.close()
  const url = e.notification.data?.url ?? "/notifications"
  e.waitUntil((async () => {
    const tabs = await self.clients.matchAll({ type: "window", includeUncontrolled: true })
    const open = tabs.find((c) => new URL(c.url).origin === self.location.origin)
    if (open) { await open.focus(); return open.navigate(url) }
    return self.clients.openWindow(url)
  })())
})
