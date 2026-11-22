<script setup lang="ts">
import { useRoute } from "vue-router"
const route = useRoute()
</script>

<template>
  <div class="panel p-6">
    <div class="panel-title">{{ route.meta.label }}</div>
    <p class="text-dim text-sm mt-2">not built yet</p>
  </div>
</template>
