<script setup lang="ts">
import { computed } from "vue"
import AccountSection from "@/components/settings/AccountSection.vue"
import OrderflowSection from "@/components/settings/OrderflowSection.vue"
import PhoneAlerts from "@/components/settings/PhoneAlerts.vue"
import SharesSection from "@/components/settings/SharesSection.vue"
import UsersSection from "@/components/settings/UsersSection.vue"
import { FIATS } from "@/lib/fiat"
import { features } from "@/lib/features"
import { GAUGES } from "@/lib/gauges"
import { useAuth } from "@/stores/auth"
import { useSettings } from "@/stores/settings"

// settings saved on the server: same on every device
const settings = useSettings()
const auth = useAuth()
const groups = computed(() => (["server", "bot", "risk", "market"] as const).map((group) => ({ g: group, items: GAUGES.filter((gauge) => gauge.group === group) })))
const groupTitle: Record<string, string> = { server: "Server", bot: "Bot", risk: "Risk", market: "Market" }

// turning pop-ups on asks the browser for permission (once per browser)
async function toggleBrowser() {
  const alerts = settings.s!.alerts
  if (!alerts.browser && "Notification" in window && Notification.permission === "default") await Notification.requestPermission()
  alerts.browser = !alerts.browser
}

function num(value: string) {
  return value === "" ? null : Number(value)
}
</script>

