import { useEffect, useState } from "react";
import { CheckCircle, Star, X } from "lucide-react";
import {
  ApiError,
  listarDesconsideradas,
  listarEntrada,
  listarRevisao,
  obterPerfil,
  reverter,
  type DesconsideradaItem,
  type RecomendacaoItem,
} from "@/lib/api";
import { Alert } from "@/components/ui/alert";
import { rotuloMotivoDesconsideracao } from "@/lib/motivos";
import { GavetaDeAcao } from "@/components/GavetaDeAcao";

/**
 * Aba Recomendações do PedAI.
 *
 * Base trazida da branch `feature/aba-recomendacoes` do George (commit
 * `9c672f0`, 11/08/2026), que espelha o protótipo `RecommendationsScreen`
 * do Figma Make `cuZGbZpvR0aBJhixqBnYYB`: cabeçalho com aviso, filtros em
 * pílula, cards com faixa de cor por tipo e gaveta de detalhes.
 *
 * Ajustado em 14/08/2026 para o contrato atual do backend
 * (`renovai-local`), depois da comparação registrada em
 * docs/context/known-issues.md:
 *
 * 1. A lista mostra todas as pendências do ciclo, paginadas de 50 em 50, com
 *    o total no cabeçalho. As primeiras de cada tipo ganham selo de
 *    prioridade, quantas o backend disser em `destaques`.
 *
 *    **Esta linha era falsa até 04/09/2026.** O backend cortava em 5 e o resto
 *    não aparecia: medido no ciclo daquela data, a mediana era de 132
 *    pendências por pessoa e tipo, e o máximo 629, então mais de 96% ficavam
 *    invisíveis sem aviso. O corte vinha de um combinado antigo de 5 inclusões
 *    e 5 exclusões por semana, que virou limite de lista sem querer. George
 *    decidiu em 04/09/2026 mostrar todas e manter as 5 primeiras destacadas
 *    como prioridade da semana.
 *
 *    A ordenação é a do ranking do setor: entrada da melhor posição para a
 *    pior, exclusão da pior para a melhor.
 * 2. Botão "Desconsiderar recomendação" e a gaveta de confirmação foram
 *    adicionados nesta revisão — a versão do George não tinha, porque na
 *    época o endpoint respondia 501. Hoje `POST
 *    /recomendacoes/{id}/desconsiderar` já funciona de verdade, contrato
 *    novo (ID no path, motivo + bloqueio no corpo).
 * 3. Especialidade e cidade vêm da dimensão de médicos (LEFT JOIN com
 *    tb_dim_medicos, só existe no Databricks — ver known-issues.md), a
 *    mesma fonte do nome. Podem vir vazias para médicos fora da janela de
 *    08/06/2026 (fonte do espelho parada desde então) — não é erro da tela.
 * 4. Os textos de motivo e ação seguem os do chat, variando por caso, sem
 *    citar números de corte de painel (decisões de George em 09 a 11/08/2026).
 *
 * A aba Arquivadas (consulta + reversão de desconsideradas) fica fora deste
 * arquivo, adicionada numa revisão separada.
 */

/** Laranja da faixa de Exclusão no protótipo. Sem token no design system do
 *  portal, entra cru pelo mesmo motivo das cores do avatar da aba Usuário. */
const LARANJA_EXCLUSAO = "#F59E0B";

/** Fallback do destaque, se o backend não mandar `destaques`. O número real
 *  vem da resposta, para a regra viver num lugar só: até 04/09/2026 este 5
 *  cortava a lista inteira no backend, e hoje ele só marca quantas ficam em
 *  destaque como prioridade da semana. */
const QTD_PRIORIDADE = 5;

type TipoAba = "entrada" | "exclusao";

/** Aba selecionada na navegação principal — inclui "arquivadas", que não
 *  existe em TipoAba porque essa lista tem forma diferente das outras duas
 *  (DesconsideradaItem, não RecomendacaoItem) e não passa pelos mesmos
 *  componentes de card/gaveta. */
type Aba = TipoAba | "arquivadas";

/* Os textos abaixo seguem os do chat (`backend/app/chat/perfil_medico.py`),
 * decisão de George em 11/08/2026: mesma leitura nas duas abas, sem número de
 * corte de painel e sem afirmar causa que o dado não sustenta. O card fala do
 * médico sem repetir o nome, que já é o título; a gaveta de detalhes usa a
 * frase completa do chat, com o nome como sujeito. Visita sem registro é caso
 * diferente de visita antiga e tem frase própria, como no chat. */

// Sprint 6: corte fixo (400) virou limite por propagandista, janela de
// visita foi de 5 para 3 meses — os 3 valores abaixo são os confirmados
// por query real contra o Databricks (ver docs/context/decisions-log.md).
const MOTIVO_RANKING = "REVISAO_RANKING_SETOR_ACIMA_LIMITE";
const MOTIVO_VISITA = "REVISAO_SEM_VISITA_3_MESES";
const MOTIVO_AMBOS = "REVISAO_RANKING_SETOR_ACIMA_LIMITE_E_SEM_VISITA_3_MESES";

