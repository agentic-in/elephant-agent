import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

declare const process: { env: Record<string, string | undefined> };

const apiBaseUrl = process.env.VITE_ELEPHANT_API_BASE_URL || "http://127.0.0.1:8000";

export default defineConfig({
  base: "/dashboard/",
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) {
            return undefined;
          }
          if (id.includes("@lobehub/icons")) {
            return "vendor-icons";
          }
          if (id.includes("reactflow") || id.includes("@dagrejs/dagre")) {
            return "vendor-graph";
          }
          if (id.includes("react") || id.includes("react-dom") || id.includes("react-router-dom")) {
            return "vendor-react";
          }
          return undefined;
        },
      },
    },
  },
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
