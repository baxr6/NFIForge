// nfi entry tag -> mode name; shorts are the long ranges + 500
const LONG_MODES: [number, number, string][] = [
  [1, 13, "normal"], [21, 26, "pump"], [41, 53, "quick"], [61, 68, "rebuy"], [81, 82, "high profit"],
  [101, 110, "rapid"], [120, 120, "grind"], [121, 121, "btc"], [141, 145, "top coins"], [161, 173, "scalp"],
]

export function nfiMode(tag: string | null | undefined): string | null {
  const first = Number((tag ?? "").trim().split(/\s+/)[0])
  if (!Number.isFinite(first) || first <= 0) return null
  const base = first > 500 ? first - 500 : first
  return LONG_MODES.find(([low, high]) => base >= low && base <= high)?.[2] ?? null
}