function fraseDaVisita(meses?: number | null): string {
  return meses ? `não recebe visita há ${meses} meses` : "não tem visita registrada";
}
function resumoDoCard(item: RecomendacaoItem, tipo: TipoAba): string {
  if (tipo === "entrada") {
    return "Médico com forte prescrição no setor e ainda fora do seu painel.";
  }
  switch (item.motivo_revisao) {
    case MOTIVO_RANKING:
      return "Caiu no ranking do setor e passou do limite do seu painel ideal.";
    case MOTIVO_VISITA:
      return `Está dentro do limite do seu painel ideal, mas ${fraseDaVisita(item.meses_sem_visita)}.`;
    case MOTIVO_AMBOS:
      return `Caiu no ranking do setor, passou do limite do seu painel ideal e ${fraseDaVisita(item.meses_sem_visita)}.`;
    default:
      return "Elegível para revisão neste ciclo.";
  }
}

function motivoDoDetalhe(item: RecomendacaoItem, tipo: TipoAba): string {
  const nome = capitalizarNome(item.nome_medico);
  if (tipo === "entrada") {
    return `${nome} deveria estar no seu painel por conta da pontuação e do ranking, que vêm do que prescreve da sua linha.`;
  }
  switch (item.motivo_revisao) {
    case MOTIVO_RANKING:
      return `${nome} caiu no ranking do seu setor e passou do limite do seu painel ideal.`;
    case MOTIVO_VISITA:
      return `${nome} está dentro do limite do seu painel ideal, mas ${fraseDaVisita(item.meses_sem_visita)}.`;
    case MOTIVO_AMBOS:
      return `${nome} caiu no ranking do seu setor, passou do limite do seu painel ideal e ainda ${fraseDaVisita(item.meses_sem_visita)}.`;
    default:
      return `${nome} está elegível para revisão neste ciclo.`;
  }
}

function acaoDoCard(tipo: TipoAba): string {
  return tipo === "entrada"
    ? "Avaliar a inclusão do médico no seu painel."
    : "Avaliar a permanência do médico no seu painel.";
}

function acaoDoDetalhe(item: RecomendacaoItem, tipo: TipoAba): string {
  if (tipo === "entrada") {
    return "Avaliar a inclusão do médico no seu painel no SalesFarma.";
  }
  // Em saída por visita a posição continua boa: a orientação é decidir entre
  // retirar ou retomar a visita, nunca elogiar para depois tirar (decisões de
  // George em 10/08/2026).
  if (item.motivo_revisao === MOTIVO_VISITA) {
    return "Avaliar a permanência do médico. Se decidir manter, o caminho é retomar a visita.";
  }
  return "Avaliar a retirada do médico do seu painel.";
}

/** A tabela guarda o nome em caixa alta; a tela mostra com inicial maiúscula,
 *  decisão de George em 10/08/2026. Conectivos ficam em minúscula. */
const CONECTIVOS = new Set(["de", "da", "do", "das", "dos", "e"]);

function capitalizarNome(nome: string): string {
  return nome
    .toLocaleLowerCase("pt-BR")
    .split(" ")
    .map((parte) =>
      CONECTIVOS.has(parte)
        ? parte
        : parte.charAt(0).toLocaleUpperCase("pt-BR") + parte.slice(1),
    )
    .join(" ");
}

/** Pontuação em valor bruto, sem arredondar nem reescalar, decisão de George
 *  em 10/08/2026. Só o formato de milhar e decimal é do pt-BR. */
function formatarPontos(valor?: number | null): string {
  if (valor === null || valor === undefined) return "—";
  return `${valor.toLocaleString("pt-BR", {
    maximumFractionDigits: 0,
  })} pts`;
}



