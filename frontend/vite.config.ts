/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The built app is served by the PulseOps API itself at /ui/ (same origin: no CORS, no cross-origin token exposure).
// During `npm run dev` the API paths are proxied to a locally running PulseOps (uvicorn on :8000).
const api = "http://127.0.0.1:8000";

export default defineConfig({
  base: "/ui/",
  plugins: [react()],
  build: { outDir: "dist", sourcemap: false },
  server: {
    proxy: {
      "/me": api,
      "/incidents": api,
      "/workflow": api,
      "/health": api,
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    exclude: ["node_modules", "dist"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/test/**", "src/main.tsx"], // test code, and the one-line bootstrap that only mounts <App/>
      reporter: ["text-summary", "json-summary"],
      reportsDirectory: "coverage",
      // thresholds: see the ratchet in quality/thresholds.json (enforced by scripts/quality_gate.py)
    },
  },
});
