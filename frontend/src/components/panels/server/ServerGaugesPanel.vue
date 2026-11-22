<script setup lang="ts">
import PanelCard from "@/components/layout/PanelCard.vue"
import Gauge from "@/components/gauges/Gauge.vue"
import { useServer } from "@/lib/state/server"

const server = useServer()
</script>

<template>
  <PanelCard>
    <div class="h-full flex flex-wrap justify-center content-center gap-4">
      <Gauge v-for="id in ['cpu', 'ram', 'load', 'disk', 'swap', 'temp']" :key="id" :id="id" :value="server.h.value[id] ?? 0" :size="150" />
    </div>
  </PanelCard>
</template>
