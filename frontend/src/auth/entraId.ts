/**
 * Entrada pela conta corporativa Microsoft.
 *
 * Quem autentica não é o portal: é o Azure App Service Easy Auth, ativo no
 * App Service. Ele intercepta a requisição antes do FastAPI e injeta a
 * identidade em `X-MS-CLIENT-PRINCIPAL-NAME`, que o backend lê em
 * `auth/jwt_auth.py` quando `AUTH_MODE=entra_id`. Não há MSAL no navegador,
 * não há token guardado neste módulo e `POST /auth/login` deixa de existir
 * para a interface (o backend devolve 404).
 *
 * Este módulo faz três coisas: dá o endereço de login da plataforma,
 * pergunta ao backend quem voltou de lá (`resolverEntrada`, via
 * `GET /auth/contexto`, autenticado pelo cookie do Easy Auth) e manda a
 * pessoa para o endpoint de logout.
 *
 * A sessão resultante nunca é gravada em sessionStorage (ver
 * `src/auth/sessao.ts` e o uso condicionado a `USA_SENHA` em `App.tsx`): ao
 * recarregar a página (F5), a identidade é sempre reconfirmada aqui, contra
 * o cookie do Easy Auth — nunca reaproveitada de um cache local. Extraído de
 * `virada-entraid-front` (AcheInfo_Apps) e reimplementado sobre o modelo de
 * sessão atual de dev, que ganhou `email` obrigatório e outras telas desde
 * que aquela branch foi criada.
 *
 * Em desenvolvimento (`npm run dev`) os caminhos `/.auth/*` não existem: são
 * da plataforma, não do FastAPI. A conferência inicial devolve `anonimo`, a
 * tela de login aparece normalmente e o botão leva a lugar nenhum. Validar o
 * fluxo completo exige o ambiente publicado com Easy Auth ativo.
 */

import { ApiError, obterContexto, obterSessaoAdmin } from "@/lib/api";
import type { Sessao } from "@/auth/sessao";

/** Endereços da plataforma, como passados pelo time de infraestrutura.
 *
 *  O destino de volta é a raiz nos dois casos: o portal é uma SPA de rota
 *  única, e é em `/` que a tela de login roda a conferência que monta a
 *  sessão. */
export const URL_LOGIN_MICROSOFT = "/.auth/login/aad?post_login_redirect_uri=/";
const URL_LOGOUT_MICROSOFT = "/.auth/logout?post_logout_redirect_uri=/";

/** Sai da conta corporativa, e não só do portal.
 *
 *  Limpar o estado do React sem passar por aqui deixaria o cookie do Easy
 *  Auth de pé: a próxima conferência (`resolverEntrada`) reconheceria a
 *  mesma pessoa e a colocaria de volta dentro do portal sem ela pedir. */
export function encerrarLoginMicrosoft(): void {
  window.location.assign(URL_LOGOUT_MICROSOFT);
}

export type Entrada =
  /** Cookie válido e cadastro encontrado: pode entrar. */
  | { estado: "autenticado"; sessao: Sessao }
  /** Ninguém autenticado ainda. É a resposta esperada na primeira visita. */
  | { estado: "anonimo" }
  /** Autenticou na Microsoft, mas STATUS_ACESSO não é ATIVO em
   *  tb_perfil_portal (ou a pessoa não tem linha nenhuma lá — deny-by-default,
   *  ver `backend/app/auth/status_acesso.py`). Mesma tela de bloqueio do
   *  modo senha. */
  | { estado: "bloqueado"; mensagem: string }
  /** Autenticou na Microsoft, mas o portal não aceita: sem cadastro em
   *  `tb_propagandistas`, ou mais de um cadastro para a mesma identidade. */
  | { estado: "recusado"; mensagem: string }
  /** Não deu para saber: rede fora, servidor fora. Vale tentar de novo. */
  | { estado: "erro"; mensagem: string };

/**
 * Descobre se já existe alguém autenticado e monta a sessão do portal.
 *
 * `GET /auth/contexto` é a autoridade aqui: ele só responde quando o Easy
 * Auth entregou uma identidade, e resolve o setor (e agora também o e-mail
 * corporativo, em `ContextoResponse.email`) a partir dela. A tela de login
 * chama isto ao abrir, o que cobre os dois lados do redirecionamento — a
 * primeira visita, que volta `anonimo`, e a volta do login, que volta
 * `autenticado`.
 */
export async function resolverEntrada(): Promise<Entrada> {
  let contexto;
  try {
    contexto = await obterContexto();
  } catch (excecao) {
    if (excecao instanceof ApiError && excecao.status === 401) {
      return { estado: "anonimo" };
    }
    if (excecao instanceof ApiError && excecao.codigo === "ACESSO_BLOQUEADO") {
      return { estado: "bloqueado", mensagem: excecao.message };
    }
    return {
      estado: "erro",
      mensagem:
        excecao instanceof ApiError
          ? excecao.message
          : "Não foi possível verificar seu acesso. Tente novamente.",
    };
  }

  if (contexto.status === "SETOR_RESOLVIDO" && contexto.setor && contexto.email) {
    return {
      estado: "autenticado",
      sessao: {
        email: contexto.email,
        nome: contexto.nome ?? null,
        setor: contexto.setor,
      },
    };
  }

  // Sem propagandista vinculado (normalmente PROPAGANDISTA_NAO_ENCONTRADO):
  // ainda pode ser administrador — o mesmo padrão dos 13 administradores
  // reais em tb_perfil_portal, sem rep_matricula (ver Fase 3/known-issues).
  // GET /admin/sessao não depende de tb_propagandistas, só de
  // tb_perfil_portal.PERFIL_ACESSO. `setor: ""` é seguro aqui: App.tsx só lê
  // `sessao.setor` depois que um administrador escolhe alguém no seletor
  // (SeletorDePropagandista), e nesse ponto usa sessao.verComo.setor, nunca
  // este placeholder.
  try {
    const admin = await obterSessaoAdmin();
    if (admin.administrador) {
      return {
        estado: "autenticado",
        sessao: { email: admin.identidade, nome: null, setor: "" },
      };
    }
  } catch {
    // Identidade já passou por STATUS_ACESSO (exigir_acesso_liberado roda
    // antes de qualquer checagem de administrador), então uma falha aqui não
    // é ACESSO_BLOQUEADO de novo — cai para "recusado" abaixo, mesma
    // mensagem que valeria sem esta tentativa extra.
  }

  return {
    estado: "recusado",
    mensagem:
      contexto.mensagem ??
      "Sua conta corporativa não tem cadastro de propagandista no PedAI.",
  };
}
