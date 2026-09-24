import { useEffect, useState, type FormEvent } from "react";
import { Loader2 } from "lucide-react";
import { ApiError, login } from "@/lib/api";
import { gravarSessao, type Sessao } from "@/auth/sessao";
import { USA_SENHA } from "@/auth/modo";
import {
  encerrarLoginMicrosoft,
  resolverEntrada,
  URL_LOGIN_MICROSOFT,
  type Entrada,
} from "@/auth/entraId";
import { AcessoBloqueado } from "@/pages/AcessoBloqueado";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const CHAVE_MARCA_DE_LOGIN = "pedai.login-solicitado";

function lerMarcaDeLogin(): boolean {
  try {
    return sessionStorage.getItem(CHAVE_MARCA_DE_LOGIN) !== null;
  } catch {
    return false;
  }
}

function gravarMarcaDeLogin(): void {
  try {
    sessionStorage.setItem(CHAVE_MARCA_DE_LOGIN, "1");
  } catch {
    return;
  }
}

function apagarMarcaDeLogin(): void {
  try {
    sessionStorage.removeItem(CHAVE_MARCA_DE_LOGIN);
  } catch {
    return;
  }
}

interface LoginProps {
  onEntrar: (sessao: Sessao) => void;
  /** Motivo pelo qual a pessoa voltou para cá, hoje só a sessão vencida.
   *  Some assim que ela tenta entrar de novo. */
  aviso?: string | null;
}

/**
 * Acesso ao Ped.AI.
 *
 * No modo `senha`, o propagandista entra com o e-mail corporativo e a senha
 * recebida. O backend confere contra o hash em `tb_portal_acesso` e devolve
 * um token de curta duração.
 *
 * No modo `entra_id`, os dois campos dão lugar a um botão de acesso
 * corporativo. O layout permanece o mesmo. Ver `src/auth/modo.ts`.
 */
