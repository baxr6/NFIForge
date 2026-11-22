<script setup lang="ts">
import { ref } from "vue"
import { useAuth } from "@/stores/auth"

// your own account: change password (signs out your other devices), sign out everywhere
const auth = useAuth()
const current = ref("")
const fresh = ref("")
const msg = ref("")
const ok = ref(false)

async function change() {
  const result = await auth.post("/api/auth/password", { current: current.value, new: fresh.value })
  ok.value = result.ok
  msg.value = result.ok ? "password changed, other devices signed out" : result.error
  if (result.ok) current.value = fresh.value = ""
}
</script>

<template>
  <section class="panel p-4">
    <div class="panel-title">Account</div>
    <p class="text-xs text-dim mt-1 mb-3">signed in as <span class="text-ink">{{ auth.user?.username }}</span> ({{ auth.user?.role }})</p>
    <form class="grid gap-3 sm:grid-cols-[1fr_1fr_auto] items-end" @submit.prevent="change">
      <label class="text-sm text-dim">Current password
        <input v-model="current" type="password" autocomplete="current-password" required class="mt-1 w-full rounded-md bg-raised border border-line px-2 py-1.5 text-ink" /></label>
      <label class="text-sm text-dim">New password <span class="text-faint text-xs">10+ characters</span>
        <input v-model="fresh" type="password" autocomplete="new-password" minlength="10" required class="mt-1 w-full rounded-md bg-raised border border-line px-2 py-1.5 text-ink" /></label>
      <button class="px-3 py-1.5 rounded-md border border-line hover:border-line-bright text-sm">Change password</button>
    </form>
    <div v-if="msg" class="text-sm mt-2" :class="ok ? 'text-up' : 'text-down'">{{ msg }}</div>
    <button class="mt-4 text-sm text-dim hover:text-ink underline" @click="auth.logout(true)">Sign out on every device</button>
  </section>
</template>
