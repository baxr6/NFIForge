<script setup lang="ts">
import StatCard from "@/components/trading/StatCard.vue"
import { age } from "@/lib/format"
import { gb, useServer } from "@/lib/state/server"

// one server number: ram, disk free, network in / out, uptime
const props = defineProps<{ card: "ram" | "disk" | "netin" | "netout" | "up" }>()
const server = useServer()
</script>

<template>
  <StatCard v-if="props.card === 'ram'" label="RAM used" :value="gb(server.h.value.ram_used)" :sub="`of ${gb(server.h.value.ram_total)}`" />
  <StatCard v-else-if="props.card === 'disk'" label="Disk free" :value="gb(server.h.value.disk_free)" :sub="`of ${gb(server.h.value.disk_total)}`" />
  <StatCard v-else-if="props.card === 'netin'" label="Network in" :value="`${(server.h.value.net_rx_kbs ?? 0).toFixed(0)} KB/s`" />
  <StatCard v-else-if="props.card === 'netout'" label="Network out" :value="`${(server.h.value.net_tx_kbs ?? 0).toFixed(0)} KB/s`" />
  <StatCard v-else label="Server up" :value="server.h.value.uptime_s ? age(Date.now() / 1000 - server.h.value.uptime_s) : '–'" />
</template>
