import { defineAsyncComponent, type Component } from "vue"

// every panel in the app, so any page can show any of them. a page has a default layout; the user can add any
// other panel to it from the grid's edit bar. panels get their data from shared stores (trading data is provided
// app-wide, page states are singletons), never from the page they sit on. sizes are on the 24 column grid.

export type PanelSpec = {
  title: string
  group: string  // the page it comes from, used to group the picker
  comp: Component
  props?: Record<string, unknown>
  w: number  // size when added from the picker
  h: number
  minW?: number
  minH?: number
  fill?: boolean  // draws to its cell's height (charts); stacked on phones it keeps its grid height
  card?: boolean  // a small number card: two to a row on phones
  fold?: boolean  // folded on phones behind a "show" line (big, glanceable on a desktop only)
}

export type Item = { i: string; x: number; y: number; w: number; h: number }

export const COLS = 24

const lazy = (load: () => Promise<{ default: Component }>) => defineAsyncComponent(load)

const MONEY = lazy(() => import("@/components/panels/cards/MoneyCardPanel.vue"))
const STATUS = lazy(() => import("@/components/panels/cards/StatusCardPanel.vue"))
const ANALYTICS_STAT = lazy(() => import("@/components/panels/cards/AnalyticsStatPanel.vue"))
const HISTORY_STAT = lazy(() => import("@/components/panels/cards/HistoryStatPanel.vue"))
const SERVER_STAT = lazy(() => import("@/components/panels/cards/ServerStatPanel.vue"))
const ANALYTICS_CHART = lazy(() => import("@/components/panels/analytics/AnalyticsChartPanel.vue"))
const SERVER_HISTORY = lazy(() => import("@/components/panels/server/ServerHistoryPanel.vue"))

const card = (title: string, group: string, comp: Component, key: string, width = 4, height = 2): PanelSpec =>
  ({ title, group, comp, props: { card: key }, w: width, h: height, minW: 3, minH: 2, card: true })

