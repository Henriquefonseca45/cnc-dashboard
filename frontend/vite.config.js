import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    proxy: {
      "/fila": "http://192.168.17.121:8001",
      "/fila_fs": "http://192.168.17.121:8001",
      "/agente": "http://192.168.17.121:8001",
      "/maquinas": "http://192.168.17.121:8001",
      "/arquivos": "http://192.168.17.121:8001",
      "/atribuir": "http://192.168.17.121:8001",
      "/dashboard": "http://192.168.17.121:8001",
    },
  },
});