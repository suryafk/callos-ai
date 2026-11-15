import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// In development the dashboard proxies API calls to the local backend, so no CORS setup is needed.
const backend = `http://127.0.0.1:${process.env.BACKEND_PORT ?? "8787"}`;

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: Number(process.env.FRONTEND_PORT ?? 5174),
    proxy: { "/api": backend, "/health": backend },
  },
});
