<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { useLive } from "@/stores/live"

// admins: share links. anyone with a link sees the chosen bots' results in percent only, without an account
// (docs/SHARING.md). the link is shown once when made; only a hash of it is kept
type Opts = { positions: boolean; trades: boolean; tags: boolean; names: boolean }
type Row = { id: number; name: string; bots: string[]; opts: Opts; created: number; expires: number | null; last_seen: number | null; opens: number }
const live = useLive()
const botNames = computed(() => Object.keys(live.bots))
const links = ref<Row[]>([])
const msg = ref("")
const made = ref("")
const copied = ref(false)
const form = ref({ name: "", bots: [] as string[], days: "" as string | number, positions: true, trades: true, tags: false, names: false })
const SWITCHES: [keyof Opts, string][] = [["positions", "open trades"], ["trades", "latest closed trades"], ["tags", "entry tags and exit reasons"], ["names", "bot names and exchange (else Bot 1, Bot 2)"]]

async function load() {
  const response = await fetch("/api/manage/shares").catch(() => null)
  if (response?.ok) links.value = await response.json()
}
onMounted(load)

async function add() {
  const draft = form.value
  const body = { ...draft, name: draft.name.trim(), bots: draft.bots.length ? draft.bots : botNames.value, days: draft.days === "" ? null : Number(draft.days) }
  const response = await fetch("/api/manage/shares", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).catch(() => null)
  const result = response ? await response.json().catch(() => ({})) : {}
  msg.value = response?.ok ? "" : (result.detail ?? "NFIForge isn't reachable")
  if (!response?.ok) return
  made.value = location.origin + result.path
  copied.value = false
  form.value.name = ""
  load()
}
async function copy() {
  try { await navigator.clipboard.writeText(made.value); copied.value = true } catch { copied.value = false }
}
async function revoke(link: Row) {
  if (!confirm(`Revoke "${link.name}"? The link stops working straight away.`)) return
  const response = await fetch(`/api/manage/shares/${link.id}`, { method: "DELETE" }).catch(() => null)
  msg.value = response?.ok ? "" : "couldn't revoke it"
  load()
}
const day = (seconds: number | null) => (seconds ? new Date(seconds * 1000).toLocaleDateString("en-GB") : "")
const shows = (options: Opts) => SWITCHES.filter(([key]) => options[key]).map(([, label]) => label.split(" (")[0]).join(", ") || "summary only"
</script>

<template>
  <section class="panel p-4">
    <div class="panel-title">Share links</div>
    <p class="text-xs text-dim mt-1 mb-3">a page anyone with the link can open without an account: the chosen bots' results in percent only (no balances,
      amounts or prices). NFIForge must be reachable for them, e.g. through your reverse proxy or tunnel.</p>

    <div v-if="made" class="rounded-md border border-line bg-raised p-3 mb-3 text-sm space-y-2">
      <div class="text-warn text-xs">copy it now: the link is shown only this once</div>
      <div class="flex flex-wrap items-center gap-2">
        <input :value="made" readonly class="flex-1 min-w-0 rounded-md bg-panel border border-line px-2 py-1.5 num text-xs text-ink" @focus="($event.target as HTMLInputElement).select()" />
        <button class="px-3 py-1.5 rounded-md border border-line hover:border-line-bright text-xs" @click="copy">{{ copied ? "✓ copied" : "copy" }}</button>
        <a :href="made" target="_blank" rel="noopener noreferrer" class="text-xs text-dim hover:text-ink">open ↗</a>
        <button class="text-xs text-dim hover:text-ink" @click="made = ''">done</button>
      </div>
    </div>

    <div v-if="links.length" class="overflow-auto mb-4">
      <table class="w-full text-sm">
        <thead class="text-xs text-faint text-left"><tr><th class="py-1">Name</th><th>Bots</th><th>Shows</th><th>Expires</th><th>Opened</th><th /></tr></thead>
        <tbody>
          <tr v-for="link in links" :key="link.id" class="border-t border-line" :class="{ 'opacity-50': link.expires && link.expires * 1000 < Date.now() }">
            <td class="py-2">{{ link.name }}</td>
            <td class="text-dim text-xs">{{ link.bots.join(", ") }}</td>
            <td class="text-dim text-xs">{{ shows(link.opts) }}</td>
            <td class="text-dim text-xs num">{{ link.expires ? (link.expires * 1000 < Date.now() ? "expired" : day(link.expires)) : "never" }}</td>
            <td class="text-dim text-xs num">{{ link.opens }}×<template v-if="link.last_seen">, last {{ day(link.last_seen) }}</template></td>
            <td class="text-right text-xs"><button class="text-dim hover:text-down" @click="revoke(link)">revoke</button></td>
          </tr>
        </tbody>
      </table>
    </div>

    <form class="space-y-3 text-sm" @submit.prevent="add">
      <div class="grid gap-3 sm:grid-cols-[1fr_10rem_auto] items-end">
        <label class="text-dim">Name <span class="text-faint text-xs">for this list, and the page's title</span>
          <input v-model="form.name" maxlength="60" required class="mt-1 w-full rounded-md bg-raised border border-line px-2 py-1.5 text-ink" /></label>
        <label class="text-dim">Expires after (days)
          <input v-model="form.days" type="number" min="1" max="3650" placeholder="never" class="mt-1 w-full rounded-md bg-raised border border-line px-2 py-1.5 num text-ink" /></label>
        <button class="px-3 py-1.5 rounded-md border border-line hover:border-line-bright">Make link</button>
      </div>
      <div>
        <div class="text-xs text-faint mb-1">Bots <span class="text-dim">(none ticked = all of them)</span></div>
        <div class="flex flex-wrap gap-x-4 gap-y-1">
          <label v-for="name in botNames" :key="name" class="flex items-center gap-1.5"><input v-model="form.bots" type="checkbox" :value="name" /> {{ name }}</label>
        </div>
      </div>
      <div>
        <div class="text-xs text-faint mb-1">Besides the summary, growth line and daily calendar, show</div>
        <div class="flex flex-wrap gap-x-4 gap-y-1">
          <label v-for="[key, label] in SWITCHES" :key="key" class="flex items-center gap-1.5"><input v-model="form[key]" type="checkbox" /> {{ label }}</label>
        </div>
      </div>
    </form>
    <div v-if="msg" class="text-sm text-down mt-2">{{ msg }}</div>
  </section>
</template>
