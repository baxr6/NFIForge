import { ref } from "vue"

// newer release notice for admins (the backend asks github at most once a day); shown in the sidebar and as a dot on
// the phone tab bar's More
export const update = ref<{ latest: string; url: string; how: string } | null>(null)
let timer = 0

async function check() {
  const response = await fetch("/api/update").catch(() => null)
  const release = response?.ok ? await response.json() : null
  update.value = release?.newer ? { latest: release.latest, url: release.url, how: release.how } : null
}

export function watchUpdates(on: boolean) {
  clearInterval(timer)
  update.value = null
  if (!on) return
  check()
  timer = window.setInterval(check, 6 * 3600 * 1000)
}
