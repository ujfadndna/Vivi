import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8100";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": apiTarget,
      "/chat/simple": apiTarget,
      "/chat/avatar": apiTarget,
      "/chat/idle-video": apiTarget,
      "/health": apiTarget,
      "/outputs": apiTarget
    }
  },
  build: {
    outDir: "dist",
    sourcemap: true
  }
});
