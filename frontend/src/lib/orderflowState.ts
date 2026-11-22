import { reactive, ref, watch } from "vue"
import { DEFAULTS } from "@/lib/orderflow"
import type { CellStyle } from "@/components/orderflow/footprintSeries"

// what the Order Flow panels show, shared so the chart, dom and depth panels follow one pair. the bot comes from the
// live store's pick (shared with the Chart page); the look is saved in this browser

export const pair = ref("")

export type Look = {
  tf: string; style: CellStyle; rows: number; poc: boolean; va: boolean; zones: boolean; session: boolean
  ratio: number; stack: number; minVol: number
  heat: boolean; contrast: number; heatLog: boolean; heatMax: number; walls: boolean; imb: boolean; band: number  // band = index into the imbalance bands
  domGroup: number; domCum: boolean; depthPct: number
  profile: "off" | "visible" | "day" | "range"; split: "bidask" | "delta"
  dev: boolean; vwap: boolean; bands: number  // bands = standard deviations drawn around each VWAP (0-2)
  ua: boolean; exh: boolean; abs: boolean; div: boolean; cot: boolean
  bubbles: boolean; bigMin: number  // bigMin = smallest bubble in USD; 0 = the pair's big-trade size
  tapeMin: number; tapeAgg: boolean  // tapeMin in USD; tapeAgg = trades of one moment and side as one line
  oi: boolean; liq: boolean; trades: boolean  // open interest pane, liquidations + funding pane, the bot's trades
  spotCvd: boolean  // the spot pair's cumulative delta next to the perp's
}
const KEY = "nfiforge.orderflow"
export const look = reactive<Look>({
  tf: "5m", style: "bidask", rows: 0, poc: true, va: true, zones: true, session: true,
  ratio: DEFAULTS.ratio, stack: DEFAULTS.stack, minVol: 0,
  heat: true, contrast: 1, heatLog: false, heatMax: 0, walls: true, imb: true, band: 3,
  domGroup: 1, domCum: false, depthPct: 1,
  profile: "visible", split: "bidask", dev: false, vwap: true, bands: 1,
  ua: true, exh: false, abs: false, div: false, cot: false, bubbles: true, bigMin: 0,
  tapeMin: 0, tapeAgg: true,
  oi: true, liq: true, trades: true, spotCvd: false,
})
try { Object.assign(look, JSON.parse(localStorage.getItem(KEY) ?? "{}")) } catch { /* storage blocked: defaults */ }
watch(look, () => { try { localStorage.setItem(KEY, JSON.stringify(look)) } catch { /* not saved */ } }, { deep: true })

export const TF_SEC: Record<string, number> = { "1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400 }
