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

  // Todo prefixo de rota que o front chama precisa estar aqui. O que falta
  // não vai ao backend: o servidor do Vite devolve o index.html e a chamada
  // falha sem explicação. `/chat`, `/agente` e `/ranking` faltavam, então
  // conversa e ranking não funcionavam em desenvolvimento.
  const rotas = [
    "/agente",
    "/auth",
    "/chat",
    "/gerencial",
    "/health",
    "/insight-medico",
    "/prescricoes",
    "/ranking",
    "/recomendacoes",
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
