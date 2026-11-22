<script setup lang="ts">
// money row card: label, big number, small line under it
defineProps<{ label: string; value: string; unit?: string; sub?: string; valueClass?: string; badge?: string }>()
</script>

<template>
  <div class="panel p-3 min-w-0 h-full">
    <div class="flex items-center gap-2 text-xs text-dim">
      {{ label }}
      <span v-if="badge" class="text-[10px] px-1.5 rounded bg-[var(--amber-dim)] text-warn">{{ badge }}</span>
    </div>
    <div class="num text-xl md:text-2xl 2xl:text-[1.7rem] font-semibold mt-1 truncate" :class="valueClass">{{ value }} <span v-if="unit" class="text-xs text-dim font-normal">{{ unit }}</span></div>
    <div v-if="sub" class="text-[11px] text-dim mt-0.5 num break-words md:truncate">{{ sub }}</div>
    <slot />
  </div>
</template>
