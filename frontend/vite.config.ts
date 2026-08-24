import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

// O build gera arquivos estáticos em `dist/`, que são copiados para dentro da
// imagem única do container e servidos pelo FastAPI na raiz `/`.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");

  // Backend do APP_RENOVAI. Em produção não há proxy: o FastAPI serve o
  // portal e a API na mesma origem, dentro da imagem única.
  const alvo = env.VITE_BACKEND_URL || "http://localhost:8000";

  const rotas = [
    "/auth",
    "/recomendacoes",
    "/prescricoes",
    "/insight-medico",
    "/gerencial",
    "/health",
  ];

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: { "@": path.resolve(__dirname, "./src") },
    },
    server: {
      port: 3000,
      // Em desenvolvimento o front roda separado do backend. O proxy evita
      // CORS e reproduz o mesmo caminho relativo usado no container.
      proxy: Object.fromEntries(
        rotas.map((rota) => [rota, { target: alvo, changeOrigin: true }]),
      ),
    },
  };
});
