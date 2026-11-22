// every gauge the dashboard can show; ids match the backend settings keys
export type GaugeDef = {
  id: string
  label: string
  unit: string
  style: "analog" | "segment"
  min: number
  max: number
  decimals: number
  group: "server" | "bot" | "risk" | "market"
  lowIsBad?: boolean  // danger below the warn level, e.g. liquidation distance
  palette?: "rising" | "risk"
  majors?: number
  hint: string
}

export const GAUGES: GaugeDef[] = [
  { id: "cpu", label: "CPU", unit: "%", style: "analog", min: 0, max: 100, decimals: 0, group: "server", hint: "host cpu use" },
  { id: "ram", label: "RAM", unit: "%", style: "analog", min: 0, max: 100, decimals: 0, group: "server", hint: "host memory use" },
  { id: "load", label: "Load", unit: "/core", style: "analog", min: 0, max: 2, decimals: 2, group: "server", majors: 5, hint: "1 min load average per cpu core" },
  { id: "disk", label: "Disk", unit: "%", style: "analog", min: 0, max: 100, decimals: 0, group: "server", hint: "disk holding the bot data" },
  { id: "swap", label: "Swap", unit: "%", style: "analog", min: 0, max: 100, decimals: 0, group: "server", hint: "swap in use, high = memory pressure" },
  { id: "temp", label: "Temp", unit: "°C", style: "analog", min: 20, max: 100, decimals: 0, group: "server", hint: "cpu temperature where the host reports it" },
  { id: "exchange_ms", label: "Exchange", unit: "ms", style: "analog", min: 0, max: 500, decimals: 0, group: "bot", hint: "api round trip to the bot" },
  { id: "loop_s", label: "Loop", unit: "s", style: "analog", min: 0, max: 30, decimals: 1, group: "bot", hint: "time the bot takes per loop" },
  { id: "btc_rsi", label: "BTC RSI", unit: "4h", style: "analog", min: 0, max: 100, decimals: 1, group: "market", hint: "btc 4h rsi(14)" },
  { id: "stake_used", label: "Stake used", unit: "%", style: "segment", min: 0, max: 100, decimals: 1, group: "risk", palette: "rising", hint: "share of the stake tied up in open trades" },
  { id: "slots_used", label: "Slots used", unit: "%", style: "segment", min: 0, max: 100, decimals: 0, group: "risk", palette: "rising", hint: "open trades / max_open_trades" },
  { id: "drawdown", label: "Drawdown", unit: "%", style: "segment", min: 0, max: 25, decimals: 1, group: "risk", palette: "risk", hint: "current drawdown from the equity peak" },
  { id: "liq_distance", label: "Liq distance", unit: "%", style: "segment", min: 0, max: 60, decimals: 1, group: "risk", palette: "rising", lowIsBad: true, hint: "nearest open trade's distance to liquidation" },
]

export const gaugeById = Object.fromEntries(GAUGES.map((gauge) => [gauge.id, gauge]))
