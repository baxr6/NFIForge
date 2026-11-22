// number formatting used across pages

// text from a bot (tags, exit reasons, titles) inside a chart tooltip, which renders html
export const esc = (value: unknown) => String(value ?? "").replace(/[&<>"']/g, (char) => `&#${char.charCodeAt(0)};`)
export const money = (value: number | null | undefined, digits = 2) =>
  value == null || !Number.isFinite(value) ? "–" : value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })

// decimals from the price: about 4 significant digits (BTC 2, a 0.31 coin 4, a 0.00001234 coin 8)
export const decimals = (price: number) => (price > 0 ? Math.min(8, Math.max(2, 3 - Math.floor(Math.log10(price)))) : 2)
export const price = (value: number | null | undefined) => (value == null || !Number.isFinite(value) ? "–" : value.toFixed(decimals(value)))
export const signed = (value: number | null | undefined, digits = 2) => (value == null || !Number.isFinite(value) ? "–" : (value >= 0 ? "+" : "") + money(value, digits))

export const pct = (value: number | null | undefined, digits = 2) => (value == null || !Number.isFinite(value) ? "–" : (value >= 0 ? "+" : "") + value.toFixed(digits) + "%")

export function age(fromSec: number, nowSec = Date.now() / 1000): string {
  const seconds = Math.max(0, nowSec - fromSec)
  if (seconds < 90) return `${Math.round(seconds)}s`
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`
  if (seconds < 172800) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`
}

// 95 % interval for a win rate
export function wilson(wins: number, trials: number): [number, number] | null {
  if (!trials) return null
  const zScore = 1.96, rate = wins / trials, den = 1 + (zScore * zScore) / trials
  const mid = (rate + (zScore * zScore) / (2 * trials)) / den
  const half = (zScore * Math.sqrt((rate * (1 - rate)) / trials + (zScore * zScore) / (4 * trials * trials))) / den
  return [Math.max(0, mid - half), Math.min(1, mid + half)]
}

export const tone = (value: number | null | undefined) => (value == null ? "text-ink" : value > 0 ? "text-up" : value < 0 ? "text-down" : "text-ink")
