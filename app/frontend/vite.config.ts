import { resolve } from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "./src"),
    },
  },
  // `uv run uvicorn app.server.main:app` serves the API on :8000; ACTCHECK_API overrides it
  server: {
    proxy: { "/api": process.env.ACTCHECK_API ?? "http://127.0.0.1:8000" },
  },
})
