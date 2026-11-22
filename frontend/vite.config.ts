import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"
import tailwindcss from "@tailwindcss/vite"
import { fileURLToPath, URL } from "node:url"
import { readFileSync } from "node:fs"

// single source of truth for the version: backend/nfiforge/__init__.py
const version = /__version__ = "([^"]+)"/.exec(readFileSync(new URL("../backend/nfiforge/__init__.py", import.meta.url), "utf8"))?.[1] ?? "dev"

// dev server proxies to the backend so the app runs on one origin like in production; NFIFORGE_API overrides it
const api = process.env.NFIFORGE_API ?? "http://127.0.0.1:8880"
const proxy = { "/api": api, "/ws": { target: api.replace(/^http/, "ws"), ws: true } }

export default defineConfig({
  plugins: [vue(), tailwindcss(), { name: "html-version", transformIndexHtml: (html) => html.replace("%VERSION%", version) }],
  define: { __APP_VERSION__: JSON.stringify(version) },
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: { port: 5173, proxy },
  preview: { proxy },
  build: { outDir: "dist", chunkSizeWarningLimit: 1500 },
})
