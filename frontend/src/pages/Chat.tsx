import { useEffect, useRef, useState } from "react";
import { ChevronRight, Info, Send } from "lucide-react";
import {
  ApiError,
  type MemoriaDeVisitas,
  enriquecerPerfil,
  perguntarAoChat,
  type CardChat,
  type BlocoChat,
  type RespostaChat,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { CardMemoriaDeVisitas } from "@/components/CardMemoriaDeVisitas";

/**
 * Conversa do propagandista com o PedAI.
 *
 * O desenho vem do `ChatScreen` do protótipo do Figma Make
 * `cuZGbZpvR0aBJhixqBnYYB`, lido em 10/08/2026: avatar do assistente, bolha
 * branca com rabicho, bolha roxa do usuário à direita, cartão do médico com a
 * posição em pílula, insight em bloco rosa e sugestões em lista vertical.
 *
 * A resposta não é escrita por modelo de linguagem. Ela chega pronta do
 * `POST /chat/perfil-medico`, montada por código. Esta tela só desenha o que o
 * backend devolve: nenhuma frase de conteúdo é escrita aqui, e nada é
 * reordenado. Como mudar qualquer texto da resposta está em
 * `backend/app/chat/como-alterar-a-resposta-do-chat.md`.
 *
 * Quatro pontos em que a tela não segue o protótipo ao pé da letra, e os
 * quatro vêm de decisão posterior a ele:
 *
 * 1. A saudação tem três linhas em vez de duas. A do protótipo promete
 *    analisar médicos, entender perfis e explicar recomendações do setor, e o
 *    backend responde só a primeira. A segunda linha aqui diz o que esta
 *    conversa entrega hoje, e a terceira pede o médico, decisão de George em
 *    10/08/2026.
 * 2. Os chips de sugestão inicial não aparecem. Quatro dos cinco do protótipo
 *    levam ao painel de recomendações ou a intenções que o backend ainda não
 *    responde, e oferecer o que devolve vazio é pior do que não oferecer.
 * 3. O botão "Ver Detalhes" do cartão não existe aqui. No protótipo ele abre
 *    a gaveta do painel de recomendações; nesta jornada o detalhe do médico
 *    são os próprios chips, que já vêm com a resposta pronta.
 * 4. O microfone não foi trazido. O ditado por voz tem análise própria, de
 *    07/08/2026, e entra como frente separada.
 *
 * O avatar é o avião da marca, do arquivo oficial do logo. O protótipo trazia
 * um círculo roxo com as letras "AI".
 */

/** Cores do protótipo que ainda não existem no `theme.css` do portal. Ficam
 *  aqui, nomeadas, até o design system absorvê-las. */
const ROXO = "#4B3B8C";
const ROXO_CLARO = "#EDE8F5";
const VERDE_PONTUACAO = "#16A34A";
const ROSA_ESCURO = "#9B1B5A";
const FUNDO_CONVERSA = "#F7F7FA";

/** Saudação em três linhas: quem fala, o que oferece e o que fazer agora.
 *
 *  A segunda linha não lista as soluções do PED, que são três e deixariam a
 *  abertura enorme. Ela diz o que esta conversa entrega hoje, e cada item
 *  corresponde a um pedaço real da resposta: o que prescreve vem de
 *  `bloco_prescricao`, o que levar vem do produto em `bloco_acao`, e a forma
 *  de conduzir a conversa vem do dicionário `_CONVERSA`, que muda o conselho
 *  conforme o médico esteja em manutenção, reativação ou introdução.
 *
 *  Cada item diz de quem é a ação, senão os três se confundem: quem prescreve
 *  é o médico, quem oferece e quem conduz a conversa é o propagandista.
 *
 *  "O que está sendo prescrito", na voz passiva, e não "o que esse médico
 *  prescreve" nem "o que essa pessoa prescreve". A primeira forma é masculina e
 *  foi apontada na revisão independente de 10/08/2026; a segunda trocava um
 *  substantivo por outro. A passiva dispensa o sujeito, que é o que a decisão
 *  de 09/08/2026 pede.
 *
 *  Nenhum "ele" ou "ela": a regra de não flexionar gênero vale para o texto
 *  escrito à mão aqui igual vale para o que o backend escreve. A fonte de sexo
 *  cobre 39,6% dos médicos e traz o mesmo UFCRM como masculino e feminino ao
 *  mesmo tempo, medido em 09/08/2026. */
function abertura(nome: string | null) {
  const primeiro = nome?.trim().split(" ")[0];
  return (
    `Olá${primeiro ? `, ${primeiro}` : ""}. Sou o PedAI.\n` +
    "Posso te dar o retrato de um médico antes da visita: o que está sendo prescrito, o que você pode oferecer e como conduzir a conversa.\n" +
    "Me diga o nome ou o CRM de quem você vai visitar agora."
  );
}

/** Uma resposta inteira do PedAI é um item só, com um avatar só. No
 *  protótipo o avatar aparece uma vez por mensagem, e os cards ficam
 *  empilhados abaixo dele. */
type Item =
  | { tipo: "pergunta"; texto: string }
  | {
      tipo: "resposta";
      mensagem: string;
      cards: CardChat[];
      /** `prontas` nulo significa que o toque num chip monta pergunta nova. */
      prontas: Record<string, string> | null;
    }
  | {
      /** A Memória de Visitas, no lugar do antigo bloco "Como Tratar". */
      tipo: "memoria";
      memoria: MemoriaDeVisitas;
      perfilTexto: string;
    };

/** Intervalo entre um bloco e o seguinte.
 *
 *  Curto de propósito. Os cinco primeiros blocos já chegaram juntos, então a
 *  sequência é de leitura e não de espera: revelar em partes é legível e uma
 *  parede de texto não é. Pausa de segundos entre coisas prontas seria simular
 *  que o sistema pensa, roubando tempo de quem está na porta do consultório. */
const INTERVALO_ENTRE_BLOCOS = 320;

const espera = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Trecho em negrito no meio da linha. O agente escreve **assim**, e no teste
 *  de 30/08/2026 os asteriscos chegaram crus na tela. Só o negrito é tratado:
 *  é a única marcação em linha que o agente produz. */
function ComNegrito({ children }: { children: string }) {
  const partes = children.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {partes.map((parte, i) =>
        parte.startsWith("**") && parte.endsWith("**") ? (
          <strong key={i} className="font-semibold">
            {parte.slice(2, -2)}
          </strong>
        ) : (
          parte
        ),
      )}
    </>
  );
}

