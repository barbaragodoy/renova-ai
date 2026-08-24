import { useState } from "react";
import { Home, MessageSquare, Star, UserCircle } from "lucide-react";
import { Login } from "@/pages/Login";
import { Recomendacoes } from "@/pages/Recomendacoes";
import { Usuario } from "@/pages/Usuario";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { configurarProvedorDeToken } from "@/lib/api";
import { lerSessao, limparSessao, type Sessao } from "@/auth/sessao";

// Sessão atual em módulo, para o cliente HTTP ler o token sem depender do
// ciclo de renderização do React. Toda escrita passa por aplicarSessao().
let sessaoAtual: Sessao | null = lerSessao();
configurarProvedorDeToken(() => sessaoAtual?.token ?? null);

/** Abas do portal, na mesma ordem do protótipo.
 *
 *  Comunicados entra numa próxima etapa, mas fica visível desde já para a
 *  navegação não mudar de forma quando for ligada. */
const ABAS = [
  { id: "home", rotulo: "Home", icone: Home },
  { id: "recomendacoes", rotulo: "Recom.", icone: Star },
  { id: "comunicados", rotulo: "Comun.", icone: MessageSquare },
  { id: "usuario", rotulo: "Usuário", icone: UserCircle },
] as const;

type AbaId = (typeof ABAS)[number]["id"];

function EmBreve() {
  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6">
      <p className="text-[var(--color-muted-foreground)]">
        Esta jornada será adicionada nas próximas etapas.
      </p>
    </div>
  );
}

export default function App() {
  const [sessao, setSessao] = useState<Sessao | null>(sessaoAtual);
  const [aba, setAba] = useState<AbaId>("home");

  function aplicarSessao(nova: Sessao | null) {
    sessaoAtual = nova;
    setSessao(nova);
  }

  if (!sessao) return <Login onEntrar={aplicarSessao} />;

  function sair() {
    limparSessao();
    aplicarSessao(null);
    setAba("home");
  }

  return (
    // Três faixas: cabeçalho, conteúdo rolável e navegação. O `minmax(0,1fr)`
    // no meio é o que impede a faixa central de crescer além da tela e empurrar
    // a navegação para fora da área visível no celular.
    <div className="grid h-dvh grid-rows-[auto_minmax(0,1fr)_auto]">
      <header className="flex items-center justify-between gap-4 bg-[var(--color-primary)] px-4 py-3 text-white sm:px-6">
        <span className="font-semibold tracking-wide">Portal RenovAI</span>
        <Button
          variant="ghost"
          onClick={sair}
          className="text-white hover:bg-white/15"
        >
          Sair
        </Button>
      </header>

      <main className="overflow-y-auto bg-[var(--color-muted)]">
        {aba === "usuario" && <Usuario email={sessao.email} />}

        {aba === "home" && (
          <div className="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6">
            <h1 className="text-2xl font-semibold">
              Olá{sessao.nome ? `, ${sessao.nome.split(" ")[0]}` : ""}
            </h1>
            <p className="mt-1 text-[var(--color-muted-foreground)]">
              Setor {sessao.setor}
            </p>

            <div className="mt-8 rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-card)] p-6">
              <p className="text-[var(--color-muted-foreground)]">
                As jornadas do portal serão adicionadas nas próximas etapas.
              </p>
            </div>
          </div>
        )}

        {aba === "recomendacoes" && (
          <Recomendacoes email={sessao.email} setor={sessao.setor} />
        )}

        {aba === "comunicados" && <EmBreve />}
      </main>

      <nav
        aria-label="Navegação principal"
        className="flex border-t border-[var(--color-border)] bg-[var(--color-card)]"
      >
        {ABAS.map(({ id, rotulo, icone: Icone }) => {
          const ativa = aba === id;
          return (
            <button
              key={id}
              type="button"
              onClick={() => setAba(id)}
              aria-current={ativa ? "page" : undefined}
              // 56px de altura: o alvo de toque continua confortável mesmo com
              // ícone e rótulo empilhados.
              className={cn(
                "flex h-14 flex-1 flex-col items-center justify-center gap-0.5 text-xs font-medium transition-colors",
                ativa
                  ? "text-[var(--color-primary)]"
                  : "text-[var(--color-muted-foreground)]",
              )}
            >
              <Icone className="h-5 w-5" aria-hidden="true" />
              <span>{rotulo}</span>
            </button>
          );
        })}
      </nav>
    </div>
  );
}
