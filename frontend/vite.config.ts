/// <reference types="vitest/config" />
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const DJANGO = process.env.DJANGO_ORIGIN ?? "http://127.0.0.1:8000";

// Dev : l'app vit sous /app/ et Vite relaie l'API, le WebSocket et les médias vers Django
// (même origine perçue → cookie de session + CSRF). Build : les assets sont servis par
// Django (WhiteNoise) sous /static/frontend/, la page sous /app/.
export default defineConfig(({ command }) => ({
  base: command === "build" ? "/static/frontend/" : "/app/",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: {
    port: 5173,
    proxy: {
      "/api": DJANGO,
      "/accounts": DJANGO,
      "/media": DJANGO,
      "/static": DJANGO,
      "/ws": { target: DJANGO.replace(/^http/, "ws"), ws: true },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        // Vendeurs stables dans des chunks séparés : cache navigateur long terme,
        // chunk applicatif principal plus léger.
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (/[\\/](react|react-dom|react-router|scheduler)[\\/]/.test(id)) return "vendor-react";
          if (id.includes("@tanstack")) return "vendor-query";
          if (id.includes("@radix-ui") || id.includes("@floating-ui")) return "vendor-radix";
          return undefined;
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}", "src/**/*.test.{ts,tsx}"],
  },
}));
