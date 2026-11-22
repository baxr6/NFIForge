<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import PanelCard from "@/components/layout/PanelCard.vue"
import { useAuth } from "@/stores/auth"

// btcgate's module switches, telegram alerts and keys. admins change them (the worker restarts, ~15 s), viewers read
type Item = { key: string; label: string; help: string; needs: string[]; on: boolean | null }
type View = {
  sections: { title: string; items: Item[] }[]
  not_yet: { key: string; label: string; why: string }[]
  keys: Record<string, boolean>
  alerts: { enabled: boolean | null; signals: string[] | null; coins: string[] | null; cooldown_min: number | null }
  alert_types: { name: string; label: string; help: string }[]
  push: string[]
  coins: "full" | "bots"
  book_alerts: { max_swing_usd: number; min_bets: number; hours: number }
  running: boolean
}
const auth = useAuth()
const view = ref<View | null>(null)
const switches = ref<Record<string, boolean>>({})
const alerts = ref({ enabled: false, signals: [] as string[], coins: "", cooldown_min: 60 })
const push = ref<string[]>([])
const coins = ref<"full" | "bots">("full")
const bookAlerts = ref({ max_swing_usd: 0, min_bets: 0, hours: 6 })
const secrets = ref<Record<string, string>>({ coinalyze_api_key: "", telegram_token: "", chat_id: "" })
const msg = ref("")
const err = ref("")
const saving = ref(false)

function take(settingsView: View) {
  view.value = settingsView
  switches.value = Object.fromEntries(settingsView.sections.flatMap((section) => section.items.map((item) => [item.key, !!item.on])))
  alerts.value = { enabled: !!settingsView.alerts.enabled, signals: [...(settingsView.alerts.signals ?? [])], coins: (settingsView.alerts.coins ?? []).join(" "), cooldown_min: settingsView.alerts.cooldown_min ?? 60 }
  secrets.value = { coinalyze_api_key: "", telegram_token: "", chat_id: "" }
  push.value = [...(settingsView.push ?? [])]
  coins.value = settingsView.coins ?? "full"
  bookAlerts.value = { ...(settingsView.book_alerts ?? { max_swing_usd: 0, min_bets: 0, hours: 6 }) }
}
onMounted(async () => {
  const response = await fetch("/api/btcgate/settings").catch(() => null)
  if (response?.ok) take(await response.json())
})

const labels = computed(() => Object.fromEntries((view.value?.sections ?? []).flatMap((section) => section.items.map((item) => [item.key, item.label]))))
const telegramOn = computed(() => alerts.value.enabled && (view.value?.keys.telegram_token || !!secrets.value.telegram_token) && (view.value?.keys.chat_id || !!secrets.value.chat_id))
// what's missing for a switch to do anything: other switches off, or a key not set
function missing(item: Item): string[] {
  if (item.key === "ledger.test_signals" && coins.value === "bots") return ["the Full coin list"]
  return item.needs.flatMap((need) => {
    if (need === "telegram") return telegramOn.value ? [] : ["Telegram alerts"]
    if (need === "coinalyze") return view.value?.keys.coinalyze_api_key || secrets.value.coinalyze_api_key ? [] : ["a Coinalyze key"]
    return switches.value[need] ? [] : [labels.value[need] ?? need]
  })
}

