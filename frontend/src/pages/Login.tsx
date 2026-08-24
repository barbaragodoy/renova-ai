import { useState, type FormEvent } from "react";
import { ApiError, login } from "@/lib/api";
import { gravarSessao, type Sessao } from "@/auth/sessao";
import { USA_SENHA } from "@/auth/modo";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface LoginProps {
  onEntrar: (sessao: Sessao) => void;
}

/**
 * Acesso ao Portal RenovAI.
 *
 * No modo `senha`, o propagandista entra com o e-mail corporativo e a senha
 * recebida. O backend confere contra o hash em `tb_portal_acesso` e devolve
 * um token de curta duração.
 *
 * No modo `entra_id`, os dois campos dão lugar a um botão de acesso
 * corporativo. O layout permanece o mesmo. Ver `src/auth/modo.ts`.
 */
export function Login({ onEntrar }: LoginProps) {
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(false);

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
      };
      gravarSessao(sessao);
      onEntrar(sessao);
    } catch (excecao) {
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

  return (
    // Mobile-first: uma coluna por padrão; o painel de marca só aparece a
    // partir de lg, onde há largura para ele sem espremer o formulário.
    <div className="grid min-h-dvh grid-cols-1 lg:grid-cols-[1fr_minmax(0,44%)]">
      <main className="flex flex-col justify-center px-6 py-12 sm:px-10 lg:px-16">
        <div className="mx-auto w-full max-w-sm">
          <p className="text-sm font-semibold tracking-[0.08em] text-[var(--color-primary)] uppercase">
            Portal RenovAI
          </p>

          <h1 className="mt-6 text-3xl leading-tight font-semibold sm:text-4xl">
            Acessar o portal
          </h1>
          <p className="mt-2 text-[var(--color-muted-foreground)]">
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
            <p className="mt-6 text-sm text-[var(--color-muted-foreground)]">
              Não recebeu sua senha ou precisa de uma nova? Fale com o time do
              RenovAI.
            </p>
          )}
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