/** Uma linha de tabela em barras verticais: "| a | b |" vira ["a", "b"].
 *
 *  A barra escapada "\\|" é conteúdo da célula, não divisor de coluna. Sem o
 *  marcador temporário, "Plano A \\| Plano B" virava duas colunas e
 *  desalinhava a linha inteira. Achado da revisão independente de 31/08/2026. */
const BARRA_ESCAPADA = "\uE000";

function celulasDe(linha: string): string[] {
  return linha
    .trim()
    .replace(/\\\|/g, BARRA_ESCAPADA)
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.replaceAll(BARRA_ESCAPADA, "|").trim());
}

/** Linha separadora de cabeçalho: "|---|---|", com ou sem dois-pontos.
 *  Exige ao menos um traço: sem isso, "| |" e "| : |" passavam como
 *  separador. Achado da segunda rodada da revisão de 31/08/2026. */
const SEPARADOR_DE_TABELA = /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/;

/** Texto do backend vem com quebras de linha, itens iniciados por "- ",
 *  negrito entre asteriscos e tabela em barras verticais. Reconstruir isso
 *  como parágrafo, lista, negrito e tabela é só apresentação: nenhuma palavra
 *  é alterada aqui.
 *
 *  A tabela existe porque o agente responde lista de médicos nesse formato, e
 *  no teste de 30/08/2026 as barras chegaram cruas na tela. O parser é
 *  proposital e mínimo: linhas consecutivas começando com "|", com a segunda
 *  sendo o separador de traços do cabeçalho. Nada além disso é interpretado. */
