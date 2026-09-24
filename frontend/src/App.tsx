import { useEffect, useRef, useState } from "react";
import { Eye, Home, Star, TrendingUp, UserCircle } from "lucide-react";
import { Login } from "@/pages/Login";
import { SeletorDePropagandista } from "@/pages/SeletorDePropagandista";
import { Recomendacoes } from "@/pages/Recomendacoes";
import { Usuario } from "@/pages/Usuario";
import { Home as PaginaHome } from "@/pages/Home";
import { Ranking } from "@/pages/Ranking";
import { Header } from "@/components/Header";
import { MenuLateral } from "@/components/MenuLateral";
import { cn } from "@/lib/utils";
import {
  configurarAoExpirarSessao,
  configurarProvedorDeToken,
  configurarVerComo,
  obterSessaoAdmin,
} from "@/lib/api";
import {
  gravarSessao,
  lerSessao,
  limparSessao,
  type Sessao,
  type VerComo,
} from "@/auth/sessao";

// Sessão atual em módulo, para o cliente HTTP ler o token sem depender do
// ciclo de renderização do React. Toda escrita passa por aplicarSessao().
let sessaoAtual: Sessao | null = lerSessao();
configurarProvedorDeToken(() => sessaoAtual?.token ?? null);
configurarVerComo(sessaoAtual?.verComo?.setor ?? null);

/** Abas do portal, na ordem do protótipo, menos uma.
 *
 *  O protótipo tem cinco: Home, Recomendações, Ranking, Comunicados e
 *  Usuário. Comunicados fica fora do escopo por decisão de George em
 *  10/08/2026, então restam quatro, todas ligadas. Home é a conversa. */
