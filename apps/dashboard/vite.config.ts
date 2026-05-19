import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

declare const process: { env: Record<string, string | undefined> };

const apiBaseUrl = process.env.VITE_ELEPHANT_API_BASE_URL || "http://127.0.0.1:8000";
const isDesktopBuild = process.env.VITE_ELEPHANT_DESKTOP === "1";

export default defineConfig({
  base: isDesktopBuild ? "./" : "/dashboard/",
  plugins: [react()],
  server: {
    port: 4174,
    strictPort: true,
    proxy: {
      "/v1": apiBaseUrl,
    },
  },
  preview: {
    port: 4174,
    strictPort: true,
  },
});
