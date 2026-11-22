<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { GridItem, GridLayout } from "grid-layout-plus"
import { catalog, COLS, MAX_SLOT_PANELS, panelSpec, placeSet, SETS, type Item } from "@/lib/panels"
import { useTrading } from "@/lib/trading"
import { useSettings } from "@/stores/settings"
import { wide } from "@/lib/viewport"

// drag/resize panel grid for any page (24 columns). the page gives its default layout (a set id there stands for
// its cards); in edit mode panels can be moved, resized, removed, and any panel or set from any page added.
// layout saved on the server per page; phones get a stack with cards two to a row.
export type { Item }

const props = defineProps<{ page: string; defaults: Item[] }>()
const editing = defineModel<boolean>("editing", { default: false })
const settings = useSettings()
const trading = useTrading()

const known = (id: string) => !!panelSpec(id)
// the layout is saved once for every bot: slot panels past this bot's max_open_trades are left out, not dropped
const slotNo = (id: string) => Number(/^slot-(\d+)$/.exec(id)?.[1] ?? 0)
const slotCount = computed(() => Math.min(Math.max(trading.maxSlots.value, trading.open.value.length, 1), MAX_SLOT_PANELS))
const fits = (id: string) => slotNo(id) <= slotCount.value

// a set id (the old grouped panel) becomes its cards at that spot; cards already placed are left alone
function expand(list: Item[]): Item[] {
  const out: Item[] = []
  for (const item of list) {
    if (item.i in SETS) out.push(...placeSet(item.i, item.x, item.y).filter((placed) => !list.some((existing) => existing.i === placed.i)))
    else out.push(item)
  }
  return out
}
const defaultItems = computed(() => expand(props.defaults))
const defaultIds = computed(() => defaultItems.value.map((item) => item.i))

// saved layout: older 12 column layouts widened, sets expanded, unknown panels dropped, default panels the user
// never removed appended (new ones in an update)
function fromSettings(): { items: Item[]; hidden: string[] } {
  const saved = settings.s?.layouts?.[props.page]
  const scale = saved && saved.cols !== COLS ? 2 : 1
  const hidden: string[] = (saved?.hidden ?? []).flatMap((id: string) => (id in SETS ? SETS[id].items.map((item) => item.i) : [id])).filter(known)
  if (!saved?.items?.length) return { items: defaultItems.value.filter((item) => !hidden.includes(item.i)), hidden }
  const wide: Item[] = saved.items.map((item: Item) => ({ ...item, x: item.x * scale, w: item.w * scale }))
  const items = expand(wide).filter((item) => known(item.i) && fits(item.i) && !hidden.includes(item.i))
  const bottom = Math.max(0, ...items.map((item) => item.y + item.h))
  for (const defaultItem of defaultItems.value) if (!items.some((item) => item.i === defaultItem.i) && !hidden.includes(defaultItem.i)) items.push({ ...defaultItem, y: bottom + defaultItem.y })
  return { items, hidden }
}

const items = ref<Item[]>([])
const hidden = ref<string[]>([])
function load() { const layout = fromSettings(); items.value = layout.items; hidden.value = layout.hidden }
// load once, then follow settings pushed from other tabs except while this tab is mid-edit
let loaded = false
watch(() => settings.s, (current) => { if (!loaded || !editing.value) { load(); loaded = !!current } }, { immediate: true })
// default panel set can change (another bot with more or fewer slots)
watch(() => defaultIds.value.join(), () => load())

// writing into settings is enough: the settings store saves changes by itself
function persist() {
  if (!settings.s) return
  const saved = settings.s.layouts?.[props.page]
  // a bot with fewer slots keeps the other bots' slot positions
  const kept = saved?.cols === COLS ? (saved.items ?? []).filter((item: Item) => !fits(item.i) && !items.value.some((existing) => existing.i === item.i)) : []
  const all = [...items.value, ...kept].map(({ i, x, y, w, h }) => ({ i, x, y, w, h }))
  settings.s.layouts = { ...(settings.s.layouts ?? {}), [props.page]: { cols: COLS, items: all, hidden: hidden.value } }
}
function remove(id: string) {
  items.value = items.value.filter((item) => item.i !== id)
  if (defaultIds.value.includes(id)) hidden.value = [...hidden.value, id]
  persist()
}
function add(id: string) {
  const bottom = Math.max(0, ...items.value.map((item) => item.y + item.h))
  const hasItem = (itemId: string) => items.value.some((item) => item.i === itemId)
  const fresh = id in SETS
    ? placeSet(id, 0, bottom).filter((item) => !hasItem(item.i))
    : hasItem(id) || !panelSpec(id) ? [] : [{ i: id, x: 0, y: bottom, w: defaultItems.value.find((item) => item.i === id)?.w ?? panelSpec(id)!.w, h: defaultItems.value.find((item) => item.i === id)?.h ?? panelSpec(id)!.h }]
  if (!fresh.length) return
  items.value = [...items.value, ...fresh]
  hidden.value = hidden.value.filter((hiddenId) => !fresh.some((item) => item.i === hiddenId))
  persist()
}
function reset() { items.value = [...defaultItems.value]; hidden.value = []; persist() }

