<script setup lang="ts">
import { onMounted, ref } from "vue"
import { RouterLink } from "vue-router"
import Drawer from "@/components/trades/Drawer.vue"
import { badges, coinOf, scanText, useBtcgateCoins } from "@/lib/btcgate"
import { age } from "@/lib/format"
import { ICON, TONE, useNotifications } from "@/lib/state/notifications"
import type { Note } from "@/stores/live"

// one notification in full; a btcgate one also shows what btcgate says about the coin now and the news naming it
const props = defineProps<{ note: Note }>()
const emit = defineEmits<{ close: [] }>()
const { when, pairOf } = useNotifications()
useBtcgateCoins()

const pair = pairOf(props.note)
const coin = props.note.kind === "signal" ? coinOf(props.note.key.split(":")[1] ?? "") : pair ? coinOf(pair) : ""
type News = { src: string; ts: number; title: string; url: string | null }
const info = ref<{ scan: { reasons?: string[]; known?: string[]; extras?: string[]; labels?: string[] } | null; news: News[] }>()
onMounted(async () => {
  if (!coin) return
  const response = await fetch(`/api/btcgate/coin/${encodeURIComponent(coin)}`).catch(() => null)
  if (response?.ok) info.value = await response.json()
})
const source = (text: string) => text.replace(/_/g, " ")
</script>

<template>
  <Drawer @close="emit('close')">
    <div class="max-w-2xl space-y-4">
      <div class="flex gap-3 items-start">
        <span class="mt-1 w-6 h-6 shrink-0 grid place-items-center rounded-full border text-xs font-bold" :class="TONE[note.level]">{{ ICON[note.level] }}</span>
        <div>
          <h2 class="text-lg text-ink font-semibold break-words">{{ note.title }}</h2>
          <div class="text-xs text-faint">{{ when(note.ts) }} · {{ age(note.ts) }} ago · {{ note.bot }}<span v-if="note.cleared"> · cleared {{ when(note.cleared) }}</span></div>
        </div>
      </div>
      <p v-if="note.detail" class="text-sm text-dim break-words">{{ note.detail }}</p>
      <RouterLink v-if="pair && note.kind !== 'signal'" :to="{ path: '/chart', query: { bot: note.bot, pair } }"
        class="inline-block px-3 py-1.5 rounded-md border border-line text-sm text-ink hover:text-brand-b">Open chart</RouterLink>

      <template v-if="coin">
        <section v-if="badges(coin).length">
          <h3 class="text-sm text-ink font-semibold mb-1">BTCGate on {{ coin }} now</h3>
          <div class="flex flex-wrap gap-1.5">
            <span v-for="badge in badges(coin)" :key="badge.text" class="text-xs px-2 py-0.5 rounded-full border" :class="badge.tone" :title="badge.title">{{ badge.text }}</span>
          </div>
        </section>
        <section v-if="info?.scan">
          <h3 class="text-sm text-ink font-semibold mb-1">Scanner</h3>
          <div class="text-sm text-dim">{{ (info.scan.labels ?? []).map(scanText).join(" · ") }}</div>
          <ul class="text-sm text-dim list-disc pl-5">
            <li v-for="reason in [...(info.scan.reasons ?? []), ...(info.scan.known ?? []), ...(info.scan.extras ?? [])]" :key="reason">{{ reason }}</li>
          </ul>
        </section>
        <section v-if="info">
          <h3 class="text-sm text-ink font-semibold mb-1">Exchange news naming {{ coin }} (90 days)</h3>
          <div v-for="story in info.news" :key="story.src + story.ts" class="py-1.5 border-b border-line last:border-0 text-sm">
            <a v-if="story.url" :href="story.url" target="_blank" rel="noopener" class="text-ink underline underline-offset-2 hover:text-brand-b">{{ story.title }}</a>
            <span v-else class="text-ink">{{ story.title }}</span>
            <div class="text-xs text-faint">{{ source(story.src) }} · {{ when(story.ts) }}</div>
          </div>
          <div v-if="!info.news.length" class="text-sm text-faint">none</div>
        </section>
      </template>
    </div>
  </Drawer>
</template>
