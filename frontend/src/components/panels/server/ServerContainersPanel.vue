<script setup lang="ts">
import PanelCard from "@/components/layout/PanelCard.vue"
import { age } from "@/lib/format"
import { gb, useServer } from "@/lib/state/server"

const server = useServer()
</script>

<template>
  <PanelCard title="Containers" :pad="false">
    <template #actions><span class="text-xs text-faint">cpu is % of one core · restarts since NFIForge started</span></template>
    <table v-if="server.containers.value.length" class="w-full text-sm num">
      <thead class="text-xs text-dim text-left border-b border-line sticky top-0 bg-panel">
        <tr><th class="px-4 py-2 font-normal">runs</th><th class="px-3 py-2 font-normal w-64">memory</th><th class="px-3 py-2 font-normal text-right">cpu</th>
          <th class="px-3 py-2 font-normal text-right">out of memory</th><th class="px-3 py-2 font-normal text-right">up</th><th class="px-4 py-2 font-normal text-right">restarts</th></tr>
      </thead>
      <tbody>
        <tr v-for="container in server.containers.value" :key="container.id" class="border-b border-line last:border-0">
          <td class="px-4 py-1.5"><div class="text-ink truncate max-w-md" :title="container.label">{{ container.label }}</div><div class="text-[11px] text-faint">{{ container.id }}</div></td>
          <td class="px-3 py-1.5">
            <div class="flex items-baseline gap-2"><span>{{ gb(container.mem) }}</span><span class="text-xs text-faint">{{ container.mem_max ? `of ${gb(container.mem_max)}` : "no limit" }}</span></div>
            <div class="h-1.5 rounded bg-line mt-1"><div class="h-full rounded" :style="{ width: Math.min(100, server.memPct(container)) + '%', background: server.barColor(container) }" /></div>
          </td>
          <td class="px-3 py-1.5 text-right" :class="(container.cpu ?? 0) > 90 ? 'text-warn' : ''">{{ container.cpu == null ? "–" : `${container.cpu.toFixed(0)}%` }}</td>
          <td class="px-3 py-1.5 text-right" :class="container.oom_kills ? 'text-down' : 'text-faint'">{{ container.oom_kills || "–" }}</td>
          <td class="px-3 py-1.5 text-right text-dim">{{ container.started ? age(container.started) : "–" }}</td>
          <td class="px-4 py-1.5 text-right" :class="container.restarts ? 'text-warn' : 'text-faint'">{{ container.restarts || "–" }}</td>
        </tr>
      </tbody>
    </table>
    <div v-else class="px-4 pb-4 text-sm text-dim">{{ server.h.value.containers_ok === false ? "no containers found: needs cgroup v2 and the host mounted at /host (install.sh does this)" : "loading…" }}</div>
  </PanelCard>
</template>
