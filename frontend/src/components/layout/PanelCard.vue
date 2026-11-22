<script setup lang="ts">
// standard panel frame: title row with optional actions, body that fills the cell and scrolls
withDefaults(defineProps<{ title?: string; pad?: boolean }>(), { pad: true })
</script>

<template>
  <div class="panel h-full flex flex-col min-h-0" :class="pad && 'p-4'">
    <div v-if="title || $slots.actions" class="flex flex-wrap items-baseline gap-x-2 gap-y-1 mb-2 shrink-0" :class="!pad && 'px-4 pt-4'">
      <div class="panel-title">{{ title }}</div>
      <!-- actions drop under the title when a narrow screen can't fit both -->
      <div class="ml-auto min-w-0 max-w-full flex flex-wrap items-center justify-end gap-2"><slot name="actions" /></div>
    </div>
    <div class="flex-1 min-h-0 overflow-auto"><slot /></div>
  </div>
</template>
