<script setup lang="ts">
// header strip card: title, main value, a detail line and an optional second line; amber/red edge when something needs a look
defineProps<{ title: string; value: string; detail?: string; sub?: string; level?: "ok" | "warn" | "bad" }>()
</script>

<template>
  <div class="panel px-3 py-2.5 min-w-0" :class="level === 'bad' ? 'lvl-bad' : level === 'warn' ? 'lvl-warn' : ''">
    <div class="flex items-center gap-1.5 text-[10px] font-semibold tracking-widest text-faint">
      <span class="h-1.5 w-1.5 rounded-full" :style="{ background: level === 'bad' ? 'var(--red)' : level === 'warn' ? 'var(--amber)' : 'var(--green)' }" />
      {{ title.toUpperCase() }}
    </div>
    <div class="text-base font-semibold mt-0.5 break-words md:truncate" :class="level === 'bad' ? 'text-down' : level === 'warn' ? 'text-warn' : ''">{{ value }}</div>
    <div v-if="detail" class="text-[11px] text-dim break-words md:truncate num">{{ detail }}</div>
    <div v-if="sub" class="text-[11px] text-faint font-mono truncate" :title="sub">{{ sub }}</div>
  </div>
</template>

<style scoped>
.lvl-warn { border-color: var(--amber-dim); box-shadow: inset 0 0 0 1px var(--amber-glow); }
.lvl-bad { border-color: var(--red-dim); box-shadow: inset 0 0 0 1px var(--red-glow); }
</style>
