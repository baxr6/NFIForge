<script setup lang="ts">
import { computed, ref } from "vue"
import { download, type Sheet } from "@/lib/download"
import { useSettings } from "@/stores/settings"

// "↓ download" with csv / excel; sheets are built only when picked. csv holds the first sheet, excel all of them
const props = defineProps<{ name: string; sheets: () => Sheet[]; disabled?: boolean }>()
const settings = useSettings()
const open = ref(false)
const utc = computed(() => settings.s?.timezone !== "local")
function pick(format: "csv" | "xlsx") {
  open.value = false
  download(props.name, format, props.sheets(), utc.value)
}
</script>

<template>
  <div class="relative" @keydown.esc="open = false">
    <button class="text-xs px-3 py-2 md:py-1 rounded-md border border-line text-dim hover:text-ink disabled:opacity-40" :disabled="disabled"
      :aria-expanded="open" aria-haspopup="menu" title="download this table" @click="open = !open">↓ download</button>
    <template v-if="open">
      <div class="fixed inset-0 z-40" @click="open = false" />
      <div role="menu" class="absolute right-0 mt-1 z-50 panel py-1 text-sm min-w-36 shadow-lg">
        <button role="menuitem" class="block w-full text-left px-3 py-2 md:py-1.5 hover:bg-hover" @click="pick('csv')">CSV</button>
        <button role="menuitem" class="block w-full text-left px-3 py-2 md:py-1.5 hover:bg-hover" @click="pick('xlsx')">Excel (.xlsx)</button>
      </div>
    </template>
  </div>
</template>
