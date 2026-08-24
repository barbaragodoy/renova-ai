import { useEffect, useState } from "react";
import { CheckCircle, Star, X } from "lucide-react";
import {
  ApiError,
  desconsiderar,
  listarDesconsideradas,
  listarEntrada,
  listarRevisao,
  MOTIVOS_DESCONSIDERACAO,
  reverter,
  type DesconsideradaItem,
  type DesconsiderarRequest,
  type MotivoDesconsideracao,
  type RecomendacaoItem,
} from "@/lib/api";
import { Alert } from "@/components/ui/alert";

/**
 * Aba Recomendações do Portal RenovAI.
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
 * 1. A lista mostra todas as pendências do ciclo, não seis exemplos. As cinco
 *    primeiras de cada tipo ganham selo de prioridade, porque a ordenação do
 *    backend já vem do ranking do setor (decisão de George em 10/08/2026).
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
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} pts`;
}

/** Rótulo em português de cada motivo fixo de desconsideração — espelha
 *  MOTIVOS_DESCONSIDERACAO em lib/api.ts / backend/app/schemas/recomendacoes.py. */
const ROTULO_MOTIVO: Record<MotivoDesconsideracao, string> = {
  MEDICO_NAO_ATUA_MAIS: "Médico não atua mais",
  MEDICO_APOSENTADO: "Médico aposentado",
  MEDICO_FALECIDO: "Médico falecido",
  SEM_INTERESSE_COMERCIAL: "Sem interesse comercial",
  OUTROS: "Outros",
};

/** O backend formata o motivo "OUTROS" como "OUTROS: <texto informado>"
 *  (ver _formatar_motivo_desconsideracao em routers/recomendacoes.py) — já
 *  vem legível, só tira o prefixo. Os demais motivos são os códigos fixos
 *  de MOTIVOS_DESCONSIDERACAO, traduzidos via ROTULO_MOTIVO. */
