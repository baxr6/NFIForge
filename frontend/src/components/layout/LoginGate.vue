<script setup lang="ts">
import { ref } from "vue"
import { useAuth } from "@/stores/auth"

// sign-in screen; with no accounts yet it says how to make the first one (there is no web setup on purpose:
// anyone who reached it first would own the dashboard)
const props = defineProps<{ note?: string }>()
const auth = useAuth()
const username = ref("")
const password = ref("")
const error = ref(props.note ?? "")
const busy = ref(false)

async function submit() {
  busy.value = true
  error.value = await auth.login(username.value.trim(), password.value)
  busy.value = false
  if (!error.value) location.reload()
}
</script>

<template>
  <div class="h-full grid place-items-center p-4">
    <form class="panel p-6 w-full max-w-sm space-y-4" @submit.prevent="submit">
      <div class="flex items-center gap-2">
        <div class="h-6 w-6 rounded-md" style="background: linear-gradient(135deg, var(--brand-a), var(--brand-b))" />
        <span class="font-semibold">NFIForge</span>
      </div>
      <template v-if="auth.hasUsers">
        <input v-model="username" autocomplete="username" placeholder="username" autofocus required
          class="w-full rounded-md bg-raised border border-line px-3 py-2 text-ink" />
        <input v-model="password" type="password" autocomplete="current-password" placeholder="password" required
          class="w-full rounded-md bg-raised border border-line px-3 py-2 text-ink" />
        <div v-if="error" class="text-sm text-down">{{ error }}</div>
        <button :disabled="busy" class="w-full rounded-md py-2 font-semibold text-white disabled:opacity-60" style="background: linear-gradient(135deg, var(--brand-a), var(--brand-b))">Sign in</button>
        <p class="text-xs text-faint">On a phone: <span class="num">./install.sh --phone</span> gives a sign-in link.</p>
      </template>
      <template v-else>
        <p class="text-sm text-dim">No accounts yet. On the computer NFIForge runs on, make the first admin:</p>
        <pre class="text-xs num bg-raised border border-line rounded-md p-2 overflow-auto">./install.sh --add-user</pre>
        <button type="button" class="w-full rounded-md py-2 border border-line text-dim hover:text-ink" @click="auth.status()">I've made one</button>
      </template>
    </form>
  </div>
</template>