const STATIC: Record<string, PanelSpec> = {
  // ===========================================================================
  // TRADING (slot panels are added below, one per slot)
  // ===========================================================================
  "status-bot": card("Bot status", "Trading", STATUS, "bot", 5),
  "status-exchange": card("Exchange status", "Trading", STATUS, "exchange", 5),
  "status-data": card("Data status", "Trading", STATUS, "data", 5),
  "status-server": card("Server status", "Trading", STATUS, "server", 5),
  "status-risk": card("Risk status", "Trading", STATUS, "risk", 4),
  "money-equity": { ...card("Equity", "Trading", MONEY, "equity", 8, 4), minW: 5, minH: 3, card: false },  // big: full width on phones
  "money-open": card("Open P&L", "Trading", MONEY, "open"),
  "money-today": card("Today realised", "Trading", MONEY, "today"),
  "money-net": card("True net", "Trading", MONEY, "net"),
  "money-winrate": card("Win rate", "Trading", MONEY, "winrate"),
  "money-notional": card("Notional exposure", "Trading", MONEY, "notional"),
  "money-stake": card("Stake used", "Trading", MONEY, "stake"),
  "money-drawdown": card("Drawdown", "Trading", MONEY, "drawdown"),
  "money-expectancy": card("Expectancy / trade", "Trading", MONEY, "expectancy"),
  gauges: { title: "Gauges", group: "Trading", comp: lazy(() => import("@/components/trading/panels/GaugesPanel.vue")), w: 24, h: 4, minW: 6, minH: 3, fold: true },
  today: { title: "Today's P&L", group: "Trading", comp: lazy(() => import("@/components/trading/panels/TodayPanel.vue")), w: 8, h: 8, minW: 6, minH: 5, fill: true },
  pulse: { title: "Market pulse", group: "Trading", comp: lazy(() => import("@/components/trading/panels/PulsePanel.vue")), w: 8, h: 8, minW: 6, minH: 6, fill: true },
  risk: { title: "Risk & exposure", group: "Trading", comp: lazy(() => import("@/components/trading/panels/RiskPanel.vue")), w: 12, h: 9, minW: 8, minH: 6 },
  events: { title: "Event stream", group: "Trading", comp: lazy(() => import("@/components/trading/panels/EventsPanel.vue")), w: 8, h: 8, minW: 6, minH: 4 },

  // ===========================================================================
  // WHOLE-PAGE PANELS
  // ===========================================================================
  positions: { title: "Open positions", group: "Positions", comp: lazy(() => import("@/components/panels/live/PositionsPanel.vue")), w: 24, h: 12, minW: 12, minH: 4 },
  chart: { title: "Chart", group: "Chart", comp: lazy(() => import("@/components/panels/live/ChartPanel.vue")), w: 24, h: 18, minW: 10, minH: 8, fill: true },
  orderflow: { title: "Order flow", group: "Order Flow", comp: lazy(() => import("@/components/panels/live/OrderFlowPanel.vue")), w: 24, h: 24, minW: 12, minH: 12, fill: true },
  "orderflow-dom": { title: "DOM ladder", group: "Order Flow", comp: lazy(() => import("@/components/panels/live/OrderFlowDomPanel.vue")), w: 6, h: 16, minW: 4, minH: 8, fill: true },
  "orderflow-tape": { title: "Tape", group: "Order Flow", comp: lazy(() => import("@/components/panels/live/OrderFlowTapePanel.vue")), w: 6, h: 8, minW: 4, minH: 5, fill: true },
  "orderflow-depth": { title: "Depth chart", group: "Order Flow", comp: lazy(() => import("@/components/panels/live/OrderFlowDepthPanel.vue")), w: 6, h: 8, minW: 4, minH: 5, fill: true },
  logs: { title: "Logs", group: "Logs", comp: lazy(() => import("@/components/panels/live/LogsPanel.vue")), w: 24, h: 18, minW: 10, minH: 6, fill: true },
  "bot-health": { title: "Bot health", group: "Bot Health", comp: lazy(() => import("@/components/panels/live/BotHealthPanel.vue")), w: 24, h: 16, minW: 10, minH: 5 },

  // ===========================================================================
  // TRADE HISTORY (filters live in the Trade History page header)
  // ===========================================================================
  "history-trades": card("Closed trades count", "Trade History", HISTORY_STAT, "trades"),
  "history-won": card("History win rate", "Trade History", HISTORY_STAT, "won"),
  "history-total": card("History total", "Trade History", HISTORY_STAT, "total"),
  "history-avg": card("History avg / trade", "Trade History", HISTORY_STAT, "avg"),
  "history-losses": card("All losses", "Trade History", HISTORY_STAT, "losses"),
  "history-worst": card("Worst trade", "Trade History", HISTORY_STAT, "worst"),
  timeline: { title: "Timeline (equity, events, slots, CPU)", group: "Trade History", comp: lazy(() => import("@/components/panels/history/TimelinePanel.vue")), w: 24, h: 16, minW: 12, minH: 10, fill: true },
  "history-table": { title: "Closed trades", group: "Trade History", comp: lazy(() => import("@/components/panels/history/HistoryTablePanel.vue")), w: 24, h: 16, minW: 12, minH: 5 },

  // ===========================================================================
  // NOTIFICATIONS
  // ===========================================================================
  alerts: { title: "Open alerts", group: "Notifications", comp: lazy(() => import("@/components/panels/notifications/AlertsPanel.vue")), w: 24, h: 3, minW: 6, minH: 2 },
  notifications: { title: "Notifications", group: "Notifications", comp: lazy(() => import("@/components/panels/notifications/NotificationListPanel.vue")), w: 24, h: 14, minW: 8, minH: 4 },

  // ===========================================================================
  // SERVER
  // ===========================================================================
  "server-gauges": { title: "Server gauges", group: "Server", comp: lazy(() => import("@/components/panels/server/ServerGaugesPanel.vue")), w: 24, h: 5, minW: 8, minH: 4 },
  "server-ram-used": card("RAM used", "Server", SERVER_STAT, "ram", 5),
  "server-disk-free": card("Disk free", "Server", SERVER_STAT, "disk", 5),
  "server-net-in": card("Network in", "Server", SERVER_STAT, "netin", 5),
  "server-net-out": card("Network out", "Server", SERVER_STAT, "netout", 5),
  "server-up": card("Server uptime", "Server", SERVER_STAT, "up", 4),
  "server-containers": { title: "Containers", group: "Server", comp: lazy(() => import("@/components/panels/server/ServerContainersPanel.vue")), w: 24, h: 9, minW: 12, minH: 4 },
  "server-cpu": { title: "CPU history", group: "Server", comp: SERVER_HISTORY, props: { kind: "cpu" }, w: 12, h: 5, minW: 6, minH: 3, fill: true },
  "server-ram": { title: "RAM history", group: "Server", comp: SERVER_HISTORY, props: { kind: "ram" }, w: 12, h: 5, minW: 6, minH: 3, fill: true },
  "server-disk": { title: "Disk history", group: "Server", comp: SERVER_HISTORY, props: { kind: "disk" }, w: 12, h: 4, minW: 6, minH: 3, fill: true },
  "server-container-mem": { title: "Container memory history", group: "Server", comp: SERVER_HISTORY, props: { kind: "containers" }, w: 24, h: 7, minW: 8, minH: 4, fill: true },
  "server-loops": { title: "Bot loop time history", group: "Server", comp: SERVER_HISTORY, props: { kind: "loops" }, w: 12, h: 4, minW: 6, minH: 3, fill: true },

  // ===========================================================================
  // ANALYTICS (filters live in the Analytics page header and apply wherever these panels are)
  // ===========================================================================
  "analytics-trades": card("Analytics trades", "Analytics", ANALYTICS_STAT, "trades"),
  "analytics-won": card("Analytics win rate", "Analytics", ANALYTICS_STAT, "won"),
  "analytics-total": card("Analytics total profit", "Analytics", ANALYTICS_STAT, "total"),
  "analytics-avg": card("Analytics avg / trade", "Analytics", ANALYTICS_STAT, "avg"),
  "analytics-pf": card("Profit factor", "Analytics", ANALYTICS_STAT, "pf"),
  "analytics-dd": card("Max drawdown", "Analytics", ANALYTICS_STAT, "dd"),
  "analytics-funding": card("Funding", "Analytics", ANALYTICS_STAT, "funding"),
  "analytics-curve": { title: "Realised profit curve", group: "Analytics", comp: lazy(() => import("@/components/panels/analytics/AnalyticsCurvePanel.vue")), w: 16, h: 9, minW: 8, minH: 5, fill: true },
  "analytics-period": { title: "Profit per day / week / month", group: "Analytics", comp: lazy(() => import("@/components/panels/analytics/AnalyticsPeriodPanel.vue")), w: 8, h: 9, minW: 6, minH: 5, fill: true },
  "analytics-calendar": { title: "Daily profit calendar", group: "Analytics", comp: ANALYTICS_CHART, props: { kind: "calendar" }, w: 24, h: 5, minW: 12, minH: 4, fill: true },
  "analytics-breakdown": { title: "Breakdown table", group: "Analytics", comp: lazy(() => import("@/components/panels/analytics/AnalyticsBreakdownPanel.vue")), w: 16, h: 10, minW: 10, minH: 4 },
  "analytics-hold": { title: "Time held", group: "Analytics", comp: ANALYTICS_CHART, props: { kind: "hold" }, w: 8, h: 10, minW: 6, minH: 4, fill: true },
  "analytics-excursion": { title: "Best / worst move (MFE / MAE)", group: "Analytics", comp: lazy(() => import("@/components/panels/analytics/AnalyticsExcursionPanel.vue")), w: 24, h: 11, minW: 12, minH: 6, fill: true },
  "analytics-tag-exit": { title: "Entry tag × exit type", group: "Analytics", comp: ANALYTICS_CHART, props: { kind: "tagExit" }, w: 24, h: 9, minW: 12, minH: 4, fill: true },

  // ===========================================================================
  // PAIRS (for the bot picked in the header)
  // ===========================================================================
  "pairs-find": { title: "Find a pair", group: "Pairs", comp: lazy(() => import("@/components/panels/pairs/PairsFindPanel.vue")), w: 24, h: 3, minW: 8, minH: 2 },
  "pairs-whitelist": { title: "Whitelist", group: "Pairs", comp: lazy(() => import("@/components/panels/pairs/PairsWhitelistPanel.vue")), w: 16, h: 12, minW: 8, minH: 4 },
  "pairs-locks": { title: "Pair locks", group: "Pairs", comp: lazy(() => import("@/components/panels/pairs/PairsLocksPanel.vue")), w: 8, h: 4, minW: 6, minH: 2 },
  "pairs-blacklist": { title: "Blacklist", group: "Pairs", comp: lazy(() => import("@/components/panels/pairs/PairsBlacklistPanel.vue")), w: 8, h: 8, minW: 6, minH: 3 },
  "pairs-filtered": { title: "Filtered out", group: "Pairs", comp: lazy(() => import("@/components/panels/pairs/PairsFilteredPanel.vue")), w: 16, h: 8, minW: 8, minH: 3 },
  "pairs-changes": { title: "Whitelist changes", group: "Pairs", comp: lazy(() => import("@/components/panels/pairs/PairsChangesPanel.vue")), w: 8, h: 8, minW: 6, minH: 3 },
}