function formatarData(iso: string): string {
  const data = new Date(iso);
  if (Number.isNaN(data.getTime())) return iso;
  return data.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

interface RecomendacoesProps {
  email: string;
  setor: string;
}

export function Recomendacoes({ email, setor }: RecomendacoesProps) {
  const [entrada, setEntrada] = useState<RecomendacaoItem[]>([]);
  const [exclusao, setExclusao] = useState<RecomendacaoItem[]>([]);
  // Quantas pendências existem no ciclo, contra quantas já foram carregadas.
  // A mediana é de 132 por pessoa e tipo, e o máximo medido é 629: sem
  // paginação a tela receberia tudo de uma vez.
  const [totalEntrada, setTotalEntrada] = useState(0);
  const [totalExclusao, setTotalExclusao] = useState(0);
  const [destaques, setDestaques] = useState(QTD_PRIORIDADE);
  const [carregandoMais, setCarregandoMais] = useState(false);
  // Quem é a pessoa e onde ela atua, para a linha do cabeçalho. Chega depois
  // e não segura a tela: até responder, o cabeçalho mostra só o setor, que já
  // vem da sessão.
  const [ondeAtua, setOndeAtua] = useState<string | null>(null);
  const [aba, setAba] = useState<Aba>("entrada");
  const [detalhe, setDetalhe] = useState<RecomendacaoItem | null>(null);
  const [desconsiderando, setDesconsiderando] = useState<RecomendacaoItem | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);

  const [desconsideradas, setDesconsideradas] = useState<DesconsideradaItem[]>([]);
  const [carregandoArquivadas, setCarregandoArquivadas] = useState(false);
  const [erroArquivadas, setErroArquivadas] = useState<string | null>(null);
  const [jaCarregouArquivadas, setJaCarregouArquivadas] = useState(false);
  const [revertendo, setRevertendo] = useState<Set<string>>(new Set());

  /** Busca as duas listas ativas de novo — reaproveitado no carregamento
   *  inicial e depois de um "Reverter" bem-sucedido (ver reverterItem).
   *  Preferido a uma atualização otimista do estado local: o novo status
   *  de uma reversão pode ser PENDENTE ou EXPIRADA (ver
   *  _ciclo_mais_recente() no backend), e recarregar reflete sempre o
   *  estado real do servidor sem duplicar essa regra de negócio aqui. */
  function recarregarListasAtivas() {
    return Promise.all([listarEntrada(email), listarRevisao(email)]).then(
      ([respEntrada, respRevisao]) => {
        setEntrada(respEntrada.recomendacoes);
        setExclusao(respRevisao.recomendacoes);
        setTotalEntrada(respEntrada.total);
        setTotalExclusao(respRevisao.total);
        // `??` e nao `||`: destaques igual a zero e resposta valida, quer
        // dizer nenhuma em destaque, e o `||` viraria cinco.
        setDestaques(respEntrada.destaques ?? QTD_PRIORIDADE);
      },
    );
  }

  /** Próxima página da aba ativa. O `offset` sai do que já está na tela, e
   *  não de um contador de página: assim uma recomendação resolvida entre
   *  duas cargas não faz a próxima pular um item. */
  function carregarMais() {
    const daEntrada = aba === "entrada";
    const buscar = daEntrada ? listarEntrada : listarRevisao;
    const jaCarregadas = daEntrada ? entrada.length : exclusao.length;
    setCarregandoMais(true);
    buscar(email, jaCarregadas)
      .then((resp) => {
        const guardar = daEntrada ? setEntrada : setExclusao;
        guardar((atuais) => [...atuais, ...resp.recomendacoes]);
        (daEntrada ? setTotalEntrada : setTotalExclusao)(resp.total);
      })
      .catch((excecao) =>
        setErro(
          excecao instanceof ApiError
            ? excecao.message
            : "Não foi possível carregar mais recomendações.",
        ),
      )
      .finally(() => setCarregandoMais(false));
  }

  useEffect(() => {
    let ativo = true;
    recarregarListasAtivas()
      .catch((excecao) => {
        if (!ativo) return;
        setErro(
          excecao instanceof ApiError
            ? excecao.message
            : "Não foi possível carregar as recomendações.",
        );
      })
      .finally(() => ativo && setCarregando(false));
    return () => {
      ativo = false;
    };
  }, [email]);

  // O nome e o lugar vêm do perfil, não da sessão: a sessão guarda o setor,
  // mas não cidade nem estado. Falha aqui não mostra nada e não atrapalha,
  // porque a linha do cabeçalho é contexto e não conteúdo.
  useEffect(() => {
    let ativo = true;
    obterPerfil(email)
      .then((p) => {
        if (!ativo) return;
        const cidade = p.cidades?.[0];
        const partes = [p.nome, cidade, p.uf].filter(Boolean);
        setOndeAtua(partes.length ? partes.join(", ") : null);
      })
      .catch(() => {
        /* silencioso: o cabeçalho fica só com o setor */
      });
    return () => {
      ativo = false;
    };
  }, [email]);

  // Carrega Arquivadas só na primeira vez que a aba é aberta — não faz
  // sentido pagar essa chamada extra em todo carregamento da tela para quem
  // nunca visita essa aba.
  useEffect(() => {
    if (aba !== "arquivadas" || jaCarregouArquivadas) return;
    let ativo = true;
    setCarregandoArquivadas(true);
    setErroArquivadas(null);
    listarDesconsideradas(email)
      .then((resp) => {
        if (!ativo) return;
        setDesconsideradas(resp.recomendacoes);
        setJaCarregouArquivadas(true);
      })
      .catch((excecao) => {
        if (!ativo) return;
        setErroArquivadas(
          excecao instanceof ApiError
            ? excecao.message
            : "Não foi possível carregar as recomendações arquivadas.",
        );
      })
      .finally(() => ativo && setCarregandoArquivadas(false));
    return () => {
      ativo = false;
    };
  }, [aba, email, jaCarregouArquivadas]);

  const lista = aba === "entrada" ? entrada : aba === "exclusao" ? exclusao : [];
  const totalDaAba = aba === "entrada" ? totalEntrada : aba === "exclusao" ? totalExclusao : 0;
  const totalPendente = totalEntrada + totalExclusao;
  // Evita depender de estreitamento de tipo de `aba` dentro de closures do
  // JSX (.map) — tipoAtual só é lido quando aba !== "arquivadas", garantido
  // pelo bloco condicional que envolve os cards de Entrada/Exclusão.
  const tipoAtual: TipoAba = aba === "exclusao" ? "exclusao" : "entrada";

  /** O id só existe numa das duas listas por vez — filtrar as duas é
   *  inofensivo e evita ter que saber de qual aba o item veio. */
  /** Tira a recomendação resolvida da lista e do contador.
   *
   *  O total precisa cair junto: ele passou a ser a contagem real do ciclo, e
   *  não o tamanho da lista, então sem isto o cabeçalho continuaria dizendo
   *  "132 pendentes" depois de resolver uma, até a próxima carga. Também é o
   *  que impede o botão "Carregar mais" de reaparecer sozinho quando a lista
   *  encolhe abaixo do total. Achado da revisão independente de 04/09/2026. */
  function removerDaLista(id: string) {
    // Decide fora do updater em qual lista o item está, e só então atualiza.
    //
    // A primeira versão disto chamava `setTotal...` de dentro do callback de
    // `setEntrada`, o que parece prático e está errado: o updater precisa ser
    // função pura, e o StrictMode do React o executa duas vezes em
    // desenvolvimento justamente para expor impureza. O contador seria
    // decrementado duas vezes numa remoção só. Achado da revisão independente
    // de 04/09/2026.
    const naEntrada = entrada.some((item) => item.id_recomendacao === id);
    const naExclusao = exclusao.some((item) => item.id_recomendacao === id);

    if (naEntrada) {
      setEntrada((atual) => atual.filter((item) => item.id_recomendacao !== id));
      setTotalEntrada((n) => Math.max(0, n - 1));
    }
    if (naExclusao) {
      setExclusao((atual) => atual.filter((item) => item.id_recomendacao !== id));
      setTotalExclusao((n) => Math.max(0, n - 1));
    }
  }

  function abrirDesconsiderar(item: RecomendacaoItem) {
    setDetalhe(null);
    setDesconsiderando(item);
  }

  /** Reversão é ação de menor risco que desconsiderar — não perde histórico
   *  (qtd_vezes_desconsiderado fica preservado no backend) e pode ser
   *  desconsiderada de novo se for engano. Por isso confirmação simples
   *  (window.confirm), sem a gaveta completa usada em (a). */
  function reverterItem(item: DesconsideradaItem) {
    const nome = item.nome_medico ? capitalizarNome(item.nome_medico) : "este médico";
    const confirmado = window.confirm(
      `Reverter a recomendação de ${nome}? Ela volta a aparecer como pendente em Entrada ou Exclusão.`,
    );
    if (!confirmado) return;

    setRevertendo((atual) => new Set(atual).add(item.id_recomendacao));
    reverter(item.id_recomendacao)
      .then(() => {
        setDesconsideradas((atual) =>
          atual.filter((i) => i.id_recomendacao !== item.id_recomendacao),
        );
        // O novo status (PENDENTE ou EXPIRADA) já foi decidido pelo
        // backend — recarregar as listas ativas é o que reflete esse
        // resultado na tela, sem o frontend precisar saber a regra.
        // Falha aqui não desfaz a reversão, que já aconteceu: só avisa
        // que a tela pode estar desatualizada.
        recarregarListasAtivas().catch(() => {
          window.alert(
            "A recomendação foi revertida, mas não foi possível atualizar as listas de Entrada/Exclusão. Recarregue a página para ver o resultado.",
          );
        });
      })
      .catch((excecao) => {
        window.alert(
          excecao instanceof ApiError
            ? excecao.message
            : "Não foi possível reverter esta recomendação. Tente novamente.",
        );
      })
      .finally(() => {
        setRevertendo((atual) => {
          const novo = new Set(atual);
          novo.delete(item.id_recomendacao);
          return novo;
        });
      });
  }

  if (carregando) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6">
        <p className="text-[var(--color-muted-foreground)]">
          Carregando recomendações…
        </p>
      </div>
    );
  }

  if (erro) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6">
        <Alert>{erro}</Alert>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-3xl">
      {/* Cabeçalho da tela */}
      <div className="border-b border-[var(--color-border)] bg-[var(--color-card)] px-4 pb-4 pt-5 sm:px-6">
        <p className="mb-1 text-xs text-[var(--color-muted-foreground)]">
          Recomendações
        </p>
        <p className="text-lg font-bold leading-tight text-[var(--color-foreground)]">
          Recomendações do seu setor
        </p>
        {/* A frase "as decisões tomadas aqui não alteram o SalesFarma" saiu em
            04/09/2026, por decisão de George: o destino é o aceite alimentar a
            carga, e o aviso passa a contradizer o produto. Quem diz que não é
            instantâneo é o texto do próprio aceite, "acontece na próxima
            carga". */}
        {/* Quem e onde, antes do código do setor. O protótipo mostra "Sugestões
            de D. Porto Alegre, RS"; aqui entra também o nome da pessoa e o
            setor, porque um propagandista pode atender mais de um e o código é
            o que ele usa para se orientar. Confirmado com George em
            04/09/2026. A base não tem nome legível para o setor, só o número. */}
        <p className="mt-1 text-xs leading-relaxed text-[var(--color-muted-foreground)]">
          {ondeAtua ? `Sugestões de ${ondeAtua} · ` : "Sugestões do "}
          Setor {setor}.
        </p>

        {/* Total pendente em destaque, no desenho do protótipo do Figma Make.
            Antes disso o número aparecia só como "5 pendentes" ao lado dos
            filtros, e com a lista cortada em 5 ele nem era o total real. */}
        {totalPendente > 0 && (
          <div
            className="mt-4 flex items-center gap-3 rounded-2xl px-4 py-3"
            style={{ background: "var(--color-accent)" }}
          >
            <span className="text-2xl font-bold leading-none text-[var(--color-primary)]">
              {totalPendente}
            </span>
            <p className="text-xs leading-snug text-[var(--color-primary)]">
              {totalPendente === 1
                ? "recomendação pendente aguardando sua avaliação"
                : "recomendações pendentes aguardando sua avaliação"}
            </p>
          </div>
        )}

        {/* Filtros + contagem */}
        <div className="mt-4 flex items-center justify-between gap-2">
          <div className="flex gap-1.5">
            {(
              [
                // Cada aba mostra o próprio número, decisão de George em
                // 04/09/2026: com a lista inteira à vista, saber quantas são
                // de entrada e quantas são de exclusão é o que orienta por
                // onde começar. O histórico não conta, porque é consulta e
                // não fila de trabalho.
                { id: "entrada", rotulo: "Entrada", contagem: totalEntrada },
                { id: "exclusao", rotulo: "Exclusão", contagem: totalExclusao },
                { id: "arquivadas", rotulo: "Histórico", contagem: null },
              ] as const
            ).map(({ id, rotulo, contagem }) => (
              <button
                key={id}
                type="button"
                onClick={() => setAba(id)}
                className="rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors"
                style={
                  aba === id
                    ? {
                        background: "var(--color-primary)",
                        color: "white",
                        borderColor: "var(--color-primary)",
                      }
                    : {
                        background: "var(--color-card)",
                        color: "var(--color-muted-foreground)",
                        borderColor: "var(--color-border)",
                      }
                }
              >
                {rotulo}
                {contagem !== null && contagem > 0 ? ` (${contagem})` : ""}
              </button>
            ))}
          </div>
          <span className="flex-shrink-0 text-xs text-[var(--color-muted-foreground)]">
            {aba === "arquivadas"
              ? `${desconsideradas.length} no histórico`
              : `${totalDaAba} pendente${totalDaAba !== 1 ? "s" : ""}`}
          </span>
        </div>
      </div>

      {/* Cards — Entrada/Exclusão */}
      {aba !== "arquivadas" && (
        <div className="space-y-3 px-4 py-4 sm:px-6">
          {lista.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <CheckCircle
                className="mb-3 h-12 w-12 text-[var(--color-primary)]"
                aria-hidden="true"
              />
              <p className="font-semibold text-[var(--color-foreground)]">
                Tudo em dia!
              </p>
              <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">
                Nenhuma recomendação pendente.
              </p>
            </div>
          ) : (
            <>
              {lista.map((item, indice) => (
                <CardRecomendacao
                  key={item.id_recomendacao}
                  item={item}
                  tipo={tipoAtual}
                  prioridade={indice < destaques}
                  onDetalhes={() => setDetalhe(item)}
                />
              ))}

              {lista.length < totalDaAba && (
                <button
                  type="button"
                  onClick={carregarMais}
                  disabled={carregandoMais}
                  className="w-full rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] py-3 text-sm font-semibold text-[var(--color-primary)] disabled:opacity-50"
                >
                  {carregandoMais
                    ? "Carregando..."
                    : `Carregar mais (${lista.length} de ${totalDaAba})`}
                </button>
              )}
            </>
          )}
        </div>
      )}

      {/* Cards — Arquivadas */}
      {aba === "arquivadas" && (
        <div className="space-y-3 px-4 py-4 sm:px-6">
          {carregandoArquivadas ? (
            <p className="px-1 text-sm text-[var(--color-muted-foreground)]">
              Carregando recomendações arquivadas…
            </p>
          ) : erroArquivadas ? (
            <Alert>{erroArquivadas}</Alert>
          ) : desconsideradas.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <CheckCircle
                className="mb-3 h-12 w-12 text-[var(--color-primary)]"
                aria-hidden="true"
              />
              <p className="font-semibold text-[var(--color-foreground)]">
                Nada por aqui
              </p>
              <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">
                Nenhuma recomendação desconsiderada.
              </p>
            </div>
          ) : (
            desconsideradas.map((item) => (
              <CardArquivada
                key={item.id_recomendacao}
                item={item}
                revertendo={revertendo.has(item.id_recomendacao)}
                onReverter={() => reverterItem(item)}
              />
            ))
          )}
        </div>
      )}

      {detalhe && (
        <GavetaDetalhes
          item={detalhe}
          tipo={tipoAtual}
          onFechar={() => setDetalhe(null)}
          onDesconsiderar={() => abrirDesconsiderar(detalhe)}
        />
      )}

      {desconsiderando && (
        <GavetaDeAcao
          nome={capitalizarNome(desconsiderando.nome_medico ?? desconsiderando.ufcrm)}
          idRecomendacao={desconsiderando.id_recomendacao}
          // O item da lista não carrega o tipo: ele vem da aba de onde a
          // gaveta foi aberta, que é sempre entrada ou exclusão.
          tipoRecomendacao={tipoAtual === "entrada" ? "ENTRADA_PAINEL" : "REVISAO_PAINEL"}
          // A frase já está em mãos aqui: a lista traz o item inteiro, então
          // não há detalhe a buscar, diferente do Ranking.
          frase={motivoDoDetalhe(desconsiderando, tipoAtual)}
          onFechar={() => setDesconsiderando(null)}
          // Só tira da lista. Fechar é do `onFechar`, acionado pelo botão da
          // etapa "Pronto": fechar aqui pularia a confirmação que a gaveta
          // mostra, e a aba Recomendações se comportaria diferente do Ranking,
          // que é justamente o que a gaveta compartilhada existe para evitar.
          // Achado da revisão independente de 04/09/2026.
          onResolvida={() => removerDaLista(desconsiderando.id_recomendacao)}
        />
      )}
    </div>
  );
}

