<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { SECTIONS, useAuth, type Access, type Section } from "@/stores/auth"
import { useLive } from "@/stores/live"

// admins: who can sign in. viewers change nothing (no settings, layouts or bots), and see what Access allows
type Row = { id: number; username: string; role: "admin" | "viewer"; disabled: boolean; sessions: number; access: Access }
const auth = useAuth()
const live = useLive()
const users = ref<Row[]>([])
const msg = ref("")
const name = ref("")
const password = ref("")
const role = ref<"admin" | "viewer">("viewer")

async function load() {
  const response = await fetch("/api/users").catch(() => null)
  if (response?.ok) users.value = await response.json()
}
onMounted(load)

async function call(path: string, method: string, body?: object) {
  const response = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) }).catch(() => null)
  const result = response ? await response.json().catch(() => ({})) : {}
  msg.value = response?.ok ? "" : (result.detail ?? "NFIForge isn't reachable")
  if (response?.ok) await load()
  return !!response?.ok
}
async function add() {
  if (await call("/api/users", "POST", { username: name.value.trim(), password: password.value, role: role.value })) name.value = password.value = ""
}
function reset(user: Row) {
  const newPassword = prompt(`New password for ${user.username} (10+ characters)`)
  if (newPassword) call(`/api/users/${user.id}`, "PUT", { password: newPassword })
}

// ===========================================================================
// ACCESS (viewers): which bots, which pages with their own data, or the percent view only
// ===========================================================================
const PAGE_LABEL: Record<Section, string> = { radar: "Signal Radar", orderflow: "Order Flow", btcgate: "BTCGate", logs: "Logs", server: "Server", notifications: "Notifications" }
const botNames = computed(() => Object.keys(live.bots))
const editing = ref<number | null>(null)
const draft = ref<Access>({ bots: null, pages: null, percent: false })
function edit(user: Row) {
  editing.value = editing.value === user.id ? null : user.id
  draft.value = { bots: user.access.bots ? [...user.access.bots] : null, pages: user.access.pages ? [...user.access.pages] : null, percent: user.access.percent }
}
function toggle<T>(list: T[] | null, all: T[], value: T): T[] | null {
  const now = list ?? [...all]
  const next = now.includes(value) ? now.filter((item) => item !== value) : [...now, value]
  return all.every((item) => next.includes(item)) ? null : next  // everything ticked = all, including ones added later
}
async function saveAccess(user: Row) {
  if (await call(`/api/users/${user.id}`, "PUT", { access: draft.value })) editing.value = null
}
function sees(access: Access) {
  if (access.percent) return "percent view only"
  const botsText = access.bots === null ? "all bots" : access.bots.length ? access.bots.join(", ") : "no bots"
  const pagesText = access.pages === null ? "all pages" : access.pages.length ? `+ ${access.pages.map((page) => PAGE_LABEL[page]).join(", ")}` : "core pages only"
  return `${botsText} · ${pagesText}`
}
function remove(user: Row) {
  if (confirm(`Remove ${user.username}? They are signed out straight away.`)) call(`/api/users/${user.id}`, "DELETE")
}
</script>

