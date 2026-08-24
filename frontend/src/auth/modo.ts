/**
 * Modo de autenticação da interface. Precisa acompanhar `AUTH_MODE` do
 * backend, caso contrário a tela pede uma credencial que o servidor não
 * aceita.
 *
 * - `senha`: e-mail corporativo e senha entregue ao propagandista, enviados
 *   em `POST /auth/login`. Modo do piloto.
 * - `entra_id`: acesso pela conta corporativa Microsoft, sem credencial
 *   passando pela interface.
 *
 * Na migração para o Entra ID, três pontos concentram a mudança:
 *   1. VITE_AUTH_MODE=entra_id no build;
 *   2. criar `src/auth/entraId.ts` com a aquisição do token e ligá-lo a
 *      `configurarProvedorDeToken()` de `src/lib/api.ts`;
 *   3. no backend, AUTH_MODE=entra_id junto com AUTH_REQUIRE_JWT=true.
 *
 * A tela de login permanece a mesma, trocando os campos pelo botão de acesso
 * corporativo.
 */

export type ModoAuth = "senha" | "entra_id";

export const MODO_AUTH: ModoAuth =
  import.meta.env.VITE_AUTH_MODE === "entra_id" ? "entra_id" : "senha";

export const USA_SENHA = MODO_AUTH === "senha";