interface CardRecomendacaoProps {
  item: RecomendacaoItem;
  tipo: TipoAba;
  prioridade: boolean;
  onDetalhes: () => void;
}

function CardRecomendacao({
  item,
  tipo,
  prioridade,
  onDetalhes,
}: CardRecomendacaoProps) {
  const cor = tipo === "entrada" ? "var(--color-primary)" : LARANJA_EXCLUSAO;
  return (
    <div
      className="overflow-hidden rounded-2xl bg-[var(--color-card)] shadow-sm"
      // As destacadas ganham a borda inteira na cor do tipo, além do selo;
      // as demais mantêm só a faixa esquerda do protótipo.
      style={{
        border: prioridade
          ? `1.5px solid ${cor}`
          : "1px solid var(--color-border)",
        borderLeft: `4px solid ${cor}`,
      }}
    >
      <div className="space-y-3 p-4">
        {prioridade && (
          <span
            className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-bold"
            style={{ background: "var(--color-accent)", color: cor }}
          >
            <Star className="h-3 w-3 fill-current" aria-hidden="true" />
            Prioridade do ciclo
          </span>
        )}

        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-sm font-semibold leading-snug text-[var(--color-foreground)]">
              {capitalizarNome(item.nome_medico)}
            </p>
            <p className="mt-0.5 text-xs text-[var(--color-muted-foreground)]">
              {item.ufcrm}
              {item.especialidade ? ` · ${capitalizarNome(item.especialidade)}` : ""}
            </p>
            {item.cidade && (
              <p className="text-xs text-[var(--color-muted-foreground)]">
                {capitalizarNome(item.cidade)}
                {item.uf ? `, ${item.uf}` : ""}
              </p>
            )}
          </div>
          <span
            className="flex-shrink-0 rounded-full px-2.5 py-1 text-xs font-bold text-white"
            style={{ background: cor }}
          >
            {tipo === "entrada" ? "Entrada" : "Exclusão"}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span
            className="rounded-full px-2.5 py-1 text-[11px] font-medium"
            style={{ background: "#EFF6FF", color: "#3B82F6" }}
          >
            Pendente
          </span>
          <span className="rounded-full bg-[var(--color-muted)] px-2.5 py-1 text-[11px] font-medium text-[var(--color-muted-foreground)]">
            Ciclo {item.ciclo_referencia}
          </span>
        </div>

        <div className="flex gap-3">
          <div className="flex-1 rounded-xl bg-[var(--color-muted)] px-3 py-2">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-[var(--color-muted-foreground)]">
              Ranking
            </p>
            <p className="mt-0.5 text-base font-bold text-[var(--color-foreground)]">
              {item.posicao_ranking ?? "—"}
            </p>
          </div>
          <div className="flex-1 rounded-xl bg-[var(--color-accent)] px-3 py-2">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-[#9B1B5A]">
              Pontuação
            </p>
            <p className="mt-0.5 text-sm font-bold text-[var(--color-primary)]">
              {formatarPontos(item.soma_pontuacao)}
            </p>
          </div>
        </div>

        <p className="text-xs leading-relaxed text-[var(--color-muted-foreground)]">
          {resumoDoCard(item, tipo)}
        </p>

        <p className="text-xs leading-relaxed text-[var(--color-foreground)]">
          <span className="font-semibold">Ação sugerida:</span>{" "}
          {acaoDoCard(tipo)}
        </p>

        <button
          type="button"
          onClick={onDetalhes}
          className="w-full rounded-xl border py-2.5 text-sm font-semibold transition-colors active:opacity-80"
          style={{
            borderColor: "var(--color-primary)",
            color: "var(--color-primary)",
            background: "var(--color-card)",
          }}
        >
          Ver detalhes
        </button>
      </div>
    </div>
  );
}

interface CardArquivadaProps {
  item: DesconsideradaItem;
  revertendo: boolean;
  onReverter: () => void;
}

/** Card da aba Arquivadas. Layout próprio, mais simples que
 *  CardRecomendacao — não tem faixa de prioridade nem os blocos de
 *  ranking/pontuação, que não fazem sentido para um item já desconsiderado;
 *  mostra em troca o motivo e a data da desconsideração. */
function CardArquivada({ item, revertendo, onReverter }: CardArquivadaProps) {
  const cor = item.tipo_recomendacao === "ENTRADA_PAINEL" ? "var(--color-primary)" : LARANJA_EXCLUSAO;
  const mostrarMesesSemVisita =
    item.tipo_recomendacao === "REVISAO_PAINEL" && item.meses_sem_visita != null;

  return (
    <div
      className="overflow-hidden rounded-2xl bg-[var(--color-card)] shadow-sm"
      style={{ border: "1px solid var(--color-border)", borderLeft: `4px solid ${cor}` }}
    >
      <div className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-sm font-semibold leading-snug text-[var(--color-foreground)]">
              {item.nome_medico ? capitalizarNome(item.nome_medico) : "Médico não identificado"}
            </p>
            <p className="mt-0.5 text-xs text-[var(--color-muted-foreground)]">
              {item.ufcrm}
              {item.especialidade ? ` · ${capitalizarNome(item.especialidade)}` : ""}
            </p>
            {item.cidade && (
              <p className="text-xs text-[var(--color-muted-foreground)]">
                {capitalizarNome(item.cidade)}
                {item.uf ? `, ${item.uf}` : ""}
              </p>
            )}
          </div>
          <span
            className="flex-shrink-0 rounded-full px-2.5 py-1 text-xs font-bold text-white"
            style={{ background: cor }}
          >
            {item.tipo_recomendacao === "ENTRADA_PAINEL" ? "Entrada" : "Exclusão"}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-[var(--color-muted)] px-2.5 py-1 text-[11px] font-medium text-[var(--color-muted-foreground)]">
            Ciclo {item.ciclo_recomendacao}
          </span>
          {/* A aba virou Histórico em 04/09/2026 e mostra as duas decisões, o
              que muda o rótulo: uma recomendação aceita não foi
              desconsiderada. A data vem de `data_decisao`, que o backend
              unifica, com recuo para a antiga quando o servidor for velho. */}
          <span className="rounded-full bg-[var(--color-muted)] px-2.5 py-1 text-[11px] font-medium text-[var(--color-muted-foreground)]">
            {item.status_recomendacao === "ACEITA" ? "Aceita em " : "Desconsiderada em "}
            {formatarData(item.data_decisao ?? item.data_desconsideracao ?? "")}
          </span>
          {item.bloquear_novas_recomendacoes && (
            <span className="rounded-full border border-[var(--color-destructive)]/30 bg-[var(--color-destructive)]/8 px-2.5 py-1 text-[11px] font-medium text-[var(--color-destructive)]">
              Não recomendar de novo
            </span>
          )}
        </div>

        {item.motivo_recomendacao && (
          <p className="text-xs leading-relaxed text-[var(--color-muted-foreground)]">
            <span className="font-semibold">Motivo original:</span> {item.motivo_recomendacao}
          </p>
        )}

        {mostrarMesesSemVisita && (
          <p className="text-xs leading-relaxed text-[var(--color-muted-foreground)]">
            {fraseDaVisita(item.meses_sem_visita)}
          </p>
        )}

        {item.status_recomendacao !== "ACEITA" && item.motivo_desconsideracao && (
          <p className="text-xs leading-relaxed text-[var(--color-foreground)]">
            <span className="font-semibold">Motivo da desconsideração:</span>{" "}
            {rotuloMotivoDesconsideracao(item.motivo_desconsideracao)}
          </p>
        )}

        {/* Reverter só existe para desconsiderada. O backend recusa reverter
            uma aceita, e desfazer o aceite tem regra própria: só vale enquanto
            a recomendação não entrou em CSV de exportação, que ainda não
            existe. Oferecer o botão aqui seria prometer uma ação que o
            servidor devolve com erro. */}
        {item.status_recomendacao !== "ACEITA" && (
          <button
            type="button"
            onClick={onReverter}
            disabled={revertendo}
            className="w-full rounded-xl border py-2.5 text-sm font-semibold transition-colors active:opacity-80 disabled:opacity-50"
            style={{
              borderColor: "var(--color-primary)",
              color: "var(--color-primary)",
              background: "var(--color-card)",
            }}
          >
            {revertendo ? "Revertendo…" : "Reverter"}
          </button>
        )}
      </div>
    </div>
  );
}

interface GavetaDetalhesProps {
  item: RecomendacaoItem;
  tipo: TipoAba;
  onFechar: () => void;
  onDesconsiderar: () => void;
}

function GavetaDetalhes({ item, tipo, onFechar, onDesconsiderar }: GavetaDetalhesProps) {
  const cor = tipo === "entrada" ? "var(--color-primary)" : LARANJA_EXCLUSAO;
  return (
    <div
      className="fixed inset-0 z-50 flex items-end"
      style={{ background: "rgba(0,0,0,0.45)" }}
      onClick={onFechar}
    >
      <div
        className="flex max-h-[92vh] w-full flex-col rounded-t-3xl bg-[var(--color-card)]"
        onClick={(evento) => evento.stopPropagation()}
      >
        <div className="flex-shrink-0 px-5 pb-3 pt-4">
          <div className="mx-auto mb-4 h-1 w-10 rounded-full bg-[var(--color-border)]" />
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-lg font-bold leading-tight text-[var(--color-foreground)]">
                {capitalizarNome(item.nome_medico)}
              </p>
              <p className="mt-0.5 text-xs text-[var(--color-muted-foreground)]">
                {item.ufcrm}
                {item.especialidade ? ` · ${capitalizarNome(item.especialidade)}` : ""}
              </p>
              <p className="text-xs text-[var(--color-muted-foreground)]">
                {item.cidade ? `${capitalizarNome(item.cidade)}${item.uf ? `, ${item.uf}` : ""} · ` : ""}
                Ciclo {item.ciclo_referencia}
              </p>
            </div>
            <button
              type="button"
              onClick={onFechar}
              aria-label="Fechar detalhes"
              className="mt-0.5 flex-shrink-0 p-1 text-[var(--color-muted-foreground)]"
            >
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
          </div>
          <div className="mt-3 flex gap-2">
            <span
              className="rounded-full px-2.5 py-1 text-xs font-bold text-white"
              style={{ background: cor }}
            >
              {tipo === "entrada" ? "Entrada" : "Exclusão"}
            </span>
            <span
              className="rounded-full px-3 py-1 text-xs font-medium"
              style={{ background: "#EFF6FF", color: "#3B82F6" }}
            >
              Pendente
            </span>
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-5 pb-2">
          <div className="flex gap-3">
            <div className="flex-1 rounded-xl bg-[var(--color-muted)] px-4 py-3">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-muted-foreground)]">
                Ranking no setor
              </p>
              <p className="mt-1 text-2xl font-bold text-[var(--color-foreground)]">
                {item.posicao_ranking ?? "—"}
              </p>
            </div>
            <div className="flex-1 rounded-xl bg-[var(--color-muted)] px-4 py-3">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-muted-foreground)]">
                Pontuação
              </p>
              <p className="mt-1 text-xl font-bold text-[var(--color-primary)]">
                {formatarPontos(item.soma_pontuacao)}
              </p>
            </div>
          </div>

          <div>
            <p className="mb-2 text-[11px] font-bold uppercase tracking-widest text-[var(--color-primary)]">
              Motivo da sugestão
            </p>
            <p className="text-sm leading-relaxed text-[var(--color-foreground)]">
              {motivoDoDetalhe(item, tipo)}
            </p>
            <div className="mt-3 border-t border-[var(--color-border)]" />
          </div>

          <div>
            <p className="mb-2 text-[11px] font-bold uppercase tracking-widest text-[var(--color-primary)]">
              Ação sugerida
            </p>
            <p className="text-sm leading-relaxed text-[var(--color-foreground)]">
              {acaoDoDetalhe(item, tipo)}
            </p>
            <div className="mt-3 border-t border-[var(--color-border)]" />
          </div>

          <div className="pb-2">
            <p className="mb-2 text-[11px] font-bold uppercase tracking-widest text-[var(--color-primary)]">
              Importante
            </p>
            <p className="text-sm leading-relaxed text-[var(--color-foreground)]">
              Esta é uma sugestão consultiva. A inclusão ou a permanência do
              médico continua sendo decidida e ajustada por você no SalesFarma.
              O portal não altera o seu painel automaticamente.
            </p>
          </div>
        </div>

        <div className="flex-shrink-0 space-y-2 border-t border-[var(--color-border)] px-5 py-4">
          <button
            type="button"
            onClick={onDesconsiderar}
            className="w-full rounded-2xl border-2 py-3 text-sm font-semibold transition-colors active:opacity-80"
            style={{
              borderColor: "var(--color-destructive)",
              color: "var(--color-destructive)",
              background: "var(--color-card)",
            }}
          >
            Desconsiderar recomendação
          </button>
          <button
            type="button"
            onClick={onFechar}
            className="w-full rounded-2xl bg-[var(--color-muted)] py-3 text-sm font-medium text-[var(--color-muted-foreground)]"
          >
            Fechar
          </button>
        </div>
      </div>
    </div>
  );
}