const SLOT = lazy(() => import("@/components/trading/panels/SlotPanel.vue"))
export const MAX_SLOT_PANELS = 60  // slot boxes per bot (max_open_trades above this shows the first 60)

export function panelSpec(id: string): PanelSpec | undefined {
  if (id in STATIC) return STATIC[id]
  const match = /^slot-(\d+)$/.exec(id)
  if (match && +match[1] >= 1 && +match[1] <= MAX_SLOT_PANELS)
    return { title: `Slot ${match[1]}`, group: "Trading", comp: SLOT, props: { index: +match[1] - 1 }, w: 6, h: 5, minW: 4, minH: 3 }
  return undefined
}

// what the picker offers: every static panel plus the bot's slots
export function catalog(slots: number): { id: string; spec: PanelSpec }[] {
  const ids = [...Object.keys(STATIC), ...Array.from({ length: slots }, (_, index) => `slot-${index + 1}`)]
  return ids.map((id) => ({ id, spec: panelSpec(id)! }))
}

// ===========================================================================
// SETS: groups of cards added (and laid out) in one go. their ids are the old single panels the cards came
// from, so a layout saved before the split gets the set in that panel's place
// ===========================================================================
const row = (ids: string[], widths: number[], y = 0, height = 2): Item[] => {
  let x = 0
  return ids.map((id, index) => { const item = { i: id, x, y, w: widths[index], h: height }; x += widths[index]; return item })
}
const shift = (items: Item[], dx: number) => items.map((item) => ({ ...item, x: item.x + dx }))

