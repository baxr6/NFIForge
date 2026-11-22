<script setup lang="ts">
import { onMounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import Sidebar from "@/components/layout/Sidebar.vue"
import LoginGate from "@/components/layout/LoginGate.vue"
import BottomNav from "@/components/layout/BottomNav.vue"
import { provideTrading } from "@/lib/trading"
import { watchUpdates } from "@/lib/update"
import { storeToRefs } from "pinia"
import { useAuth } from "@/stores/auth"
import { useLive } from "@/stores/live"
import { useSettings } from "@/stores/settings"
import ShareView from "@/views/ShareView.vue"

const live = useLive()
// trading data shared by every page, so trading panels can be placed anywhere
provideTrading(storeToRefs(live).picked)
const settings = useSettings()
const route = useRoute()
const router = useRouter()
const menuOpen = ref(false)
const auth = useAuth()
const pairNote = ref("")
// a share link (/s/<code>) opens without an account, and with nothing else of NFIForge
const shareCode = location.pathname.match(/^\/s\/([^/]+)/)?.[1]
// a phone link signs in by itself; otherwise sign in first
onMounted(async () => {
  if (shareCode) return
  pairNote.value = await auth.claimPairCode()
  if (!auth.user) await auth.status()
  if (!auth.user || auth.percent) return  // percent-only accounts get the percent view, no live state
  settings.load()
  live.connect()
})
// colour-blind safe up / down colours (settings)
watch(() => settings.s?.colorblind, (on) => document.documentElement.classList.toggle("cb", !!on), { immediate: true })
// newer release notice: admins only (they're the ones who can update)
watch(() => auth.isAdmin, (admin) => watchUpdates(admin), { immediate: true })
// close the phone menu after picking a page
watch(() => route.path, () => (menuOpen.value = false))
// a page this account may not open (an old link, a bookmark) goes to Trading
watch([() => route.meta.section, () => auth.user], ([section]) => { if (auth.user && !auth.can(section as string | undefined)) router.replace("/trading") })
</script>

<template>
  <ShareView v-if="shareCode" :src="`/api/share/${encodeURIComponent(shareCode)}`" />
  <div v-else-if="!auth.user && !auth.checked" class="h-full" />
  <LoginGate v-else-if="!auth.user" :note="pairNote" />
  <ShareView v-else-if="auth.percent" src="/api/view" :user="auth.user.username" @sign-out="auth.logout()" />
  <div v-else class="flex h-full">
    <!-- desktop: fixed sidebar; phone/narrow: slide-in menu, opened from the tab bar's More -->
    <Sidebar class="hidden lg:flex" />
    <div v-if="menuOpen" class="fixed inset-0 z-40 bg-black/60 lg:hidden" @click="menuOpen = false" />
    <Sidebar v-if="menuOpen" class="fixed inset-y-0 left-0 z-50 flex lg:hidden shadow-2xl safe-y" />

    <div class="flex-1 flex flex-col min-w-0">
      <header class="lg:hidden flex items-center gap-3 px-3 py-2 border-b border-line bg-panel">
        <span class="font-semibold">{{ route.meta.label ?? "NFIForge" }}</span>
        <span class="ml-auto h-2 w-2 rounded-full" :style="{ background: live.online ? 'var(--green)' : 'var(--red)' }" />
      </header>
      <main class="flex-1 overflow-auto p-3 sm:p-4 2xl:p-6">
        <RouterView />
      </main>
      <BottomNav class="lg:hidden" :menu-open="menuOpen" @more="menuOpen = !menuOpen" />
    </div>
  </div>
</template>