export function Login({ onEntrar, aviso }: LoginProps) {
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState<string | null>(aviso ?? null);
  // 403 ACESSO_BLOQUEADO em POST /auth/login (modo senha). Mensagem vinda do
  // backend, não texto fixo aqui — única fonte é
  // backend/app/auth/status_acesso.py, ver AcessoBloqueado.tsx.
  const [bloqueado, setBloqueado] = useState<string | null>(null);
  const [entrada, setEntrada] = useState<Entrada | null>(() =>
    !USA_SENHA && lerMarcaDeLogin() ? null : { estado: "anonimo" },
  );

  // Aviso que chega depois da montagem também precisa aparecer. Hoje o Login
  // é sempre remontado quando a sessão cai, então o estado inicial bastaria,
  // mas isso é acidente do desenho atual e não contrato. Achado da revisão
  // independente de 03/09/2026.
  useEffect(() => {
    if (aviso) setErro(aviso);
  }, [aviso]);
  const [carregando, setCarregando] = useState(false);

  async function entrarComMicrosoft() {
    setEntrada(null);
    const resultado = await resolverEntrada();
    if (resultado.estado === "autenticado") {
      onEntrar(resultado.sessao);
      return;
    }
    if (resultado.estado === "anonimo") {
      gravarMarcaDeLogin();
      window.location.assign(URL_LOGIN_MICROSOFT);
      return;
    }
    setEntrada(resultado);
  }

  useEffect(() => {
    if (USA_SENHA || !lerMarcaDeLogin()) return;
    apagarMarcaDeLogin();
    let cancelado = false;
    resolverEntrada().then((resultado) => {
      if (cancelado) return;
      if (resultado.estado === "autenticado") {
        onEntrar(resultado.sessao);
        return;
      }
      setEntrada(resultado);
    });
    return () => {
      cancelado = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const podeEnviar = email.trim() !== "" && senha.trim() !== "";

  async function entrar(evento: FormEvent) {
    evento.preventDefault();
    if (!podeEnviar || carregando) return;

    setErro(null);
    setCarregando(true);

    try {
      const resposta = await login(email.trim(), senha.trim());
      const sessao: Sessao = {
        email: email.trim(),
        nome: resposta.nome ?? null,
        setor: resposta.setor,
        token: resposta.access_token,
        // `expira_em` vem como duração em segundos; a sessão guarda o
        // instante absoluto, que é o que a leitura precisa comparar.
        expiraEm: Date.now() + resposta.expira_em * 1000,
      };
      gravarSessao(sessao);
      onEntrar(sessao);
    } catch (excecao) {
      if (excecao instanceof ApiError && excecao.codigo === "ACESSO_BLOQUEADO") {
        setBloqueado(excecao.message);
        setSenha("");
        return;
      }
      setErro(
        excecao instanceof ApiError
          ? excecao.message
          : "Erro inesperado ao entrar. Tente novamente.",
      );
      // A senha não permanece no campo depois de uma tentativa recusada.
      setSenha("");
    } finally {
      setCarregando(false);
    }
  }

  if (bloqueado) {
    return (
      <AcessoBloqueado
        mensagem={bloqueado}
        onSair={() => {
          setBloqueado(null);
          setSenha("");
        }}
      />
    );
  }

  // 403 ACESSO_BLOQUEADO em GET /auth/contexto (modo entra_id): a pessoa
  // autenticou na Microsoft, mas está BLOQUEADO em tb_perfil_portal. Sem
  // isto, a tela voltava ao botão de entrar, sem mensagem, e cada clique
  // repetia a mesma checagem. "Sair" encerra a sessão do Easy Auth para
  // permitir entrar com outra conta.
  if (!USA_SENHA && entrada?.estado === "bloqueado") {
    return (
      <AcessoBloqueado mensagem={entrada.mensagem} onSair={encerrarLoginMicrosoft} />
    );
  }

  if (!USA_SENHA) {
    return (
      <TelaEntraId
        entrada={entrada}
        aviso={erro}
        onEntrar={entrarComMicrosoft}
      />
    );
  }

  return (
    // Mobile-first: uma coluna por padrão; o painel de marca só aparece a
    // partir de lg, onde há largura para ele sem espremer o formulário.
    <div className="grid min-h-dvh grid-cols-1 lg:grid-cols-[1fr_minmax(0,44%)]">
      <main className="flex flex-col justify-center px-6 py-12 sm:px-10 lg:px-16">
        <div className="mx-auto w-full max-w-md">
          <Card className="p-6 sm:p-8">
            <p className="text-sm font-semibold tracking-[0.08em] text-[var(--color-primary)] uppercase">
              Ped.AI
            </p>

            <h1 className="mt-6 text-3xl leading-tight font-semibold sm:text-4xl">
              Acessar o portal
            </h1>
            <p className="mt-2 text-sm text-[var(--color-muted-foreground)]">
              Use seu e-mail corporativo e a senha que você recebeu.
            </p>

            <form onSubmit={entrar} className="mt-8" noValidate>
              <Label htmlFor="email">E-mail corporativo</Label>
              <Input
                id="email"
                name="email"
                type="email"
                inputMode="email"
                autoComplete="username"
                autoFocus
                required
                placeholder="nome.sobrenome@ache.com.br"
                value={email}
                onChange={(evento) => setEmail(evento.target.value)}
                aria-invalid={erro ? true : undefined}
                aria-describedby={erro ? "erro-login" : undefined}
              />

              <div className="mt-4">
                <Label htmlFor="senha">Senha</Label>
                <Input
                  id="senha"
                  name="senha"
                  type="password"
                  autoComplete="current-password"
                  // A senha vem em blocos separados por hífen: sem correção
                  // automática nem primeira letra maiúscula no celular.
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                  required
                  value={senha}
                  onChange={(evento) => setSenha(evento.target.value)}
                  aria-invalid={erro ? true : undefined}
                  aria-describedby={erro ? "erro-login" : undefined}
                />
              </div>

              {erro && (
                <Alert className="mt-4">
                  <span id="erro-login">{erro}</span>
                </Alert>
              )}

              <Button
                type="submit"
                size="lg"
                className="mt-6 w-full"
                disabled={carregando || !podeEnviar}
              >
                {carregando ? "Entrando..." : "Entrar"}
              </Button>
            </form>

            {USA_SENHA && (
              <p className="mt-6 text-xs text-[var(--color-muted-foreground)]">
                Não recebeu sua senha ou precisa de uma nova? Fale com o time
                do Ped.AI.
              </p>
            )}

            <div className="mt-8 flex items-center gap-3" aria-hidden="true">
              <span className="h-px flex-1 bg-[var(--color-border)]" />
              <span className="text-xs tracking-[0.08em] text-[var(--color-muted-foreground)] uppercase">
                conta corporativa
              </span>
              <span className="h-px flex-1 bg-[var(--color-border)]" />
            </div>

            <button
              type="button"
              disabled
              aria-describedby="microsoft-login-status"
              className="mt-4 inline-flex h-12 w-full cursor-not-allowed items-center justify-center gap-2 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-card)] px-6 text-base font-medium text-[var(--color-foreground)] opacity-60"
            >
              <img src="/microsoft.svg" alt="" className="h-4 w-4 shrink-0" />
              Entrar com a conta Microsoft
            </button>
            <p id="microsoft-login-status" className="mt-2 text-center text-xs text-[var(--color-destructive)]">
              Funcionalidade em desenvolvimento
            </p>
          </Card>
        </div>
      </main>

      <aside
        aria-hidden="true"
        className="relative hidden overflow-hidden bg-[var(--color-primary)] lg:block"
      >
        <span className="absolute -top-32 -right-40 h-[26rem] w-[26rem] rounded-full border border-white/15" />
        <span className="absolute -bottom-32 -left-36 h-80 w-80 rounded-full border border-white/15" />

        <div className="relative flex h-full flex-col justify-center px-14 text-white">
          <p className="text-6xl leading-none font-bold tracking-tight">achē</p>
          <p className="mt-4 text-lg">mais vida para você</p>
        </div>
      </aside>
    </div>
  );
}

/**
 * Tela de acesso do modo `entra_id`: sem formulário, sem senha. `entrada`
 * é o resultado de `resolverEntrada()` (`null` enquanto ainda não voltou).
 *
 * O bloqueio (`ACESSO_BLOQUEADO`) é tratado em `Login` (mesmo componente
 * `AcessoBloqueado` do modo senha) antes de chegar aqui — este componente só
 * recebe os demais estados.
 */
function TelaEntraId({
  entrada,
  aviso,
  onEntrar,
}: {
  entrada: Entrada | null;
  aviso: string | null;
  onEntrar: () => void;
}) {
  const travado = entrada === null;
  const rotulo = travado ? "Verificando seu acesso..." : "Entrar com Microsoft";

  const mensagem =
    entrada?.estado === "recusado" || entrada?.estado === "erro"
      ? entrada.mensagem
      : aviso;

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center bg-[var(--color-muted)] px-4 py-10 baixo:py-6">
      <header className="flex flex-col items-center text-center">
        <span
          aria-hidden="true"
          className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-[var(--color-primary)] text-xl font-bold text-[var(--color-primary-foreground)] baixo:h-12 baixo:w-12"
        >
          R
        </span>

        <div className="mt-5 flex items-center justify-center gap-2 baixo:mt-4">
          <h1 className="text-2xl font-bold tracking-tight">PedAI</h1>
          <span className="rounded-md bg-[var(--color-accent)] px-1.5 py-0.5 text-[10px] leading-4 font-bold tracking-wide text-[var(--color-accent-foreground)] uppercase">
            Aché
          </span>
        </div>

        <p className="mt-2 text-xs text-[var(--color-muted-foreground)]">
          Inteligência comercial para propagandistas
        </p>
      </header>

      <Card className="mt-6 w-full max-w-[26rem] rounded-3xl p-6 baixo:mt-5 baixo:p-6 sm:p-8">
        <h2 className="text-center text-lg font-semibold">Bem-vindo</h2>
        <p className="mt-2 text-center text-sm text-[var(--color-muted-foreground)]">
          Use sua conta corporativa Microsoft para acessar o PedAI.
        </p>

        {mensagem && (
          <Alert className="mt-4">
            <span id="erro-login">{mensagem}</span>
          </Alert>
        )}

        <div className="mt-6 flex items-center gap-3" aria-hidden="true">
          <span className="h-px flex-1 bg-[var(--color-border)]" />
          <span className="text-xs text-[var(--color-muted-foreground)]">
            conta corporativa
          </span>
          <span className="h-px flex-1 bg-[var(--color-border)]" />
        </div>

        <a
          href={URL_LOGIN_MICROSOFT}
          onClick={(evento) => {
            evento.preventDefault();
            if (!travado) onEntrar();
          }}
          aria-disabled={travado || undefined}
          aria-busy={travado || undefined}
          tabIndex={travado ? -1 : undefined}
          aria-describedby={mensagem ? "erro-login" : undefined}
          className={`mt-4 inline-flex h-12 w-full items-center justify-center gap-2.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] shadow-sm px-6 text-sm font-semibold text-[var(--color-foreground)] transition-colors outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] focus-visible:ring-offset-2 ${
            travado
              ? "pointer-events-none cursor-not-allowed opacity-60"
              : "hover:bg-[var(--color-muted)]"
          }`}
        >
          {travado ? (
            <Loader2
              className="h-[18px] w-[18px] shrink-0 animate-spin"
              aria-hidden="true"
            />
          ) : (
            <img
              src="/microsoft.svg"
              alt=""
              aria-hidden="true"
              className="h-[18px] w-[18px] shrink-0"
            />
          )}
          {rotulo}
        </a>

        {(entrada?.estado === "recusado" || entrada?.estado === "erro") && (
          <button
            type="button"
            onClick={encerrarLoginMicrosoft}
            className="mt-4 w-full text-center text-xs text-[var(--color-muted-foreground)] underline underline-offset-2"
          >
            Sair e tentar com outra conta
          </button>
        )}

        <p className="mt-5 text-center text-[11px] leading-[18px] text-[var(--color-muted-foreground)] baixo:mt-4">
          Ao entrar, você concorda com os termos de uso e a política de
          privacidade da Aché.
        </p>
      </Card>

      <p className="mt-8 text-center text-[11px] text-[var(--color-muted-foreground)] baixo:mt-6">
        © {new Date().getFullYear()} Aché Laboratórios. Todos os direitos
        reservados.
      </p>
    </div>
  );
}
