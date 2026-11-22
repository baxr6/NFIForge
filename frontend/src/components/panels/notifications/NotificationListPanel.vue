<script setup lang="ts">
import { ref } from "vue"
import PanelCard from "@/components/layout/PanelCard.vue"
import NoteDetail from "@/components/panels/notifications/NoteDetail.vue"
import { ICON, TONE, useNotifications } from "@/lib/state/notifications"
import type { Note } from "@/stores/live"

const { live, more, loadMore, kind, bot, bots, shown, when } = useNotifications()
const picked = ref<Note | null>(null)
</script>

<template>
  <PanelCard :pad="false">
    <template #actions>
      <div class="flex rounded-md border border-line overflow-hidden text-sm">
        <button v-for="[value, label] in ([['', 'all'], ['alert', 'alerts'], ['trade', 'trade events'], ['action', 'actions'], ['signal', 'BTCGate']] as const)" :key="value" class="px-3 py-1"
          :class="kind === value ? 'bg-raised text-ink' : 'text-dim hover:text-ink'" @click="kind = value">{{ label }}</button>
      </div>
      <select v-if="bots.length > 1" v-model="bot" class="rounded-md bg-raised border border-line px-2 py-1 text-ink text-sm"><option value="">all bots</option><option v-for="name in bots" :key="name">{{ name }}</option></select>
    </template>
    <button v-for="note in shown" :key="note.id" class="w-full text-left flex gap-3 items-start px-4 py-2 border-b border-line last:border-0 hover:bg-raised" @click="picked = note">
      <span class="mt-0.5 w-5 h-5 shrink-0 grid place-items-center rounded-full border text-[11px] font-bold" :class="TONE[note.level]">{{ ICON[note.level] }}</span>
      <div class="min-w-0 flex-1">
        <div class="text-sm" :class="note.level === 'info' || note.level === 'ok' ? 'text-dim' : 'text-ink'">
          {{ note.title }}
          <span v-if="note.kind === 'alert' && note.cleared" class="text-xs text-faint"> · cleared</span>
        </div>
        <div v-if="note.detail" class="text-xs text-faint break-words">{{ note.detail }}</div>
      </div>
      <div class="text-right shrink-0">
        <div class="text-xs text-faint num whitespace-nowrap">{{ when(note.ts) }}</div>
        <div v-if="bots.length > 1" class="text-[11px] text-faint">{{ note.bot }}</div>
      </div>
    </button>
    <div v-if="!shown.length" class="p-8 text-center text-dim">nothing yet: alerts and trade events appear here as they happen</div>
    <button v-else-if="more && live.notes.length >= 200" class="w-full py-2 text-sm text-dim hover:text-ink" @click="loadMore">older…</button>
    <NoteDetail v-if="picked" :note="picked" @close="picked = null" />
  </PanelCard>
</template>
