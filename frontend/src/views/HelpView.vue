<script setup lang="ts">
import { marked } from "marked"
import { nextTick, onMounted, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import guide from "../../../docs/HELP.md?raw"

// docs/HELP.md built into the app, so the guide always matches the installed version
const REPO = "https://github.com/baxr6/NFIForge/blob/main/"
const html = marked.parse(guide, { async: false })
const body = ref<HTMLElement>()
const route = useRoute()
const router = useRouter()

// github's heading anchors, so the guide's own contents links work here too
const slug = (text: string) => text.trim().toLowerCase().replace(/[^\w\s-]/g, "").replace(/\s/g, "-")

function jump(id: string) {
  body.value?.querySelector(`[id="${CSS.escape(id)}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" })
}

onMounted(async () => {
  const root = body.value!
  root.querySelectorAll("h1, h2, h3").forEach((heading) => (heading.id = slug(heading.textContent ?? "")))
  // links to other files in the repo go to github, anything outside opens in a new tab
  root.querySelectorAll("a").forEach((link) => {
    const href = link.getAttribute("href") ?? ""
    if (href.startsWith("#")) return
    if (!/^[a-z]+:/i.test(href)) link.href = REPO + (href.startsWith("../") ? href.slice(3) : `docs/${href}`)
    link.target = "_blank"
    link.rel = "noopener"
  })
  await nextTick()
  if (route.hash) jump(decodeURIComponent(route.hash.slice(1)))
})

function click(e: MouseEvent) {
  const link = (e.target as HTMLElement).closest("a")
  const href = link?.getAttribute("href")
  if (!href?.startsWith("#")) return
  e.preventDefault()
  router.replace({ hash: href })
  jump(href.slice(1))
}
</script>

<template>
  <div class="max-w-4xl">
    <article ref="body" class="help panel p-4 sm:p-6" @click="click" v-html="html" />
  </div>
</template>

<style scoped>
.help { line-height: 1.6; overflow-wrap: anywhere; }
.help :deep(h1) { font-size: 1.5rem; font-weight: 600; margin-bottom: 0.75rem; }
.help :deep(h2) { font-size: 1.2rem; font-weight: 600; margin: 2rem 0 0.75rem; padding-top: 1rem; border-top: 1px solid var(--line); scroll-margin-top: 1rem; }
.help :deep(h3) { font-size: 1rem; font-weight: 600; margin: 1.5rem 0 0.5rem; color: var(--text); scroll-margin-top: 1rem; }
.help :deep(p), .help :deep(ul), .help :deep(ol), .help :deep(pre) { margin: 0.6rem 0; color: var(--text-dim); }
.help :deep(strong) { color: var(--text); font-weight: 600; }
.help :deep(ul) { list-style: disc; padding-left: 1.25rem; }
.help :deep(ol) { list-style: decimal; padding-left: 1.25rem; }
.help :deep(li) { margin: 0.2rem 0; }
.help :deep(a) { color: var(--brand-b); text-decoration: underline; text-underline-offset: 2px; }
.help :deep(code) { font-family: var(--mono); font-size: 0.85em; background: var(--panel-raised); border: 1px solid var(--line); border-radius: 4px; padding: 0 0.3em; }
.help :deep(pre) { background: var(--void); border: 1px solid var(--line); border-radius: var(--radius); padding: 0.75rem 1rem; overflow-x: auto; }
.help :deep(pre code) { background: none; border: 0; padding: 0; overflow-wrap: normal; white-space: pre; }
.help :deep(table) { display: block; overflow-x: auto; border-collapse: collapse; margin: 0.75rem 0; font-size: 0.875rem; }
.help :deep(th), .help :deep(td) { border: 1px solid var(--line); padding: 0.4rem 0.6rem; text-align: left; vertical-align: top; overflow-wrap: normal; }
.help :deep(th) { background: var(--panel-raised); color: var(--text); font-weight: 600; }
.help :deep(td) { color: var(--text-dim); min-width: 7rem; }
</style>