async function save() {
  saving.value = true; msg.value = ""; err.value = ""
  const body = {
    switches: switches.value,
    alerts: { ...alerts.value, coins: alerts.value.coins.split(/[\s,]+/).filter(Boolean) },
    secrets: Object.fromEntries(Object.entries(secrets.value).filter(([, value]) => value.trim())),
    push: push.value,
    coins: coins.value,
    book_alerts: bookAlerts.value,
  }
  const response = await fetch("/api/btcgate/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).catch(() => null)
  const result = response ? await response.json().catch(() => ({})) : {}
  saving.value = false
  if (response?.ok) { take(result); msg.value = "saved · the worker restarts to use it (about 15 s, labels back after its next pass)" }
  else err.value = typeof result.detail === "string" ? result.detail : (result.detail?.[0]?.msg ?? "not saved")
}
async function clearKey(name: string) {
  const response = await fetch("/api/btcgate/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ secrets: { [name]: "" } }) }).catch(() => null)
  if (response?.ok) { take(await response.json()); msg.value = "key removed · the worker restarts" }
}
const KEYS = [
  { name: "coinalyze_api_key", label: "Coinalyze API key", help: "for direction (liquidations, crowd, taker)" },
  { name: "telegram_token", label: "Telegram bot token", help: "from @BotFather" },
  { name: "chat_id", label: "Telegram chat id", help: "your chat with the bot" },
]
</script>

<template>
  <div v-if="!view" class="panel p-4 text-sm text-dim">loading…</div>
  <div v-else class="space-y-3">
    <p v-if="!auth.isAdmin" class="text-sm text-dim">Only an admin can change these.</p>
    <p v-if="!view.running" class="text-sm text-warn">The worker hasn't reported its settings yet; switches not saved here show BTCGate's defaults once it has.</p>
    <div class="grid gap-3 md:grid-cols-2">
      <PanelCard v-for="section in view.sections" :key="section.title" :title="section.title">
        <div class="space-y-2 text-sm">
          <label v-for="item in section.items" :key="item.key" class="flex items-start gap-2" :class="auth.isAdmin ? 'cursor-pointer' : ''">
            <input v-model="switches[item.key]" type="checkbox" class="mt-1" :disabled="!auth.isAdmin" />
            <span>
              <span :class="switches[item.key] && missing(item).length ? 'text-dim' : 'text-ink'">{{ item.label }}</span>
              <span v-if="item.help" class="text-dim"> · {{ item.help }}</span>
              <span v-if="switches[item.key] && missing(item).length" class="block text-xs text-warn">does nothing yet: needs {{ missing(item).join(", ") }}</span>
            </span>
          </label>
        </div>
      </PanelCard>
      <PanelCard title="Coin list">
        <div class="space-y-2 text-sm">
          <label class="flex items-start gap-2" :class="auth.isAdmin ? 'cursor-pointer' : ''">
            <input v-model="coins" type="radio" value="full" class="mt-1" :disabled="!auth.isAdmin" />
            <span><span class="text-ink">Full</span> <span class="text-dim">· about 150 coins by Binance volume, the same filters as the research. The signal ledger runs.</span></span>
          </label>
          <label class="flex items-start gap-2" :class="auth.isAdmin ? 'cursor-pointer' : ''">
            <input v-model="coins" type="radio" value="bots" class="mt-1" :disabled="!auth.isAdmin" />
            <span><span class="text-ink">Bots' coins</span> <span class="text-dim">· only what the connected bots can trade, plus BTC. Lighter. The signal ledger pauses (a different set of coins can't be compared).</span></span>
          </label>
          <p class="text-xs text-dim">Either way, the coin of every open trade is added, so open positions always get labels. Coins Binance has no perpetual for show "no Binance data".</p>
        </div>
      </PanelCard>
      <PanelCard title="Alerts">
        <div class="space-y-2 text-sm">
          <p class="text-xs text-dim">Every alert shows in Notifications (BTCGate). Pick where else each type goes.</p>
          <table class="w-full">
            <thead class="text-xs text-dim text-left"><tr><th class="font-normal py-1">Type</th><th class="font-normal px-2">Phone push</th><th class="font-normal px-2">Telegram</th></tr></thead>
            <tbody><tr v-for="alertType in view.alert_types" :key="alertType.name" class="align-top">
              <td class="py-1"><span class="text-ink">{{ alertType.label }}</span> <span class="text-dim">· {{ alertType.help }}</span></td>
              <td class="px-2 py-1 text-center"><input v-model="push" type="checkbox" :value="alertType.name" :disabled="!auth.isAdmin" /></td>
              <td class="px-2 py-1 text-center"><input v-model="alerts.signals" type="checkbox" :value="alertType.name" :disabled="!auth.isAdmin" /></td>
            </tr></tbody>
          </table>
          <p class="text-xs text-dim">Phone push goes to the phones that turned on alerts in Settings → Phone alerts.</p>
          <label class="flex items-center gap-2 pt-1"><input v-model="alerts.enabled" type="checkbox" :disabled="!auth.isAdmin" /> send the Telegram ones</label>
          <p v-if="alerts.enabled && !telegramOn" class="text-xs text-warn">needs the bot token and chat id under Keys</p>
          <label class="block"><span class="text-dim">only these coins (empty = every watched coin)</span>
            <input v-model="alerts.coins" class="mt-1 w-full rounded-md bg-raised border border-line px-2 py-1 text-ink num" placeholder="BTC ETH SOL" :disabled="!auth.isAdmin" /></label>
          <label class="block"><span class="text-dim">at most one alert per coin and type every</span>
            <input v-model.number="alerts.cooldown_min" type="number" min="1" max="1440" class="ml-1 w-20 rounded-md bg-raised border border-line px-2 py-1 text-ink num" :disabled="!auth.isAdmin" /> <span class="text-dim">min</span></label>
        </div>
      </PanelCard>
      <PanelCard title="Book">
        <div class="space-y-2 text-sm">
          <p class="text-xs text-dim">A Book alert for a bot when either is true (0 = off). Where it goes: the Book row under Alerts.</p>
          <label class="block"><span class="text-dim">likely 24 h swing above $</span>
            <input v-model.number="bookAlerts.max_swing_usd" type="number" min="0" class="ml-1 w-28 rounded-md bg-raised border border-line px-2 py-1 text-ink num" :disabled="!auth.isAdmin" /></label>
          <label class="block"><span class="text-dim">6 or more trades behaving like fewer than</span>
            <input v-model.number="bookAlerts.min_bets" type="number" min="0" max="50" step="0.5" class="ml-1 w-20 rounded-md bg-raised border border-line px-2 py-1 text-ink num" :disabled="!auth.isAdmin" /> <span class="text-dim">bets</span></label>
          <label class="block"><span class="text-dim">at most one per bot every</span>
            <input v-model.number="bookAlerts.hours" type="number" min="1" max="168" class="ml-1 w-20 rounded-md bg-raised border border-line px-2 py-1 text-ink num" :disabled="!auth.isAdmin" /> <span class="text-dim">h</span></label>
        </div>
      </PanelCard>
      <PanelCard title="Keys">
        <div class="space-y-3 text-sm">
          <div v-for="keyField in KEYS" :key="keyField.name">
            <div><span class="text-ink">{{ keyField.label }}</span> <span class="text-dim">· {{ keyField.help }}</span>
              <span class="ml-1 text-xs" :class="view.keys[keyField.name] ? 'text-up' : 'text-faint'">{{ view.keys[keyField.name] ? "set" : "not set" }}</span>
              <button v-if="auth.isAdmin && view.keys[keyField.name]" class="ml-2 text-xs text-dim hover:text-down" @click="clearKey(keyField.name)">remove</button></div>
            <input v-if="auth.isAdmin" v-model="secrets[keyField.name]" type="password" autocomplete="off" class="mt-1 w-full rounded-md bg-raised border border-line px-2 py-1 text-ink num"
              :placeholder="view.keys[keyField.name] ? 'set · type to replace' : 'paste here'" />
          </div>
          <p class="text-xs text-dim">Stored owner-only on the server, never shown again.</p>
          <details class="text-xs text-dim">
            <summary class="cursor-pointer hover:text-ink">Setting up Telegram</summary>
            <ol class="mt-1 ml-4 list-decimal space-y-0.5">
              <li>In Telegram, message <span class="text-ink">@BotFather</span>, send <span class="num text-ink">/newbot</span>, pick a name. Use a new bot just for NFIForge: Telegram lets only one program read a bot's messages.</li>
              <li>Paste the token it gives you above and Save.</li>
              <li>Send your new bot any message: it replies with your chat id. Paste that above, tick "send the Telegram ones" under Alerts, Save.</li>
              <li>Then pick which alert types go to Telegram. Commands work in the chat too: /scan, /recovery, /book, /coin, /locks, /help.</li>
            </ol>
          </details>
        </div>
      </PanelCard>
      <PanelCard title="Not available here yet">
        <ul class="space-y-1 text-sm">
          <li v-for="item in view.not_yet" :key="item.key"><span class="text-dim">{{ item.label }}</span> <span class="text-faint">· {{ item.why }}</span></li>
        </ul>
      </PanelCard>
    </div>
    <div v-if="auth.isAdmin" class="flex flex-wrap items-center gap-3">
      <button class="px-4 py-1.5 rounded-md border border-brand-b/50 bg-brand-b/20 text-ink disabled:opacity-40" :disabled="saving" @click="save">{{ saving ? "saving…" : "Save" }}</button>
      <span v-if="msg" class="text-sm text-up">{{ msg }}</span>
      <span v-if="err" class="text-sm text-down">{{ err }}</span>
    </div>
  </div>
</template>
