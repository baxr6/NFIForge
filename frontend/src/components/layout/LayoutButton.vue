<script setup lang="ts">
import { useAuth } from "@/stores/auth"

// "Edit layout" toggle for a page header (desktop only: phones get the stacked view)
const editing = defineModel<boolean>({ default: false })
const auth = useAuth()
</script>

<template>
  <button v-if="auth.isAdmin" class="hidden lg:inline-flex items-center gap-1.5 px-3 py-1 rounded-md text-xs border"
    :class="editing ? 'border-brand-b text-ink bg-hover' : 'border-line text-dim hover:text-ink hover:border-line-bright'" @click="editing = !editing">
    {{ editing ? "✓ Done" : "⠿ Edit layout" }}
  </button>
</template>