function Texto({ children }: { children: string }) {
  const blocos: React.ReactNode[] = [];
  let lista: string[] = [];
  let tabela: string[] = [];

  const fecharLista = (chave: number) => {
    if (!lista.length) return;
    blocos.push(
      <ul key={`l${chave}`} className="mt-2 list-disc space-y-1 pl-5">
        {lista.map((item, i) => (
          <li key={i}>
            <ComNegrito>{item}</ComNegrito>
          </li>
        ))}
      </ul>,
    );
    lista = [];
  };

  const fecharTabela = (chave: number) => {
    if (!tabela.length) return;
    // Só é tabela o que tem cabeçalho e separador de traços na segunda linha.
    // Sem esta guarda, qualquer linha começando por barra virava uma tabela
    // de uma célula. Achado da revisão independente de 31/08/2026.
    if (tabela.length < 2 || !SEPARADOR_DE_TABELA.test(tabela[1])) {
      const soltas = tabela;
      tabela = [];
      soltas.forEach((linha, k) => {
        blocos.push(
          <p key={`t${chave}-p${k}`} className="mt-1.5 first:mt-0">
            <ComNegrito>{linha}</ComNegrito>
          </p>,
        );
      });
      return;
    }
    const [cabecalho, ...resto] = tabela;
    const corpo = resto.filter((l) => !SEPARADOR_DE_TABELA.test(l));
    blocos.push(
      <div key={`t${chave}`} className="mt-2 overflow-x-auto">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr>
              {celulasDe(cabecalho).map((c, i) => (
                <th
                  key={i}
                  className="border-b border-[var(--color-border)] px-2 py-1.5 text-left font-semibold"
                >
                  <ComNegrito>{c}</ComNegrito>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {corpo.map((linha, i) => (
              <tr key={i} className={i % 2 ? "bg-[var(--color-muted)]" : undefined}>
                {celulasDe(linha).map((c, j) => (
                  <td key={j} className="px-2 py-1.5 align-top">
                    <ComNegrito>{c}</ComNegrito>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>,
    );
    tabela = [];
  };

  children.split("\n").forEach((linha, i) => {
    if (linha.trim().startsWith("|")) {
      fecharLista(i);
      tabela.push(linha);
      return;
    }
    fecharTabela(i);
    if (linha.startsWith("- ")) {
      lista.push(linha.slice(2));
      return;
    }
    fecharLista(i);
    if (linha.trim()) {
      blocos.push(
        <p key={`p${i}`} className="mt-1.5 first:mt-0">
          <ComNegrito>{linha}</ComNegrito>
        </p>,
      );
    }
  });
  fecharTabela(-1);
  fecharLista(-1);

  return <>{blocos}</>;
}

/** O avião da marca do PED, extraído do arquivo oficial do logo em
 *  10/08/2026. O protótipo trazia um círculo roxo com as letras "AI"; o avião
 *  é o ícone real e foi o pedido de George. */
function Avatar() {
  return (
    <img
      src="/ped-aviao.png"
      alt=""
      width={32}
      height={32}
      className="h-8 w-8 flex-shrink-0 object-contain"
      aria-hidden="true"
    />
  );
}

/** Linha do assistente: avatar à esquerda e o conteúdo ao lado. */
function DoRenovai({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex gap-3">
      <Avatar />
      <div className="min-w-0 flex-1 space-y-2">{children}</div>
    </div>
  );
}

function CardMedico({ card, aoIrParaRecomendacoes }: {
  card: CardChat;
  aoIrParaRecomendacoes?: () => void;
}) {
  return (
    <div className="rounded-2xl border border-[var(--color-border)] bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-start justify-between gap-2">
        <p className="text-sm font-semibold">{card.name}</p>
        {card.rank && (
          <span
            className="flex-none rounded-full px-2 py-1 text-xs font-semibold"
            style={{ background: ROXO_CLARO, color: ROXO }}
          >
            {card.rank}
          </span>
        )}
      </div>

      <div className="mb-2 flex gap-6">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-[var(--color-muted-foreground)]">
            Pontos
          </p>
          {/* Valor bruto, decisão de George em 10/08/2026. */}
          <p className="text-sm font-bold" style={{ color: VERDE_PONTUACAO }}>
            {card.score == null
              ? "sem pontos"
              : card.score.toLocaleString("pt-BR", {
                  maximumFractionDigits: 0,
                })}
          </p>
        </div>
        {card.status && (
          <div>
            <p className="text-[10px] uppercase tracking-wide text-[var(--color-muted-foreground)]">
              Status
            </p>
            <p className="text-sm font-semibold text-[var(--color-primary)]">
              {card.status}
            </p>
          </div>
        )}
        {card.last_visit && (
          <div>
            <p className="text-[10px] uppercase tracking-wide text-[var(--color-muted-foreground)]">
              Última visita
            </p>
            <p className="text-sm font-semibold text-[var(--color-foreground)]">
              {card.last_visit}
            </p>
          </div>
        )}
      </div>

      {card.summary && (
        <p className="text-xs text-[var(--color-muted-foreground)]">{card.summary}</p>
      )}

      {/* Encaminha para a aba onde a recomendação é resolvida. Sem estado nem
          chamada aqui: o chat sabe falar do médico, não decidir por ele. */}
      {aoIrParaRecomendacoes && (
        <button
          type="button"
          onClick={aoIrParaRecomendacoes}
          className="mt-3 inline-flex items-center gap-1 rounded-full border px-3 py-1.5 text-xs font-semibold"
          style={{ borderColor: ROXO, color: ROXO, background: "white" }}
        >
          Ver em Recomendações
          <ChevronRight className="h-3 w-3" aria-hidden="true" />
        </button>
      )}
    </div>
  );
}

export function Chat({
  nome,
  perguntaPendente,
  aoConsumirPergunta,
  onIrParaRecomendacoes,
}: {
  nome?: string | null;
  /** Leva para a aba Recomendações.
   *
   *  O chat **não** resolve a recomendação: quem aceita ou desconsidera é a
   *  aba própria, que já tem a gaveta de três passos, o motivo e o bloqueio.
   *  Decisão de George em 04/09/2026, e é a decisão certa: replicar o fluxo
   *  aqui criaria uma segunda implementação da mesma regra, e a conversa não
   *  é lugar de formulário. O chat encaminha. */
  onIrParaRecomendacoes?: () => void;
  /** Pergunta enviada de outra aba, hoje pelo botão da gaveta do Ranking.
   *  Chega como texto, e não como identificador de médico, porque o chat já
   *  sabe interpretar pergunta em linguagem natural e a rota do agente recebe
   *  exatamente isso. */
  perguntaPendente?: string | null;
  /** Avisa quem enviou que a pergunta foi consumida, para ela não ser
   *  reenviada a cada volta para a aba. */
  aoConsumirPergunta?: () => void;
}) {
  const [itens, setItens] = useState<Item[]>([
    { tipo: "resposta", mensagem: abertura(nome ?? null), cards: [], prontas: null },
  ]);
  const [rascunho, setRascunho] = useState("");
  const [aguardando, setAguardando] = useState(false);
  const fim = useRef<HTMLDivElement>(null);
  // Uma conversa por montagem da tela. Sair do portal desmonta o chat (ver
  // `sair()` no App), então a próxima pessoa neste aparelho começa com outra
  // conversa e a memória do backend não vaza entre sessões.
  const idConversa = useRef<string>(
    globalThis.crypto?.randomUUID?.() ?? `conversa-${Date.now()}`,
  );
  // Cresce a cada envio. Compõe o identificador da interação no log do
  // agente; ver o comentário em perguntarAoChat.
  const turno = useRef(0);

  useEffect(() => {
    fim.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [itens, aguardando]);

  // Pergunta vinda de outra aba. Consome antes de enviar, para uma troca de
  // aba durante a espera não disparar a mesma pergunta de novo.
  useEffect(() => {
    if (!perguntaPendente || aguardando) return;
    aoConsumirPergunta?.();
    void perguntar(perguntaPendente);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [perguntaPendente]);

  function acrescentar(novos: Item[]) {
    setItens((atuais) => [...atuais, ...novos]);
  }

  function daResposta(resposta: RespostaChat): Item {
    return {
      tipo: "resposta",
      mensagem: resposta.mensagem,
      cards: resposta.cards,
      // Na desambiguação os chips são nomes de médico, e a resposta deles
      // ainda não foi buscada. Um `respostas` vazio também vira null: objeto
      // vazio é verdadeiro em JS, e o chip mostraria uma resposta em branco
      // em vez de enviar a pergunta.
      prontas:
        resposta.status === "MEDICO_AMBIGUO" ||
        !Object.keys(resposta.respostas ?? {}).length
          ? null
          : resposta.respostas,
    };
  }

  /** Revela os blocos um a um e, no fim, busca o perfil de comunicação.
   *
   *  Cada card acompanha o bloco de que ele fala, em vez de ficar tudo no fim.
   *  O card do médico é o visual do bloco de ranking, com nome, posição,
   *  pontuação e o status colorido, então nesse bloco o texto não é exibido:
   *  ele diria a mesma posição e a mesma pontuação que o card já mostra.
   *
   *  Os chips de continuação ficam no último bloco, porque só fazem sentido
   *  depois de a resposta inteira ter sido lida. */
  async function revelarEmBlocos(resposta: RespostaChat, blocos: BlocoChat[]) {
    const doTipo = (t: CardChat["type"]) => resposta.cards.filter((c) => c.type === t);
    const cardsDoBloco: Record<string, CardChat[]> = {
      decisao: doTipo("info-banner"),
      ranking: doTipo("doctor"),
      prescreve: doTipo("insight"),
    };

    const ordenados = [...blocos].sort((a, b) => a.ordem - b.ordem);
    for (let i = 0; i < ordenados.length; i += 1) {
      if (i > 0) await espera(INTERVALO_ENTRE_BLOCOS);
      const bloco = ordenados[i];
      const ultimo = i === ordenados.length - 1;
      const cards = [
        ...(cardsDoBloco[bloco.tipo] ?? []),
        ...(ultimo ? doTipo("suggestions") : []),
      ];
      acrescentar([
        {
          tipo: "resposta",
          mensagem: bloco.tipo === "ranking" && cards.some((c) => c.type === "doctor")
            ? ""
            : bloco.texto,
          cards,
          prontas: ultimo ? resposta.respostas : null,
        },
      ]);
    }
    // Sem await, de propósito: o enriquecimento agora inclui uma chamada de
    // modelo que pode levar dezenas de segundos, e aguardá-lo mantinha o
    // campo de digitação travado até o fim. A memória aparece quando chega.
    // Achado da revisão independente de 03/09/2026.
    void enriquecer(resposta);
  }

  /** O sexto bloco. Falha e indisponibilidade não viram erro na tela: o
   *  propagandista já tem os cinco primeiros, que são o essencial.
   *
   *  Com a Memória de Visitas disponível, ela ocupa o lugar do antigo texto
   *  de perfil, que vira rodapé dela. Backend antigo, sem o campo `visitas`,
   *  continua caindo no comportamento anterior. */
  async function enriquecer(resposta: RespostaChat) {
    const ufcrm = resposta.identificacao?.ufcrm;
    if (typeof ufcrm !== "string" || !ufcrm) return;
    // O enriquecimento roda em segundo plano e o campo já foi liberado. Se o
    // propagandista mandou outra pergunta nesse meio tempo, o resultado chega
    // atrasado e apareceria abaixo da conversa de OUTRO médico. O turno
    // capturado no início denuncia: mudou, descarta. Achado da revisão
    // independente de 03/09/2026.
    const turnoDeOrigem = turno.current;
    try {
      const extra = await enriquecerPerfil(ufcrm);
      if (turno.current !== turnoDeOrigem) return;
      if (extra.visitas?.disponivel) {
        acrescentar([
          {
            tipo: "memoria",
            memoria: extra.visitas,
            perfilTexto: extra.disponivel ? extra.texto.trim() : "",
          },
        ]);
        return;
      }
      if (!extra.disponivel || !extra.texto.trim()) return;
      acrescentar([
        { tipo: "resposta", mensagem: extra.texto, cards: [], prontas: null },
      ]);
    } catch {
      // silêncio proposital: sem o perfil a resposta continua completa
    }
  }

  async function perguntar(pergunta: string) {
    const texto = pergunta.trim();
    if (!texto || aguardando) return;
    setRascunho("");
    acrescentar([{ tipo: "pergunta", texto }]);
    setAguardando(true);
    try {
      turno.current += 1;
      const resposta = await perguntarAoChat(texto, idConversa.current, turno.current);
      // Backend anterior a 20/08 não manda `blocos`. Sem esta guarda, a tela
      // ficaria vazia entre um deploy e outro.
      if (resposta.blocos?.length) {
        await revelarEmBlocos(resposta, resposta.blocos);
      } else {
        acrescentar([daResposta(resposta)]);
      }
    } catch (erro) {
      acrescentar([
        {
          tipo: "resposta",
          mensagem:
            erro instanceof ApiError
              ? erro.message
              : "Não consegui responder agora. Tente de novo em instantes.",
          cards: [],
          prontas: null,
        },
      ]);
    } finally {
      setAguardando(false);
    }
  }

  function tocarNoChip(rotulo: string, prontas: Record<string, string> | null) {
    if (prontas) {
      // A resposta já veio no mesmo payload: nenhuma requisição.
      acrescentar([
        { tipo: "pergunta", texto: rotulo },
        { tipo: "resposta", mensagem: prontas[rotulo] ?? "", cards: [], prontas: null },
      ]);
      return;
    }
    void perguntar(rotulo);
  }

  return (
    <div className="flex h-full w-full flex-col" style={{ background: FUNDO_CONVERSA }}>
      <div className="mx-auto w-full max-w-3xl flex-1 space-y-4 overflow-y-auto p-4">
        {itens.map((item, i) =>
          item.tipo === "pergunta" ? (
            <div key={i} className="flex justify-end">
              <div
                className="max-w-[75%] rounded-2xl rounded-br-sm px-4 py-2.5 text-sm text-white"
                style={{ background: ROXO }}
              >
                {item.texto}
              </div>
            </div>
          ) : item.tipo === "memoria" ? (
            <DoRenovai key={i}>
              <CardMemoriaDeVisitas
                memoria={item.memoria}
                perfilTexto={item.perfilTexto}
              />
            </DoRenovai>
          ) : (
            <DoRenovai key={i}>
              {item.mensagem && (
                <div className="rounded-2xl rounded-tl-sm border border-[var(--color-border)] bg-white px-4 py-3 text-sm shadow-sm">
                  <Texto>{item.mensagem}</Texto>
                </div>
              )}

              {item.cards.map((card, j) => {
                if (card.type === "doctor")
                  return (
                    <CardMedico
                      key={j}
                      card={card}
                      aoIrParaRecomendacoes={onIrParaRecomendacoes}
                    />
                  );

                if (card.type === "suggestions") {
                  return (
                    <div key={j}>
                      <p className="mb-1.5 px-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-muted-foreground)]">
                        Sugestões de continuação
                      </p>
                      <div className="flex flex-col gap-2">
                        {(card.items ?? []).map((rotulo) => (
                          <button
                            key={rotulo}
                            type="button"
                            onClick={() => tocarNoChip(rotulo, item.prontas)}
                            className="flex items-center justify-between rounded-xl border border-[var(--color-border)] bg-white px-3 py-2 text-left text-sm transition-colors active:bg-[var(--color-muted)]"
                          >
                            {rotulo}
                            <ChevronRight
                              className="h-4 w-4 flex-shrink-0 text-[var(--color-muted-foreground)]"
                              aria-hidden="true"
                            />
                          </button>
                        ))}
                      </div>
                    </div>
                  );
                }

                return (
                  <div
                    key={j}
                    className={cn(
                      "flex gap-2 rounded-2xl p-3 text-xs leading-relaxed",
                      card.type === "info-banner" &&
                        "bg-[var(--color-muted)] text-[var(--color-muted-foreground)]",
                    )}
                    style={
                      card.type === "insight"
                        ? { background: "var(--color-accent)", color: ROSA_ESCURO }
                        : undefined
                    }
                  >
                    <Info
                      className="mt-0.5 h-4 w-4 flex-shrink-0"
                      style={card.type === "insight" ? { color: "var(--color-primary)" } : undefined}
                      aria-hidden="true"
                    />
                    <span>{card.text}</span>
                  </div>
                );
              })}
            </DoRenovai>
          ),
        )}

        {aguardando && (
          <DoRenovai>
            <div className="w-fit rounded-2xl rounded-tl-sm border border-[var(--color-border)] bg-white px-4 py-3 shadow-sm">
              <div className="flex h-4 items-center gap-1" role="status" aria-label="Consultando">
                {[0, 1, 2].map((i) => (
                  <span
                    key={i}
                    className="h-1.5 w-1.5 animate-bounce rounded-full bg-[var(--color-primary)]"
                    style={{ animationDelay: `${i * 0.15}s` }}
                  />
                ))}
              </div>
            </div>
          </DoRenovai>
        )}
        <div ref={fim} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void perguntar(rascunho);
        }}
        className="w-full border-t border-[var(--color-border)] bg-white px-4 pb-5 pt-3"
      >
        <div className="mx-auto flex w-full max-w-3xl items-center gap-2 rounded-2xl bg-[var(--color-muted)] px-4 py-2.5">
          <input
            value={rascunho}
            onChange={(e) => setRascunho(e.target.value)}
            placeholder="Digite o nome do médico ou faça uma pergunta."
            aria-label="Pergunta"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-[var(--color-muted-foreground)]"
          />
          <button
            type="submit"
            disabled={!rascunho.trim() || aguardando}
            aria-label="Enviar"
            className="grid h-8 w-8 flex-shrink-0 place-items-center rounded-full bg-[var(--color-primary)] text-white disabled:opacity-40"
          >
            <Send className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      </form>
    </div>
  );
}
