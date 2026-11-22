<script setup lang="ts">
import { RouterLink } from "vue-router"
import PanelCard from "@/components/layout/PanelCard.vue"
import { signed, tone } from "@/lib/format"
import { usePairs } from "@/lib/state/pairs"

const { q, found, bot, statusOf, TONES, past } = usePairs()
</script>

<template>
  <PanelCard title="Find a pair">
    <template #actions>
      <input v-model="q" placeholder="e.g. KAITO" class="rounded-md bg-raised border border-line px-2 py-1 text-ink text-sm w-48 uppercase" />
      <span class="text-xs text-faint hidden md:inline">why is (or isn't) the bot trading it</span>
    </template>
    <div v-for="pair in found" :key="pair" class="flex flex-wrap gap-x-4 gap-y-1 items-baseline text-sm py-0.5">
      <RouterLink :to="{ path: '/chart', query: { bot: bot?.name, pair: pair } }" class="font-semibold num text-brand-b hover:underline w-40">{{ pair }}</RouterLink>
      <span v-for="(status, i) in statusOf(pair)" :key="i" :class="TONES[status.tone]">{{ status.text }}</span>
      <span v-if="past.get(pair)" class="text-dim num">· {{ past.get(pair)!.n }} past trades, <span :class="tone(past.get(pair)!.total)">{{ signed(past.get(pair)!.total) }}</span></span>
    </div>
  </PanelCard>
</template>
