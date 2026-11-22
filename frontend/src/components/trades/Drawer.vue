<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue"

// right-side panel over the page (full width on phones); esc or the backdrop closes it
const emit = defineEmits<{ close: [] }>()
const onKey = (e: KeyboardEvent) => e.key === "Escape" && emit("close")
onMounted(() => window.addEventListener("keydown", onKey))
onBeforeUnmount(() => window.removeEventListener("keydown", onKey))
</script>

<!-- teleported to body: inside a grid panel (moved with css transforms) "fixed" would be the panel, not the page -->
<template>
  <Teleport to="body">
  <div class="fixed inset-0 z-40 bg-black/60" @click="emit('close')" />
  <aside class="fixed inset-y-0 right-0 z-50 w-full lg:w-[min(1100px,70vw)] bg-void border-l border-line overflow-auto p-4 safe-y-4 shadow-2xl">
    <button class="float-right ml-3 px-2 py-1 rounded-md border border-line text-dim hover:text-ink" @click="emit('close')">✕ close</button>
    <slot />
  </aside>
  </Teleport>
</template>
