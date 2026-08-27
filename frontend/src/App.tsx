import { useEffect, useRef, useState } from "react";
import { Home, Star, TrendingUp, UserCircle } from "lucide-react";
import { Login } from "@/pages/Login";
import { Recomendacoes } from "@/pages/Recomendacoes";
import { Usuario } from "@/pages/Usuario";
import { Chat } from "@/pages/Chat";
import { Ranking } from "@/pages/Ranking";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { configurarProvedorDeToken } from "@/lib/api";
import { lerSessao, limparSessao, type Sessao } from "@/auth/sessao";

// Sessão atual em módulo, para o cliente HTTP ler o token sem depender do
// ciclo de renderização do React. Toda escrita passa por aplicarSessao().
let sessaoAtual: Sessao | null = lerSessao();
configurarProvedorDeToken(() => sessaoAtual?.token ?? null);

/** Abas do portal, na ordem do protótipo, menos uma.
 *
 *  O protótipo tem cinco: Home, Recomendações, Ranking, Comunicados e
 *  Usuário. Comunicados fica fora do escopo por decisão de George em
 *  10/08/2026, então restam quatro, todas ligadas. Home é a conversa. */
const ABAS = [
  { id: "home", rotulo: "Home", icone: Home },
  { id: "recomendacoes", rotulo: "Recom.", icone: Star },
  { id: "ranking", rotulo: "Ranking", icone: TrendingUp },
  { id: "usuario", rotulo: "Usuário", icone: UserCircle },
] as const;

type AbaId = (typeof ABAS)[number]["id"];

/** Faixa de uma aba, que continua montada quando a pessoa sai dela.
 *
 *  O portal é usado em pé, na porta do consultório, alternando entre abas o
 *  tempo todo. Desmontar a aba ao sair jogava fora tudo: a posição no ranking,
 *  as páginas já carregadas, a conversa do chat, o texto digitado. Voltar
 *  significava recomeçar e esperar de novo pela rede.
 *
 *  Duas decisões aqui:
 *
 *  1. **Montagem preguiçosa.** A aba só é criada no primeiro acesso a ela.
 *     Montar as quatro no login dispararia quatro consultas ao Databricks de
 *     uma vez, e a pessoa pagaria a espera de telas que talvez nem abra.
 *
 *  2. **Rolagem por aba.** Cada aba tem o próprio contêiner de rolagem, e a
 *     posição é guardada e devolvida na mão. `display:none` não preserva
 *     `scrollTop` de forma confiável entre navegadores, então não dá para
 *     depender disso. */
function Faixa({
  ativa,
  children,
}: {
  ativa: boolean;
  children: React.ReactNode;
}) {
  const caixa = useRef<HTMLDivElement>(null);
  const posicao = useRef(0);

  useEffect(() => {
    if (ativa && caixa.current) caixa.current.scrollTop = posicao.current;
  }, [ativa]);

  return (
    <div
      ref={caixa}
      hidden={!ativa}
      onScroll={(e) => {
        posicao.current = e.currentTarget.scrollTop;
      }}
      className="h-full overflow-y-auto"
    >
      {children}
    </div>
  );
}

export default function App() {
  const [sessao, setSessao] = useState<Sessao | null>(sessaoAtual);
  const [aba, setAba] = useState<AbaId>("home");
  // Abas já abertas ao menos uma vez. Só essas ficam montadas.
  const [visitadas, setVisitadas] = useState<Set<AbaId>>(new Set(["home"]));
  // Pergunta que o Ranking manda para o chat pelo botão da gaveta. Fica aqui,
  // e não dentro de cada aba, porque atravessa as duas.
  const [perguntaParaOChat, setPerguntaParaOChat] = useState<string | null>(null);

  function conversarSobre(nomeMedico: string) {
    setPerguntaParaOChat(`Vou visitar ${nomeMedico}`);
    trocarAba("home");
  }

  function trocarAba(id: AbaId) {
    setVisitadas((anteriores) =>
      anteriores.has(id) ? anteriores : new Set(anteriores).add(id),
    );
    setAba(id);
  }

  function aplicarSessao(nova: Sessao | null) {
    sessaoAtual = nova;
    setSessao(nova);
  }

  if (!sessao) return <Login onEntrar={aplicarSessao} />;

  function sair() {
    limparSessao();
    aplicarSessao(null);
    setAba("home");
    // Sair descarta o que estava carregado: a próxima pessoa a entrar neste
    // aparelho não pode ver o ranking nem a conversa da anterior.
    setVisitadas(new Set(["home"]));
    setPerguntaParaOChat(null);
  }

  return (
    // Três faixas: cabeçalho, conteúdo rolável e navegação. O `minmax(0,1fr)`
    // no meio é o que impede a faixa central de crescer além da tela e empurrar
    // a navegação para fora da área visível no celular.
    <div className="grid h-dvh grid-rows-[auto_minmax(0,1fr)_auto]">
      <header className="flex items-center justify-between gap-4 bg-[var(--color-primary)] px-4 py-3 text-white sm:px-6">
        <span className="font-semibold tracking-wide">PedAI</span>
        <Button
          variant="ghost"
          onClick={sair}
          className="text-white hover:bg-white/15"
        >
          Sair
        </Button>
      </header>

      <main className="h-full min-h-0 overflow-hidden bg-[var(--color-muted)]">
        {visitadas.has("home") && (
          <Faixa ativa={aba === "home"}>
            <Chat
              nome={sessao.nome}
              perguntaPendente={perguntaParaOChat}
              aoConsumirPergunta={() => setPerguntaParaOChat(null)}
            />
          </Faixa>
        )}

        {visitadas.has("recomendacoes") && (
          <Faixa ativa={aba === "recomendacoes"}>
            <Recomendacoes email={sessao.email} setor={sessao.setor} />
          </Faixa>
        )}

        {visitadas.has("ranking") && (
          <Faixa ativa={aba === "ranking"}>
            <Ranking
              email={sessao.email}
              setor={sessao.setor}
              onConversar={conversarSobre}
            />
          </Faixa>
        )}

        {visitadas.has("usuario") && (
          <Faixa ativa={aba === "usuario"}>
            <Usuario email={sessao.email} />
          </Faixa>
        )}
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
              onClick={() => trocarAba(id)}
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