<template>
  <section class="panel p-4">
    <div class="panel-title">Users</div>
    <p class="text-xs text-dim mt-1 mb-3">admins change settings, layouts and bots; viewers only look, at what "Sees" allows. Passwords are stored as scrypt hashes.</p>
    <div class="overflow-auto">
      <table class="w-full text-sm">
        <thead class="text-xs text-faint text-left"><tr><th class="py-1">User</th><th>Role</th><th>Sees</th><th>Signed in on</th><th /></tr></thead>
        <tbody>
          <template v-for="user in users" :key="user.id">
          <tr class="border-t border-line" :class="{ 'opacity-50': user.disabled }">
            <td class="py-2">{{ user.username }} <span v-if="user.id === auth.user?.id" class="text-faint text-xs">you</span>
              <span v-if="user.disabled" class="text-warn text-xs">blocked</span></td>
            <td>
              <select :value="user.role" class="rounded-md bg-raised border border-line px-1.5 py-0.5 text-ink text-xs"
                @change="call(`/api/users/${user.id}`, 'PUT', { role: ($event.target as HTMLSelectElement).value })">
                <option value="admin">admin</option><option value="viewer">viewer</option>
              </select>
            </td>
            <td class="text-xs text-dim max-w-64">
              <span v-if="user.role === 'admin'">everything</span>
              <button v-else class="text-left hover:text-ink" title="change what this viewer sees" @click="edit(user)">{{ sees(user.access) }} ✎</button>
            </td>
            <td class="num text-dim">{{ user.sessions }} device{{ user.sessions === 1 ? "" : "s" }}</td>
            <td class="text-right md:whitespace-nowrap text-xs space-x-3 leading-7">
              <button class="text-dim hover:text-ink" @click="reset(user)">new password</button>
              <template v-if="user.id !== auth.user?.id">
                <button class="text-dim hover:text-ink" @click="call(`/api/users/${user.id}/logout`, 'POST')">sign out</button>
                <button class="text-dim hover:text-ink" @click="call(`/api/users/${user.id}`, 'PUT', { disabled: !user.disabled })">{{ user.disabled ? "unblock" : "block" }}</button>
                <button class="text-dim hover:text-down" @click="remove(user)">remove</button>
              </template>
            </td>
          </tr>
          <tr v-if="editing === user.id && user.role === 'viewer'">
            <td colspan="5" class="pb-3">
              <div class="rounded-md border border-line bg-raised p-3 space-y-3 text-sm">
                <label class="flex items-center gap-3">
                  <button type="button" role="switch" :aria-checked="draft.percent" class="toggle" :class="{ on: draft.percent }" @click="draft.percent = !draft.percent"><span /></button>
                  <span>Percent view only <span class="text-xs text-dim">results in % for the bots below; no balances, amounts or prices anywhere</span></span>
                </label>
                <div>
                  <div class="text-xs text-faint mb-1">Bots <span class="text-dim">(all ticked = every bot, also ones added later)</span></div>
                  <div class="flex flex-wrap gap-x-4 gap-y-1">
                    <label v-for="name in botNames" :key="name" class="flex items-center gap-1.5">
                      <input type="checkbox" :checked="draft.bots === null || draft.bots.includes(name)" @change="draft.bots = toggle(draft.bots, botNames, name)" /> {{ name }}</label>
                  </div>
                </div>
                <div v-if="!draft.percent">
                  <div class="text-xs text-faint mb-1">Pages with their own data <span class="text-dim">(Trading, Positions, Chart, History, Analytics, Pairs and Bot Health come with the bots)</span></div>
                  <div class="flex flex-wrap gap-x-4 gap-y-1">
                    <label v-for="page in SECTIONS" :key="page" class="flex items-center gap-1.5">
                      <input type="checkbox" :checked="draft.pages === null || draft.pages.includes(page)" @change="draft.pages = toggle(draft.pages, [...SECTIONS], page)" /> {{ PAGE_LABEL[page] }}</label>
                  </div>
                </div>
                <div class="flex gap-3">
                  <button class="px-3 py-1 rounded-md border border-line hover:border-line-bright" @click="saveAccess(user)">Save</button>
                  <button class="text-dim hover:text-ink" @click="editing = null">Cancel</button>
                </div>
              </div>
            </td>
          </tr>
          </template>
        </tbody>
      </table>
    </div>
    <form class="grid gap-3 sm:grid-cols-[1fr_1fr_auto_auto] items-end mt-4" @submit.prevent="add">
      <label class="text-sm text-dim">Username
        <input v-model="name" autocomplete="off" required class="mt-1 w-full rounded-md bg-raised border border-line px-2 py-1.5 text-ink" /></label>
      <label class="text-sm text-dim">Password <span class="text-faint text-xs">10+ characters</span>
        <input v-model="password" type="password" autocomplete="new-password" minlength="10" required class="mt-1 w-full rounded-md bg-raised border border-line px-2 py-1.5 text-ink" /></label>
      <select v-model="role" class="rounded-md bg-raised border border-line px-2 py-1.5 text-ink text-sm">
        <option value="viewer">viewer</option><option value="admin">admin</option>
      </select>
      <button class="px-3 py-1.5 rounded-md border border-line hover:border-line-bright text-sm">Add user</button>
    </form>
    <div v-if="msg" class="text-sm text-down mt-2">{{ msg }}</div>
    <p class="text-xs text-faint mt-3">a phone sign-in link for any user: <span class="num">./install.sh --phone</span></p>
  </section>
</template>