// picker: every panel not on the page, grouped by the page it comes from; a set first when any of its cards is missing
const slots = computed(() => Math.max(trading.maxSlots.value, trading.open.value.length, 1))
const choices = computed(() => {
  const shown = new Set(items.value.map((item) => item.i))
  const groups = new Map<string, { id: string; title: string }[]>()
  for (const [id, set] of Object.entries(SETS)) {
    if (set.items.some((item) => !shown.has(item.i))) groups.set(set.group, [...(groups.get(set.group) ?? []), { id, title: `⧉ ${set.title}` }])
  }
  for (const { id, spec } of catalog(slots.value)) {
    if (shown.has(id)) continue
    groups.set(spec.group, [...(groups.get(spec.group) ?? []), { id, title: spec.title }])
  }
  return [...groups]
})
const picking = ref("")
watch(picking, (id) => { if (id) { add(id); picking.value = "" } })

// desktop grid from lg up, phone stack below: panels as tall as their content so the page scrolls, not the panel;
// charts and logs (fill) keep their grid height
// on phones empty slots shrink to one line where the first of them sits
const emptySlot = (id: string) => { const match = /^slot-(\d+)$/.exec(id); return !!match && !trading.open.value[+match[1] - 1] }
const empties = computed(() => items.value.filter((item) => emptySlot(item.i)).length)
const stacked = computed(() => {
  const list = [...items.value].sort((a, b) => a.y - b.y || a.x - b.x)
  const first = list.find((item) => emptySlot(item.i))
  return list.filter((item) => !emptySlot(item.i) || item === first)
})
const unfolded = ref<string[]>([])
const stackHeight = (units: number) => `${units * 40 + (units - 1) * 12}px`
const spec = (id: string) => panelSpec(id)!

defineExpose({ reset })
</script>

<template>
  <div v-if="editing && wide" class="panel p-2.5 mb-3 flex flex-wrap items-center gap-2 text-sm edit-bar">
    <span class="text-dim">Drag a panel by its bar, resize from the corner.</span>
    <select v-model="picking" class="rounded-md bg-raised border border-line px-2 py-1 text-ink text-sm">
      <option value="">+ add panel…</option>
      <optgroup v-for="[group, list] in choices" :key="group" :label="group">
        <option v-for="option in list" :key="option.id" :value="option.id">{{ option.title }}</option>
      </optgroup>
    </select>
    <button class="ml-auto px-3 py-1 rounded-md border border-line hover:border-line-bright text-dim" @click="reset">Reset to default</button>
  </div>

  <GridLayout v-if="wide" v-model:layout="items" :col-num="COLS" :row-height="40" :margin="[12, 12]" :is-draggable="editing"
    :is-resizable="editing" :vertical-compact="true" :use-css-transforms="true" @layout-updated="editing && persist()">
    <GridItem v-for="item in items" :key="item.i" :i="item.i" :x="item.x" :y="item.y" :w="item.w" :h="item.h"
      :min-w="spec(item.i).minW ?? 2" :min-h="spec(item.i).minH ?? 2" drag-allow-from=".drag-handle" :class="{ editing }">
      <div class="h-full relative">
        <div v-if="editing" class="drag-handle">
          <span class="grip">⠿</span><span class="truncate min-w-0">{{ spec(item.i).title }}</span>
          <span v-if="!spec(item.i).card" class="text-faint whitespace-nowrap">· {{ spec(item.i).group }}</span>
          <button class="ml-auto shrink-0 text-faint hover:text-down whitespace-nowrap" :title="`remove ${spec(item.i).title} from this page`" @mousedown.stop @click="remove(item.i)">
            ✕<span v-if="!spec(item.i).card"> remove</span></button>
        </div>
        <div class="h-full overflow-auto"><component :is="spec(item.i).comp" v-bind="spec(item.i).props ?? {}" /></div>
      </div>
    </GridItem>
  </GridLayout>

  <div v-else class="grid grid-cols-2 gap-3">
    <template v-for="item in stacked" :key="item.i">
      <div v-if="emptySlot(item.i)" class="col-span-2 panel px-3 py-3 text-sm text-dim">
        {{ empties }} empty slot{{ empties === 1 ? "" : "s" }} <span v-if="trading.loopAgo.value" class="text-faint">· last loop {{ trading.loopAgo.value }} ago</span></div>
      <button v-else-if="spec(item.i).fold && !unfolded.includes(item.i)" class="col-span-2 panel px-3 py-3 text-sm text-dim text-left"
        @click="unfolded = [...unfolded, item.i]">▸ show {{ spec(item.i).title.toLowerCase() }}</button>
      <div v-else :class="[spec(item.i).card ? 'col-span-1' : 'col-span-2', spec(item.i).fill && 'overflow-auto']"
        :style="spec(item.i).fill ? { height: stackHeight(item.h) } : {}">
        <button v-if="spec(item.i).fold" class="text-xs text-dim mb-1 py-1" @click="unfolded = unfolded.filter((unfoldedId) => unfoldedId !== item.i)">▾ hide {{ spec(item.i).title.toLowerCase() }}</button>
        <component :is="spec(item.i).comp" v-bind="spec(item.i).props ?? {}" />
      </div>
    </template>
  </div>
</template>

<style scoped>
.drag-handle {
  position: absolute; z-index: 5; top: -10px; left: 8px; right: 8px;
  display: flex; align-items: center; gap: 8px; padding: 2px 8px; white-space: nowrap; overflow: hidden;
  font-size: 12px; color: var(--text-dim); cursor: move; user-select: none;
  background: var(--panel-raised); border: 1px dashed var(--brand-b); border-radius: 8px;
}
.grip { color: var(--brand-b); }
.editing { outline: 1px dashed var(--line-bright); outline-offset: 4px; border-radius: var(--radius); }
/* no accidental text selection while dragging panels around */
.editing, .editing * { user-select: none; }
.edit-bar { border-color: var(--brand-b); box-shadow: 0 0 0 1px var(--brand-glow); }
</style>
