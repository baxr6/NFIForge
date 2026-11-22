import { LineStyle, type IPriceLine, type ISeriesApi, type SeriesMarker, type SeriesType, type Time, type UTCTimestamp } from "lightweight-charts"
import { alpha, css } from "./chartTheme"
import type { Mark, TradeOverlay } from "./CandleChart.vue"

// bot trades on a lightweight chart (Chart and Order Flow pages): entry / add / exit markers, and the open trade's
// avg entry, stop and liquidation lines

export function tradeMarker(mark: Mark): SeriesMarker<Time> {
  const green = css("--green"), red = css("--red"), brandB = css("--brand-b"), brandA = css("--brand-a")
  const long = mark.side === "long"
  const time = mark.time as UTCTimestamp
  if (mark.kind === "signal") return { time, position: long ? "belowBar" : "aboveBar", shape: "circle", color: alpha(long ? green : red, 0.55), size: 0.4 }
  return {
    time,
    position: mark.kind === "exit" ? (long ? "aboveBar" : "belowBar") : (long ? "belowBar" : "aboveBar"),
    shape: mark.kind === "exit" ? (long ? "arrowDown" : "arrowUp") : mark.kind === "dca" ? "circle" : (long ? "arrowUp" : "arrowDown"),
    color: mark.kind === "exit" ? css("--amber") : mark.kind === "dca" ? brandA : brandB,
    size: mark.kind === "dca" ? Math.min(2, 0.6 + (mark.stake ?? 0) / 100) : 1.4,
    text: mark.text,
  }
}

// markers must sit on a bar the series has, in time order
export function tradeMarkers(marks: Mark[], have: Set<number>): SeriesMarker<Time>[] {
  return marks.filter((mark) => have.has(mark.time)).sort((left, right) => left.time - right.time).map(tradeMarker)
}

export function tradeLines<T extends SeriesType>(series: ISeriesApi<T>, overlay: TradeOverlay): IPriceLine[] {
  const red = css("--red"), brandB = css("--brand-b"), brandA = css("--brand-a")
  const pct = (price: number) => `${(((price - overlay.avgEntry) / overlay.avgEntry) * 100).toFixed(1)}%`
  const out = [series.createPriceLine({ price: overlay.avgEntry, color: brandB, lineStyle: LineStyle.Dashed, lineWidth: 1, title: "avg entry" })]
  if (overlay.stop) out.push(series.createPriceLine({ price: overlay.stop, color: css("--amber"), lineStyle: LineStyle.Dashed, lineWidth: 1, title: `stop ${pct(overlay.stop)}` }))
  if (overlay.liquidation) out.push(series.createPriceLine({ price: overlay.liquidation, color: red, lineStyle: LineStyle.Solid, lineWidth: 2, title: `liq ${pct(overlay.liquidation)}` }))
  for (const level of overlay.levels ?? []) out.push(series.createPriceLine({ price: level.price, color: alpha(brandA, 0.7), lineStyle: LineStyle.SparseDotted, lineWidth: 1, title: level.text }))
  return out
}