function rotuloMotivoDesconsideracao(bruto: string): string {
  if (bruto.startsWith("OUTROS:")) return bruto.replace(/^OUTROS:\s*/, "").trim();
  return ROTULO_MOTIVO[bruto as MotivoDesconsideracao] ?? bruto;
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
      },
    );
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
  // Evita depender de estreitamento de tipo de `aba` dentro de closures do
  // JSX (.map) — tipoAtual só é lido quando aba !== "arquivadas", garantido
  // pelo bloco condicional que envolve os cards de Entrada/Exclusão.
  const tipoAtual: TipoAba = aba === "exclusao" ? "exclusao" : "entrada";

  /** O id só existe numa das duas listas por vez — filtrar as duas é
   *  inofensivo e evita ter que saber de qual aba o item veio. */
  function removerDaLista(id: string) {
    setEntrada((atual) => atual.filter((item) => item.id_recomendacao !== id));
    setExclusao((atual) => atual.filter((item) => item.id_recomendacao !== id));
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
        <p className="mt-1 text-xs leading-relaxed text-[var(--color-muted-foreground)]">
          Sugestões do setor S{setor}. As decisões tomadas aqui não alteram o
          seu painel no SalesFarma automaticamente.
        </p>

        {/* Filtros + contagem */}
        <div className="mt-4 flex items-center justify-between gap-2">
          <div className="flex gap-1.5">
            {(
              [
                { id: "entrada", rotulo: "Entrada" },
                { id: "exclusao", rotulo: "Exclusão" },
                { id: "arquivadas", rotulo: "Arquivadas" },
              ] as const
            ).map(({ id, rotulo }) => (
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
              </button>
            ))}
          </div>
          <span className="flex-shrink-0 text-xs text-[var(--color-muted-foreground)]">
            {aba === "arquivadas"
              ? `${desconsideradas.length} arquivada${desconsideradas.length !== 1 ? "s" : ""}`
              : `${lista.length} pendente${lista.length !== 1 ? "s" : ""}`}
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
            lista.map((item, indice) => (
              <CardRecomendacao
                key={item.id_recomendacao}
                item={item}
                tipo={tipoAtual}
                prioridade={indice < QTD_PRIORIDADE}
                onDetalhes={() => setDetalhe(item)}
              />
            ))
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
        <GavetaDesconsiderar
          item={desconsiderando}
          onFechar={() => setDesconsiderando(null)}
          onSucesso={() => {
            removerDaLista(desconsiderando.id_recomendacao);
            setDesconsiderando(null);
          }}
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
      // As cinco primeiras de cada tipo ganham a borda inteira na cor do tipo,
      // além do selo; as demais mantêm só a faixa esquerda do protótipo.
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
          <span className="rounded-full bg-[var(--color-muted)] px-2.5 py-1 text-[11px] font-medium text-[var(--color-muted-foreground)]">
            Desconsiderada em {formatarData(item.data_desconsideracao)}
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

        <p className="text-xs leading-relaxed text-[var(--color-foreground)]">
          <span className="font-semibold">Motivo da desconsideração:</span>{" "}
          {rotuloMotivoDesconsideracao(item.motivo_desconsideracao)}
        </p>

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

interface GavetaDesconsiderarProps {
  item: RecomendacaoItem;
  onFechar: () => void;
  onSucesso: () => void;
}

/** Gaveta de confirmação de "Desconsiderar recomendação".
 *
 * Mesmo padrão visual de GavetaDetalhes (bottom sheet), reaproveitado por
 * consistência — não existe componente de modal/toggle compartilhado no
 * design system do portal hoje (ver components/ui/). O toggle de
 * "bloquear novas recomendações" é construído com as mesmas variáveis CSS
 * do tema, não um componente novo. */
function GavetaDesconsiderar({ item, onFechar, onSucesso }: GavetaDesconsiderarProps) {
  const [motivo, setMotivo] = useState<MotivoDesconsideracao | null>(null);
  const [motivoOutrosTexto, setMotivoOutrosTexto] = useState("");
  const [bloquear, setBloquear] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const podeConfirmar =
    motivo !== null && (motivo !== "OUTROS" || motivoOutrosTexto.trim().length > 0);

  function confirmar() {
    if (!motivo) return;
    setEnviando(true);
    setErro(null);

    const body: DesconsiderarRequest = {
      motivo,
      motivo_outros_texto: motivo === "OUTROS" ? motivoOutrosTexto.trim() : null,
      bloquear_novas_recomendacoes: bloquear,
    };

    desconsiderar(item.id_recomendacao, body)
      .then(() => onSucesso())
      .catch((excecao) => {
        setErro(
          excecao instanceof ApiError
            ? excecao.message
            : "Não foi possível desconsiderar esta recomendação. Tente novamente.",
        );
        setEnviando(false);
      });
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end"
      style={{ background: "rgba(0,0,0,0.45)" }}
      onClick={enviando ? undefined : onFechar}
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
                Desconsiderar recomendação
              </p>
              <p className="mt-0.5 text-xs text-[var(--color-muted-foreground)]">
                {capitalizarNome(item.nome_medico)} · {item.ufcrm}
              </p>
            </div>
            <button
              type="button"
              onClick={onFechar}
              disabled={enviando}
              aria-label="Fechar"
              className="mt-0.5 flex-shrink-0 p-1 text-[var(--color-muted-foreground)] disabled:opacity-50"
            >
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-5 pb-2">
          {erro && <Alert>{erro}</Alert>}

          <div>
            <p className="mb-2 text-[11px] font-bold uppercase tracking-widest text-[var(--color-primary)]">
              Motivo
            </p>
            <div className="flex flex-wrap gap-2">
              {MOTIVOS_DESCONSIDERACAO.map((codigo) => (
                <button
                  key={codigo}
                  type="button"
                  onClick={() => setMotivo(codigo)}
                  disabled={enviando}
                  className="rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors disabled:opacity-50"
                  style={
                    motivo === codigo
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
                  {ROTULO_MOTIVO[codigo]}
                </button>
              ))}
            </div>
          </div>

          {motivo === "OUTROS" && (
            <div>
              <p className="mb-2 text-[11px] font-bold uppercase tracking-widest text-[var(--color-primary)]">
                Descreva o motivo
              </p>
              <textarea
                value={motivoOutrosTexto}
                onChange={(evento) => setMotivoOutrosTexto(evento.target.value)}
                disabled={enviando}
                rows={3}
                maxLength={280}
                placeholder="Explique o motivo..."
                className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-input-background)] p-3 text-sm text-[var(--color-foreground)] outline-none transition-shadow focus-visible:border-transparent focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] disabled:opacity-60"
              />
            </div>
          )}

          <div>
            <button
              type="button"
              onClick={() => setBloquear((atual) => !atual)}
              disabled={enviando}
              aria-pressed={bloquear}
              className="flex w-full items-center justify-between rounded-xl bg-[var(--color-muted)] px-4 py-3 text-left disabled:opacity-50"
            >
              <span className="text-sm text-[var(--color-foreground)]">
                Não recomendar este médico novamente
              </span>
              <span
                className="flex h-6 w-11 flex-shrink-0 items-center rounded-full p-0.5 transition-colors"
                style={{ background: bloquear ? "var(--color-primary)" : "var(--color-border)" }}
              >
                <span
                  className="h-5 w-5 rounded-full bg-white shadow transition-transform"
                  style={{ transform: bloquear ? "translateX(20px)" : "translateX(0)" }}
                />
              </span>
            </button>
          </div>
        </div>

        <div className="flex-shrink-0 space-y-2 border-t border-[var(--color-border)] px-5 py-4">
          <button
            type="button"
            onClick={confirmar}
            disabled={!podeConfirmar || enviando}
            className="w-full rounded-2xl py-3 text-sm font-bold text-white transition-colors disabled:opacity-50"
            style={{ background: "var(--color-destructive)" }}
          >
            {enviando ? "Desconsiderando…" : "Confirmar"}
          </button>
          <button
            type="button"
            onClick={onFechar}
            disabled={enviando}
            className="w-full rounded-2xl bg-[var(--color-muted)] py-3 text-sm font-medium text-[var(--color-muted-foreground)] disabled:opacity-50"
          >
            Cancelar
          </button>
        </div>
      </div>
    </div>
  );
}
