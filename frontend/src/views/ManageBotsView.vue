<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useLive } from "@/stores/live"

// which bots NFIForge watches: add / edit / remove without touching files; bots from config.yaml are listed but locked
const live = useLive()
type Row = { name: string; url: string; username: string; source: "config" | "ui"; trading: boolean; radar: boolean; container: string | null }
const rows = ref<Row[]>([])
const whyNot = ref<string | null>(null)
const writeActions = ref(false)
const blank = () => ({ name: "", url: "http://127.0.0.1:8080", username: "freqtrader", password: "", trading: false, radar: false, container: "" })
const form = ref(blank())
const editing = ref<string | null>(null)  // name of the bot being edited, null = adding
const open = ref(false)
const msg = ref<{ ok: boolean; text: string } | null>(null)
const busy = ref(false)

async function load() {
  const response = await fetch("/api/manage/bots").catch(() => null)
  if (response?.ok) { const result = await response.json(); rows.value = result.bots; whyNot.value = result.why_not; writeActions.value = result.write_actions }
}
onMounted(load)

function startAdd() { form.value = blank(); editing.value = null; msg.value = null; open.value = true }
function startEdit(bot: Row) { form.value = { name: bot.name, url: bot.url, username: bot.username, password: "", trading: bot.trading, radar: bot.radar, container: bot.container ?? "" }; editing.value = bot.name; msg.value = null; open.value = true }

async function call(method: string, path: string, body?: object) {
  const response = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined })
  const result = await response.json().catch(() => ({}))
  return { ok: response.ok, d: result }
}
async function test() {
  busy.value = true
  const { ok, d: result } = await call("POST", "/api/manage/bots/test", { ...form.value, name: editing.value ?? form.value.name })
  msg.value = ok ? { ok: result.ok, text: result.message } : { ok: false, text: result.detail ?? "test failed" }
  busy.value = false
}
async function save() {
  busy.value = true
  const { ok, d: result } = editing.value
    ? await call("PUT", `/api/manage/bots/${encodeURIComponent(editing.value)}`, form.value)
    : await call("POST", "/api/manage/bots", form.value)
  busy.value = false
  if (!ok) { msg.value = { ok: false, text: result.detail ?? "could not save" }; return }
  open.value = false
  live.picked = result.name
  load()
}
async function remove(name: string) {
  if (!confirm(`Remove ${name} from NFIForge? The bot itself keeps running.`)) return
  await call("DELETE", `/api/manage/bots/${encodeURIComponent(name)}`)
  load()
}
// reset what NFIForge kept for a bot (one started on a fresh database); the bot itself is not touched
const PARTS = [
  ["equity", "Equity history", "the wallet + open profit line"],
  ["notes", "Notifications", "alerts and trade messages"],
  ["excursions", "Trade highs / lows", "best and worst move of each closed trade"],
  ["logs", "Logs", "log lines, events and whitelist changes kept since NFIForge started"],
  ["radar", "Signal radar", "signals and guard history"],
  ["loops", "Loop times", "the bot's loop time history on Server"],
] as const
const resetting = ref<string | null>(null)
const counts = ref<Record<string, number>>({})
const picked = ref<string[]>([])
const resetMsg = ref<string | null>(null)
async function startReset(name: string) {
  resetMsg.value = null
  const { ok, d: result } = await call("GET", `/api/manage/bots/${encodeURIComponent(name)}/data`)
  if (!ok) { resetMsg.value = result.detail ?? "could not read"; return }
  counts.value = result.counts
  picked.value = PARTS.map((part) => part[0])
  resetting.value = name
}
async function doReset() {
  const name = resetting.value
  if (!name) return
  const what = PARTS.filter((part) => picked.value.includes(part[0])).map((part) => part[1].toLowerCase())
  if (what.length && !confirm(`Delete ${what.join(", ")} for ${name}? This can't be undone. The bot itself is not touched.`)) return
  busy.value = true
  const { ok, d: result } = await call("POST", `/api/manage/bots/${encodeURIComponent(name)}/reset`, { parts: picked.value })
  busy.value = false
  if (!ok) { resetMsg.value = result.detail ?? "reset failed"; return }
  resetting.value = null
  const total = Object.values(result.cleared as Record<string, number>).reduce((a, b) => a + b, 0)
  resetMsg.value = what.length ? `${name}: cleared ${total.toLocaleString()} rows` : `${name}: kept everything, current database remembered`
}
const inp = "mt-1 w-full rounded-md bg-raised border border-line px-2 py-1.5 text-ink"
</script>