<template>
  <div class="max-w-5xl space-y-4">
    <div class="flex items-center gap-3">
      <h1 class="text-xl font-semibold">Settings</h1>
      <span class="text-sm text-dim hidden sm:inline">saved on the server automatically, same on every device</span>
      <span class="ml-auto text-sm num" :class="settings.error ? 'text-down' : settings.saving ? 'text-dim' : 'text-up'">
        {{ settings.error ? "✕ not saved" : settings.saving ? "Saving…" : settings.savedAt ? `✓ Saved ${settings.savedAt.toLocaleTimeString("en-GB")}` : "changes save automatically" }}
      </span>
    </div>
    <div v-if="settings.error" class="panel p-3 text-sm text-down">{{ settings.error }}</div>
    <div v-if="!auth.isAdmin" class="panel p-3 text-sm text-dim">You're a viewer: settings below are shown, but only an admin can change them.</div>

    <AccountSection />
    <PhoneAlerts />
    <UsersSection v-if="auth.isAdmin" />
    <SharesSection v-if="auth.isAdmin" />

    <fieldset v-if="settings.s" :disabled="!auth.isAdmin" class="space-y-4 disabled:opacity-70">
      <section class="panel p-4">
        <div class="panel-title mb-3">General</div>
        <div class="grid gap-4 sm:grid-cols-2">
          <label class="text-sm text-dim">Times shown in
            <select v-model="settings.s.timezone" class="mt-1 w-full rounded-md bg-raised border border-line px-2 py-1.5 text-ink">
              <option value="utc">UTC</option><option value="local">Local time</option>
            </select>
          </label>
          <label class="text-sm text-dim">Trading day starts at
            <select v-model="settings.s.day_boundary" class="mt-1 w-full rounded-md bg-raised border border-line px-2 py-1.5 text-ink">
              <option value="utc">00:00 UTC</option><option value="freqtrade">freqtrade's day</option>
            </select>
          </label>
          <label class="text-sm text-dim">Also show USDT money in
            <select v-model="settings.s.fiat" class="mt-1 w-full rounded-md bg-raised border border-line px-2 py-1.5 text-ink">
              <option :value="null">off</option><option v-for="currency in FIATS" :key="currency" :value="currency">{{ currency }}</option>
            </select>
            <span class="block text-xs text-faint mt-1">at the live USDT market rate (Kraken; BTC Markets backup for AUD), equity and P&amp;L cards</span>
          </label>
        </div>
        <div class="mt-4 flex items-center gap-3">
          <button role="switch" :aria-checked="!!settings.s.colorblind" class="toggle" :class="{ on: settings.s.colorblind }"
            @click="settings.s.colorblind = !settings.s.colorblind"><span /></button>
          <div class="text-sm">Colour-blind safe colours <span class="text-xs text-dim">up / down in blue / orange instead of green / red; open charts change when reloaded</span></div>
        </div>
      </section>

      <section class="panel p-4">
        <div class="panel-title">Alerts</div>
        <p class="text-xs text-dim mt-1 mb-3">nfiforge checks every bot every 15 s and raises an alert while one of these holds; they show on the
          Notifications page with a count in the menu</p>
        <div class="grid gap-4 sm:grid-cols-2">
          <label class="text-sm text-dim">Bot API unreachable for (seconds)
            <input v-model.number="settings.s.alerts.api_down_s" type="number" min="0" class="mt-1 w-full rounded-md bg-raised border border-line px-2 py-1.5 num text-ink" /></label>
          <label class="text-sm text-dim">No bot loop for (minutes)
            <input v-model.number="settings.s.alerts.stuck_min" type="number" min="1" class="mt-1 w-full rounded-md bg-raised border border-line px-2 py-1.5 num text-ink" /></label>
          <label class="text-sm text-dim">Open trade closer to liquidation than (%)
            <input v-model.number="settings.s.alerts.liq_pct" type="number" min="0" step="any" class="mt-1 w-full rounded-md bg-raised border border-line px-2 py-1.5 num text-ink" /></label>
          <label class="text-sm text-dim">Drawdown above (%)
            <input v-model.number="settings.s.alerts.drawdown_pct" type="number" min="0" step="any" class="mt-1 w-full rounded-md bg-raised border border-line px-2 py-1.5 num text-ink" /></label>
          <label class="text-sm text-dim">Server disk fuller than (%)
            <input v-model.number="settings.s.alerts.disk_pct" type="number" min="0" max="100" class="mt-1 w-full rounded-md bg-raised border border-line px-2 py-1.5 num text-ink" /></label>
          <label class="text-sm text-dim">Server RAM fuller than (%)
            <input v-model.number="settings.s.alerts.ram_pct" type="number" min="0" max="100" class="mt-1 w-full rounded-md bg-raised border border-line px-2 py-1.5 num text-ink" /></label>
          <label class="text-sm text-dim">Container closer to its memory limit than (%)
            <input v-model.number="settings.s.alerts.container_mem_pct" type="number" min="0" max="100" class="mt-1 w-full rounded-md bg-raised border border-line px-2 py-1.5 num text-ink" /></label>
        </div>
        <p class="text-xs text-faint mt-2">containers killed for running out of memory, or restarted, always alert</p>
        <div class="mt-4 space-y-3">
          <div class="flex items-center gap-3">
            <button role="switch" :aria-checked="settings.s.alerts.trade_events" class="toggle" :class="{ on: settings.s.alerts.trade_events }"
              @click="settings.s.alerts.trade_events = !settings.s.alerts.trade_events"><span /></button>
            <div class="text-sm">Keep trade events <span class="text-xs text-dim">fills, cancels, protection locks, bot warnings</span></div>
          </div>
          <div class="flex items-center gap-3">
            <button role="switch" :aria-checked="settings.s.alerts.browser" class="toggle" :class="{ on: settings.s.alerts.browser }" @click="toggleBrowser"><span /></button>
            <div class="text-sm">Desktop pop-ups for alerts <span class="text-xs text-dim">while an NFIForge tab is open; this browser asks once</span></div>
          </div>
        </div>
      </section>

      <section class="panel p-4">
        <div class="panel-title">Gauges</div>
        <p class="text-xs text-dim mt-1 mb-3">switch each gauge on or off; warn / danger set where the amber and red zones start</p>
        <div v-for="grp in groups" :key="grp.g" class="mb-4 last:mb-0">
          <div class="text-[11px] font-semibold tracking-widest text-faint mb-1">{{ groupTitle[grp.g].toUpperCase() }}</div>
          <div v-for="gauge in grp.items" :key="gauge.id"
            class="grid grid-cols-[auto_1fr] sm:grid-cols-[auto_1fr_7.5rem_7rem_7rem] items-center gap-x-4 gap-y-2 py-2 border-b border-line last:border-0">
            <button role="switch" :aria-checked="settings.s.gauges[gauge.id]?.enabled" class="toggle" :class="{ on: settings.s.gauges[gauge.id]?.enabled }"
              @click="settings.s.gauges[gauge.id].enabled = !settings.s.gauges[gauge.id].enabled"><span /></button>
            <div>
              <div class="text-sm">{{ gauge.label }} <span class="text-faint text-xs">{{ gauge.unit }}</span></div>
              <div class="text-xs text-dim">{{ gauge.hint }}</div>
            </div>
            <div class="col-start-2 sm:col-start-auto flex rounded-md border border-line overflow-hidden text-xs w-fit">
              <button v-for="opt in (['analog', 'segment'] as const)" :key="opt" class="px-2.5 py-1"
                :class="(settings.s.gauges[gauge.id].style ?? gauge.style) === opt ? 'bg-hover text-ink' : 'text-dim hover:text-ink'"
                @click="settings.s.gauges[gauge.id].style = opt">{{ opt === "analog" ? "Analog" : "Digital" }}</button>
            </div>
            <label class="col-start-2 sm:col-start-auto text-xs text-dim flex items-center gap-2">warn
              <input type="number" step="any" class="w-full rounded-md bg-raised border border-line px-2 py-1 num text-warn"
                :value="settings.s.gauges[gauge.id]?.warn ?? ''" @input="settings.s.gauges[gauge.id].warn = num(($event.target as HTMLInputElement).value)" />
            </label>
            <label class="col-start-2 sm:col-start-auto text-xs text-dim flex items-center gap-2">danger
              <input type="number" step="any" class="w-full rounded-md bg-raised border border-line px-2 py-1 num text-down"
                :value="settings.s.gauges[gauge.id]?.danger ?? ''" @input="settings.s.gauges[gauge.id].danger = num(($event.target as HTMLInputElement).value)" />
            </label>
          </div>
        </div>
      </section>

      <OrderflowSection v-if="features.orderflow" />
    </fieldset>
  </div>
</template>

