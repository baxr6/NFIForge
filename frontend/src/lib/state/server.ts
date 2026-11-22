import { computed, ref, watch } from "vue"
import { css, ecBase } from "@/components/charts/chartTheme"
import { once, sharedPoll } from "@/lib/shared"
import { useLive } from "@/stores/live"

// the Server page's data, shared by its panels: live host stats from the socket, history from the backend
export type Ctr = { id: string; label: string; mem: number | null; mem_max: number | null; cpu: number | null; oom_kills: number; started: number | null; restarts: number }
type Hist = { host: Record<string, number>[]; containers: { ts: number; id: string; label: string; mem: number }[]; loops: { ts: number; bot: string; loop_s: number }[] }

export const RANGES: [string, number][] = [["6h", 6], ["24h", 24], ["7d", 168], ["30d", 720]]
export const gb = (bytes?: number | null) => (bytes == null ? "–" : bytes >= 2 ** 30 ? `${(bytes / 2 ** 30).toFixed(1)} GB` : `${(bytes / 2 ** 20).toFixed(0)} MB`)

const state = once(() => {
  const live = useLive()
  const h = computed(() => live.host as Record<string, any>)
  const containers = computed(() => ((h.value.containers ?? []) as Ctr[]).slice().sort((a, b) => (b.mem ?? 0) - (a.mem ?? 0)))
  const range = ref(24)
  const hist = ref<Hist | null>(null)
  async function load() {
    const response = await fetch(`/api/server/history?hours=${range.value}`).catch(() => null)
    if (response?.ok) hist.value = await response.json()
  }
  watch(range, load)
  const series = (key: string) => (hist.value?.host ?? []).filter((point) => point[key] != null).map((point) => ({ time: Math.floor(point.ts), value: +point[key].toFixed(1) }))
  // memory per container over time, the 8 biggest now
  const memOption = computed(() => {
    const theme = ecBase()
    const top = containers.value.slice(0, 8).map((container) => container.id)
    const names = new Map(containers.value.map((container) => [container.id, container.label]))
    const palette = [css("--brand-b"), css("--amber"), css("--brand-a"), css("--green"), css("--red"), "#22d3ee", "#e879f9", "#a3e635"]
    const byContainer = new Map<string, [number, number][]>()
    for (const point of hist.value?.containers ?? []) if (top.includes(point.id)) (byContainer.get(point.id) ?? byContainer.set(point.id, []).get(point.id)!).push([point.ts * 1000, +(point.mem / 2 ** 30).toFixed(3)])
    return {
      tooltip: { ...theme.tooltip, trigger: "axis", valueFormatter: (value: number) => `${value.toFixed(2)} GB` },
      legend: { bottom: 0, textStyle: { color: css("--text-dim"), fontFamily: "IBM Plex Sans", fontSize: 11 }, icon: "roundRect", itemWidth: 10, itemHeight: 4 },
      grid: { left: 44, right: 12, top: 12, bottom: 56 },
      xAxis: { type: "time", ...theme.axis },
      yAxis: { type: "value", ...theme.valueAxis, axisLabel: { ...theme.valueAxis.axisLabel, formatter: "{value} GB" } },
      series: top.map((id, i) => ({ type: "line", name: names.get(id)?.slice(0, 40) ?? id, data: byContainer.get(id) ?? [], showSymbol: false, lineStyle: { width: 1.5 }, color: palette[i] })),
    }
  })
  const loopBots = computed(() => [...new Set((hist.value?.loops ?? []).map((loop) => loop.bot))])
  const loopSeries = (bot: string) => (hist.value?.loops ?? []).filter((loop) => loop.bot === bot).map((loop) => ({ time: Math.floor(loop.ts), value: +loop.loop_s.toFixed(1) }))
  const enough = computed(() => (hist.value?.host.length ?? 0) > 1)
  const memPct = (container: Ctr) => (container.mem && container.mem_max ? (container.mem / container.mem_max) * 100 : container.mem && h.value.ram_total ? (container.mem / h.value.ram_total) * 100 : 0)
  const barColor = (container: Ctr) => { const pct = memPct(container); return !container.mem_max ? "var(--brand-b)" : pct > 90 ? "var(--red)" : pct > 75 ? "var(--amber)" : "var(--green)" }
  return { h, containers, range, hist, load, series, memOption, loopBots, loopSeries, enough, memPct, barColor }
})

const poll = once(() => sharedPoll(() => state().load(), 60000))

export function useServer() {
  poll()()
  return state()
}
