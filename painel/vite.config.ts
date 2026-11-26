import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// Em desenvolvimento o painel roda no Vite e encaminha a API para o servidor Python.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
    dedupe: ["react", "react-dom", "react/jsx-runtime", "react/jsx-dev-runtime", "@tanstack/react-query", "@tanstack/query-core"],
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/entrar/helena": "http://127.0.0.1:8000",
      "/midia": "http://127.0.0.1:8000",
    },
  },
});
