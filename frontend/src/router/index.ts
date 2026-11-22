import { createRouter, createWebHistory } from "vue-router"

// pages from docs/DESIGN.md §6; the ones not built yet show a placeholder. section: a page a viewer may be left
// without (docs/SHARING.md)
export const navGroups = [
  { title: "LIVE", items: [
    { name: "trading", label: "Trading", path: "/trading" },
    { name: "positions", label: "Positions", path: "/positions" },
    { name: "chart", label: "Chart", path: "/chart" },
    { name: "orderflow", label: "Order Flow", path: "/orderflow", feature: "orderflow", section: "orderflow" },
    { name: "radar", label: "Signal Radar", path: "/radar", section: "radar" },
    { name: "btcgate", label: "BTCGate", path: "/btcgate", feature: "btcgate", section: "btcgate" },
    { name: "logs", label: "Logs", path: "/logs", section: "logs" },
    { name: "notifications", label: "Notifications", path: "/notifications", section: "notifications" },
  ] },
  { title: "STATISTICS", items: [
    { name: "history", label: "Trade History", path: "/history" },
    { name: "analytics", label: "Analytics", path: "/analytics" },
    { name: "pairs", label: "Pairs", path: "/pairs" },
  ] },
  { title: "SYSTEM", items: [
    { name: "server", label: "Server", path: "/server", section: "server" },
    { name: "manage-bots", label: "Manage Bots", path: "/manage-bots", admin: true },
    { name: "bot-health", label: "Bot Health", path: "/bot-health" },
    { name: "settings", label: "Settings", path: "/settings" },
    { name: "help", label: "Help", path: "/help" },
  ] },
]

const built: Record<string, () => Promise<unknown>> = {
  trading: () => import("@/views/TradingView.vue"),
  settings: () => import("@/views/SettingsView.vue"),
  positions: () => import("@/views/PositionsView.vue"),
  history: () => import("@/views/HistoryView.vue"),
  analytics: () => import("@/views/AnalyticsView.vue"),
  chart: () => import("@/views/ChartView.vue"),
  orderflow: () => import("@/views/OrderFlowView.vue"),
  radar: () => import("@/views/RadarView.vue"),
  btcgate: () => import("@/views/BtcgateView.vue"),
  logs: () => import("@/views/LogsView.vue"),
  "bot-health": () => import("@/views/BotHealthView.vue"),
  pairs: () => import("@/views/PairsView.vue"),
  notifications: () => import("@/views/NotificationsView.vue"),
  server: () => import("@/views/ServerView.vue"),
  "manage-bots": () => import("@/views/ManageBotsView.vue"),
  help: () => import("@/views/HelpView.vue"),
}

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/trading" },
    { path: "/s/:code", name: "share", component: { render: () => null } },  // a share link: App.vue shows it, no sign-in
    { path: "/:unknown(.*)*", redirect: "/trading" },  // old or mistyped addresses
    ...navGroups.flatMap((group) => group.items).map((item) => ({
      path: item.path,
      name: item.name,
      component: built[item.name] ?? (() => import("@/views/PlaceholderView.vue")),
      meta: { label: item.label, section: "section" in item ? item.section : undefined },
    })),
  ],
})