export const SETS: Record<string, { title: string; group: string; items: Item[] }> = {
  status: { title: "All status cards (5)", group: "Trading", items: row(["status-bot", "status-exchange", "status-data", "status-server", "status-risk"], [5, 5, 5, 5, 4]) },
  money: {
    title: "All money cards (9)", group: "Trading",
    items: [
      { i: "money-equity", x: 0, y: 0, w: 8, h: 4 },
      ...shift(row(["money-open", "money-today", "money-net", "money-winrate"], [4, 4, 4, 4], 0), 8),
      ...shift(row(["money-notional", "money-stake", "money-drawdown", "money-expectancy"], [4, 4, 4, 4], 2), 8),
    ],
  },
  "analytics-summary": { title: "All analytics cards (6)", group: "Analytics", items: row(["analytics-trades", "analytics-won", "analytics-total", "analytics-avg", "analytics-pf", "analytics-dd"], [4, 4, 4, 4, 4, 4]) },
  "history-summary": { title: "All history cards (6)", group: "Trade History", items: row(["history-trades", "history-won", "history-total", "history-avg", "history-losses", "history-worst"], [4, 4, 4, 4, 4, 4]) },
  "server-stats": { title: "All server number cards (5)", group: "Server", items: row(["server-ram-used", "server-disk-free", "server-net-in", "server-net-out", "server-up"], [5, 5, 5, 5, 4]) },
}

// a set's cards placed with their top-left at (x, y)
export const placeSet = (id: string, x: number, y: number): Item[] => shift(SETS[id].items, x).map((item) => ({ ...item, y: item.y + y }))
