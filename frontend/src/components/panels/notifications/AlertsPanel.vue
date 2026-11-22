<script setup lang="ts">
import { ref } from "vue"
import PanelCard from "@/components/layout/PanelCard.vue"
import { age } from "@/lib/format"
import NoteDetail from "@/components/panels/notifications/NoteDetail.vue"
import { ICON, TONE, useNotifications } from "@/lib/state/notifications"
import type { Note } from "@/stores/live"

const { active } = useNotifications()
const picked = ref<Note | null>(null)
</script>

<template>
  <PanelCard title="Open alerts">
    <button v-for="note in active" :key="note.id" class="w-full text-left flex gap-3 items-start py-1.5 hover:bg-raised rounded-md" @click="picked = note">
      <span class="mt-0.5 w-5 h-5 shrink-0 grid place-items-center rounded-full border text-[11px] font-bold" :class="TONE[note.level]">{{ ICON[note.level] }}</span>
      <div class="min-w-0">
        <div class="text-sm text-ink">{{ note.title }}</div>
        <div class="text-xs text-faint">{{ note.detail }}{{ note.detail ? " · " : "" }}since {{ age(note.ts) }} ago</div>
      </div>
    </button>
    <NoteDetail v-if="picked" :note="picked" @close="picked = null" />
    <div v-if="!active.length" class="text-sm text-up">nothing open, all bots look fine</div>
  </PanelCard>
</template>
