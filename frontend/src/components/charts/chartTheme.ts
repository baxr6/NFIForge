import { ColorType, CrosshairMode, LineStyle, type DeepPartial, type ChartOptions } from "lightweight-charts"

// one look for every lightweight-chart: transparent canvas, faint horizontal grid, no hard borders
export const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

export function baseOptions(minimal = false): DeepPartial<ChartOptions> {
  return {
    autoSize: true,
    layout: {
      background: { type: ColorType.Solid, color: "transparent" },
      textColor: css("--text-dim"),
      fontFamily: "IBM Plex Mono",
      fontSize: 11,
      attributionLogo: false,
      panes: { separatorColor: css("--line"), separatorHoverColor: css("--line-bright"), enableResize: true },
    },
    grid: { vertLines: { visible: false }, horzLines: { visible: !minimal, color: "rgba(36,46,59,0.45)" } },
    rightPriceScale: { visible: !minimal, borderVisible: false, scaleMargins: { top: 0.12, bottom: 0.08 } },
    leftPriceScale: { visible: false },
    timeScale: { visible: !minimal, borderVisible: false, timeVisible: true, secondsVisible: false, rightOffset: 4 },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: { color: css("--line-bright"), width: 1, style: LineStyle.Dashed, labelBackgroundColor: css("--panel-raised") },
      horzLine: { color: css("--line-bright"), width: 1, style: LineStyle.Dashed, labelBackgroundColor: css("--panel-raised") },
    },
    // a vertical swipe over the chart scrolls the page (phones); sideways drags and the wheel still pan it
    handleScroll: minimal ? false : { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
    handleScale: !minimal,
  }
}

// hex + alpha byte, for gradient fills
export const alpha = (hex: string, opacity: number) => hex + Math.round(opacity * 255).toString(16).padStart(2, "0")

// shared echarts styling: dark tooltip, quiet axes, plex fonts
export function ecBase() {
  const dim = css("--text-dim"), line = css("--line")
  const axis = { axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: dim, fontFamily: "IBM Plex Mono", fontSize: 10 } }
  return {
    tooltip: { backgroundColor: css("--panel-raised"), borderColor: css("--line-bright"), textStyle: { color: css("--text"), fontFamily: "IBM Plex Mono", fontSize: 12 } },
    axis,
    valueAxis: { ...axis, splitLine: { lineStyle: { color: alpha(line, 0.6) } } },
    // red -> panel -> green for signed values
    diverging: [css("--red"), css("--red-dim"), css("--panel"), css("--green-dim"), css("--green")],
  }
}