const ABAS = [
  { id: "home", rotulo: "Home", rotuloCurto: "Home", icone: Home },
  { id: "recomendacoes", rotulo: "Recomendações", rotuloCurto: "Recom.", icone: Star },
  { id: "ranking", rotulo: "Ranking", rotuloCurto: "Ranking", icone: TrendingUp },
  { id: "usuario", rotulo: "Usuário", rotuloCurto: "Usuário", icone: UserCircle },
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
  const [menuAberto, setMenuAberto] = useState(false);
  // Abas já abertas ao menos uma vez. Só essas ficam montadas.
  const [visitadas, setVisitadas] = useState<Set<AbaId>>(new Set(["home"]));
  // Pergunta que o Ranking manda para o chat pelo botão da gaveta. Fica aqui,
  // e não dentro de cada aba, porque atravessa as duas.
  // Motivo do retorno ao login. Hoje só existe um: a sessão venceu.
  const [avisoDeSessao, setAvisoDeSessao] = useState<string | null>(null);
  // Se quem entrou está na lista administrativa. `null` enquanto o servidor
  // não respondeu; nesse intervalo a tela fica em branco em vez de piscar as
  // abas de um propagandista que talvez nem exista.
  const [administrador, setAdministrador] = useState<boolean | null>(null);

  // Quem é administrador vê o seletor no lugar das abas até escolher alguém.
  // A resposta não é decisão de segurança: o servidor confere a lista a cada
  // chamada e ignora o header de quem não está nela.
  useEffect(() => {
    if (!sessao) return;
    let cancelado = false;
    obterSessaoAdmin(sessao.email)
      .then((resposta) => {
        if (!cancelado) setAdministrador(resposta.administrador);
      })
      .catch(() => {
        if (!cancelado) setAdministrador(false);
      });
    return () => {
      cancelado = true;
    };
  }, [sessao]);

  /** Encerra a sessão e devolve a pessoa ao login, descartando o que estava
   *  carregado: quem entrar depois neste aparelho não pode ver o ranking nem
   *  a conversa de quem estava antes. */
  function encerrarSessao(aviso: string | null) {
    limparSessao();
    configurarVerComo(null);
    sessaoAtual = null;
    setSessao(null);
    setAdministrador(null);
    setAba("home");
    setVisitadas(new Set(["home"]));
    setAvisoDeSessao(aviso);
  }

  // O token vale 60 minutos. Quando ele vence, a primeira chamada de negócio
  // volta 401 e o cliente HTTP avisa aqui, em vez de a tela seguir exibindo
  // uma pessoa autenticada cujas chamadas todas falham.
  useEffect(() => {
    configurarAoExpirarSessao(() =>
      encerrarSessao("Sua sessão expirou. Entre novamente."),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function trocarAba(id: AbaId) {
    setVisitadas((anteriores) =>
      anteriores.has(id) ? anteriores : new Set(anteriores).add(id),
    );
    setAba(id);
  }

  function aplicarSessao(nova: Sessao | null) {
    sessaoAtual = nova;
    setSessao(nova);
    if (nova) setAvisoDeSessao(null);
  }

  /** Administrador escolheu (ou deixou de ver) um propagandista. As abas
   *  voltam ao estado inicial porque tudo que estava carregado era de outra
   *  pessoa. */
  function verComo(alvo: VerComo | null) {
    if (!sessao) return;
    const nova: Sessao = { ...sessao, verComo: alvo };
    gravarSessao(nova);
    configurarVerComo(alvo?.setor ?? null);
    sessaoAtual = nova;
    setSessao(nova);
    setAba("home");
    setVisitadas(new Set(["home"]));
  }

  if (!sessao) return <Login onEntrar={aplicarSessao} aviso={avisoDeSessao} />;

  function sair() {
    encerrarSessao(null);
  }

  if (administrador === null) return null;

  if (administrador && !sessao.verComo) {
    return (
      <SeletorDePropagandista email={sessao.email} onEscolher={verComo} onSair={sair} />
    );
  }

  // Na sessão de conferência as abas mostram o propagandista escolhido; o
  // e-mail continua sendo o de quem entrou, que é o que o servidor autentica.
  const setorExibido = sessao.verComo?.setor ?? sessao.setor;
  const nomeExibido = sessao.verComo ? sessao.verComo.nome : sessao.nome;

  return (
    // Três faixas: cabeçalho, conteúdo rolável e navegação. O `minmax(0,1fr)`
    // no meio é o que impede a faixa central de crescer além da tela e empurrar
    // a navegação para fora da área visível no celular.
    <div className="grid h-dvh grid-rows-[auto_minmax(0,1fr)_auto]">
      <div className="min-w-0">
        <Header onAbrirMenu={() => setMenuAberto(true)} />
        {sessao.verComo && (
          // Faixa fixa da sessão de conferência: quem está vendo precisa saber
          // o tempo todo que não é o próprio painel e que nada aqui grava.
          <div className="flex items-center justify-between gap-3 bg-[#5D4A95] px-4 py-2 text-xs text-white sm:px-6">
            <span className="flex min-w-0 items-center gap-2">
              <Eye className="size-4 shrink-0" aria-hidden="true" />
              <span className="truncate">
                Vendo como <strong>{sessao.verComo.nome ?? "propagandista"}</strong>, setor{" "}
                {sessao.verComo.setor}. Somente leitura.
              </span>
            </span>
            <button
              type="button"
              onClick={() => verComo(null)}
              className="shrink-0 rounded-full border border-white/40 px-3 py-1 font-semibold hover:bg-white/15"
            >
              Trocar
            </button>
          </div>
        )}
      </div>

      <MenuLateral
        aberto={menuAberto}
        itens={ABAS}
        abaAtiva={aba}
        onSelecionar={(id) => {
          trocarAba(id as AbaId);
          setMenuAberto(false);
        }}
        onFechar={() => setMenuAberto(false)}
        onSair={() => {
          setMenuAberto(false);
          sair();
        }}
      />

      <main className="h-full min-h-0 overflow-hidden bg-[var(--color-muted)]">
        {visitadas.has("home") && (
          <Faixa ativa={aba === "home"}>
            {/* Home guiada do protótipo, decisão de George em 20/09/2026. O
                Chat com o motor continua em pages/Chat.tsx para voltar por
                botões separados. */}
            <PaginaHome email={sessao.email} nome={nomeExibido} />
          </Faixa>
        )}

        {visitadas.has("recomendacoes") && (
          <Faixa ativa={aba === "recomendacoes"}>
            <Recomendacoes
              email={sessao.email}
              setor={setorExibido}
              ativa={aba === "recomendacoes"}
            />
          </Faixa>
        )}

        {visitadas.has("ranking") && (
          <Faixa ativa={aba === "ranking"}>
            <Ranking
              email={sessao.email}
              setor={setorExibido}
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
        {ABAS.map(({ id, rotuloCurto, icone: Icone }) => {
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
              <span className="max-w-full truncate px-1">{rotuloCurto}</span>
            </button>
          );
        })}
      </nav>
    </div>
  );
}
