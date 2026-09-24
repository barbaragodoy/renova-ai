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
    "/admin",
    "/insight-medico",
    "/prescricoes",
    "/ranking",
    "/recomendacoes",
  ];

  // Login Entra ID em desenvolvimento (só `npm run dev`; nada disto entra no
  // bundle, por isso os nomes não têm o prefixo VITE_). Sem as variáveis, o
  // proxy não muda nada.
  //
  // DEV_EASY_AUTH_LOGIN: backend LOCAL em AUTH_MODE=entra_id. O proxy injeta
  // um X-MS-CLIENT-PRINCIPAL com esse UPN em `preferred_username`, como faz o
  // App Service. Contra hmg isto não funciona: o Easy Auth descarta o header
  // vindo de fora.
  //
  // DEV_EASY_AUTH_COOKIE: backend de HMG (VITE_BACKEND_URL). Valor do cookie
  // AppServiceAuthSession, copiado do navegador depois de entrar em hmg. O
  // proxy repassa o cookie e o Easy Auth trata a chamada como a do navegador
  // logado. É uma credencial pessoal e expira: com 401, copie de novo.
  const loginSimulado = env.DEV_EASY_AUTH_LOGIN?.trim();
  const cookieSessao = env.DEV_EASY_AUTH_COOKIE?.trim();
  const cabecalhosEasyAuth: Record<string, string> = {};
  if (loginSimulado) {
    cabecalhosEasyAuth["X-MS-CLIENT-PRINCIPAL"] = Buffer.from(
      JSON.stringify({
        claims: [{ typ: "preferred_username", val: loginSimulado }],
      }),
    ).toString("base64");
  }
  if (cookieSessao) {
    cabecalhosEasyAuth["Cookie"] = `AppServiceAuthSession=${cookieSessao}`;
  }

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
        rotas.map((rota) => [
          rota,
          { target: alvo, changeOrigin: true, headers: cabecalhosEasyAuth },
        ]),
      ),
    },
  };
});