<template>
  <div class="max-w-5xl space-y-3">
    <div class="flex flex-wrap items-baseline gap-3">
      <h1 class="text-xl font-semibold">Manage Bots</h1>
      <span class="text-sm text-dim">the bots NFIForge watches; it only trades on bots with trading on</span>
    </div>
    <section class="panel p-4">
      <div class="flex items-baseline gap-3">
        <div class="panel-title">Bots</div>
        <button v-if="!whyNot && !open" class="ml-auto text-xs px-3 py-1 rounded-md border border-line text-dim hover:text-ink" @click="startAdd">+ add bot</button>
      </div>
      <p v-if="whyNot" class="text-xs text-warn mt-1">{{ whyNot }}</p>
      <p v-if="!writeActions" class="text-xs text-faint mt-1">trade actions are off for every bot: set <span class="num">write_actions: true</span> in config.yaml and restart NFIForge to allow them</p>

      <div class="mt-3">
        <div v-for="bot in rows" :key="bot.name" class="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 border-b border-line last:border-0">
          <span class="h-2 w-2 rounded-full" :class="live.bots[bot.name]?.connected ? 'bg-up' : 'bg-down'" />
          <span class="font-semibold">{{ bot.name }}</span>
          <span class="text-xs text-dim num">{{ bot.username }} @ {{ bot.url }}</span>
          <span v-if="live.bots[bot.name]?.error" class="text-xs text-down basis-full pl-5">{{ live.bots[bot.name].error }}</span>
          <span v-if="bot.container" class="text-[11px] px-1.5 rounded border border-line text-dim font-mono" title="docker container">{{ bot.container }}</span>
          <span v-if="bot.radar" class="text-[11px] px-1.5 rounded border border-brand-b/50 text-brand-b" title="signal radar on">radar</span>
          <span v-if="bot.trading" class="text-[11px] px-1.5 rounded border" :class="writeActions ? 'border-warn/60 text-warn' : 'border-line text-faint'" :title="writeActions ? 'admins can enter and exit trades on this bot' : 'off until write_actions: true in config.yaml'">trading on</span>
          <span v-if="live.bots[bot.name]?.fresh_db" class="text-[11px] px-1.5 rounded border border-warn/60 text-warn" title="the bot's old trades are gone: it looks like it started on a new database">new database?</span>
          <span class="ml-auto text-[11px]" :class="bot.source === 'config' ? 'text-faint' : 'text-brand-b'">{{ bot.source === "config" ? "from config file" : "added here" }}</span>
          <button class="text-xs hover:text-ink" :class="live.bots[bot.name]?.fresh_db ? 'text-warn' : 'text-dim'" @click="startReset(bot.name)">reset data</button>
          <template v-if="bot.source === 'ui' && !whyNot">
            <button class="text-xs text-dim hover:text-ink" @click="startEdit(bot)">edit</button>
            <button class="text-xs text-dim hover:text-down" @click="remove(bot.name)">remove</button>
          </template>
        </div>
        <div v-if="!rows.length" class="text-sm text-dim py-2">no bots yet</div>
      </div>
      <p v-if="resetMsg" class="text-xs text-dim mt-2">{{ resetMsg }}</p>

      <div v-if="resetting" class="mt-4 rounded-md border border-line p-3 space-y-2">
        <div class="text-sm font-semibold">Reset NFIForge data for {{ resetting }}</div>
        <p class="text-xs text-faint">for a bot started on a fresh database: clears what NFIForge kept from before. the bot, its trades and its files are not touched. untick everything to keep it all and stop the new-database warning</p>
        <label v-for="[key, label, what] in PARTS" :key="key" class="flex items-start gap-2 text-sm">
          <input v-model="picked" type="checkbox" :value="key" class="mt-1" />
          <span><span class="text-ink">{{ label }}</span> <span class="text-dim num">({{ (counts[key] ?? 0).toLocaleString() }})</span> <span class="text-faint">{{ what }}</span></span>
        </label>
        <div class="flex items-center gap-2 pt-1">
          <button class="text-sm px-3 py-1 rounded-md border disabled:opacity-40" :class="picked.length ? 'border-down/60 text-down' : 'border-line text-dim'" :disabled="busy" @click="doReset">{{ picked.length ? "delete selected" : "keep everything" }}</button>
          <button class="text-sm px-3 py-1 text-dim hover:text-ink" @click="resetting = null">cancel</button>
        </div>
      </div>

      <form v-if="open" class="mt-4 rounded-md border border-line p-3 space-y-3" @submit.prevent="save">
        <div class="text-sm font-semibold">{{ editing ? `Edit ${editing}` : "Add a bot" }}</div>
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="text-sm text-dim">Name<input v-model="form.name" required :class="inp" /></label>
          <label class="text-sm text-dim">API url<input v-model="form.url" required :class="inp" placeholder="http://127.0.0.1:8080" /></label>
          <label class="text-sm text-dim">API username<input v-model="form.username" required :class="inp" autocomplete="off" /></label>
          <label class="text-sm text-dim">Docker container <span class="text-faint">(optional)</span><input v-model="form.container" :class="inp" autocomplete="off" placeholder="freqtrade" /></label>
          <label class="text-sm text-dim">API password
            <input v-model="form.password" type="password" :required="!editing" :class="inp" autocomplete="new-password" :placeholder="editing ? 'leave empty to keep it' : ''" /></label>
        </div>
        <p class="text-xs text-faint">the api_server login from the bot's freqtrade config (the one FreqUI uses); saved in NFIForge's data folder, owner-only</p>
        <label class="flex items-start gap-2 text-sm">
          <input v-model="form.radar" type="checkbox" class="mt-1" />
          <span><span class="text-ink">Signal radar</span> <span class="text-dim">(after each new candle, one small request per whitelisted pair: about 2 s for 100 pairs; watch the bot's loop time on Server after turning it on)</span></span>
        </label>
        <label class="flex items-start gap-2 text-sm">
          <input v-model="form.trading" type="checkbox" class="mt-1" />
          <span><span class="text-ink">Allow trade actions and bot control</span> <span class="text-dim">(admins can force entries, adds and exits, cancel, reload and delete trades, and pause, start, stop or reload the bot; a live bot also needs the coin typed to confirm{{ writeActions ? "" : "; needs write_actions: true in config.yaml" }})</span></span>
        </label>
        <div class="flex items-center gap-2">
          <button type="button" class="text-sm px-3 py-1 rounded-md border border-line text-dim hover:text-ink disabled:opacity-40" :disabled="busy" @click="test">test login</button>
          <button type="submit" class="text-sm px-3 py-1 rounded-md bg-brand-b/20 border border-brand-b/50 text-ink disabled:opacity-40" :disabled="busy">{{ editing ? "save" : "add" }}</button>
          <button type="button" class="text-sm px-3 py-1 text-dim hover:text-ink" @click="open = false">cancel</button>
          <span v-if="msg" class="text-sm" :class="msg.ok ? 'text-up' : 'text-down'">{{ msg.ok ? "✓" : "✕" }} {{ msg.text }}</span>
        </div>
      </form>
    </section>
  </div>
</template>
