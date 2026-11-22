<script setup lang="ts">
import { computed } from "vue"
import { navGroups } from "@/router"
import { features } from "@/lib/features"
import { update } from "@/lib/update"
import { useAuth } from "@/stores/auth"
import { useLive } from "@/stores/live"

const live = useLive()
const auth = useAuth()
const featureOn = (item: object) => !("feature" in item) || (features as Record<string, boolean>)[item.feature as string]
const version = __APP_VERSION__

const botsUp = computed(() => Object.values(live.bots).filter((bot) => bot.connected).length)
const botsAll = computed(() => Object.keys(live.bots).length)
</script>

<template>
  <aside class="w-56 shrink-0 border-r border-line bg-panel flex-col">
    <div class="px-4 py-4 flex items-center gap-2">
      <div class="h-6 w-6 rounded-md" style="background: linear-gradient(135deg, var(--brand-a), var(--brand-b)); box-shadow: 0 0 14px var(--brand-glow)" />
      <span class="font-semibold tracking-wide">NFIForge</span>
      <span class="text-[10px] num text-faint mt-0.5">v{{ version }}</span>
    </div>
    <a v-if="update" :href="update.url" target="_blank" rel="noopener" class="mx-4 -mt-2 mb-2 text-[11px] text-warn hover:underline">
      ↑ v{{ update.latest }} available · {{ update.how }}
    </a>
    <nav class="flex-1 overflow-auto px-2">
      <div v-for="group in navGroups" :key="group.title" class="mb-4">
        <div class="px-2 mb-1 text-[11px] font-semibold tracking-widest text-faint">{{ group.title }}</div>
        <RouterLink v-for="item in group.items.filter((item) => (auth.isAdmin || !('admin' in item)) && featureOn(item) && auth.can('section' in item ? item.section : undefined))" :key="item.name" :to="item.path"
          class="block rounded-md px-2 py-1.5 text-sm text-dim hover:bg-hover hover:text-ink"
          active-class="!text-ink bg-hover nav-active">{{ item.label }}<span v-if="item.name === 'notifications' && live.unread"
            class="float-right num text-[10px] px-1.5 rounded-full bg-down text-ink mt-0.5">{{ live.unread > 99 ? "99+" : live.unread }}</span></RouterLink>
      </div>
    </nav>
    <div class="px-4 pt-3 text-xs flex items-center gap-2">
      <RouterLink to="/settings" class="truncate text-dim hover:text-ink">{{ auth.user?.username }}</RouterLink>
      <span class="text-faint">{{ auth.user?.role }}</span>
      <button class="ml-auto text-dim hover:text-ink" @click="auth.logout()">Sign out</button>
    </div>
    <div class="px-4 py-3 mt-3 border-t border-line text-xs flex items-center gap-2">
      <span class="h-2 w-2 rounded-full" :style="{ background: live.online ? 'var(--green)' : 'var(--red)', boxShadow: live.online ? '0 0 8px var(--green)' : 'none' }" />
      <span class="text-dim">{{ live.online ? "backend live" : "backend offline" }}</span>
      <span class="ml-auto num text-dim">{{ botsUp }}/{{ botsAll }} bots</span>
    </div>
  </aside>
</template>

<style scoped>
/* active page gets the brand gradient edge */
.nav-active { box-shadow: inset 2px 0 0 var(--brand-b); }
</style>
