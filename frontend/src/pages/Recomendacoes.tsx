import { useEffect, useState } from "react";
import { CheckCircle, Info, MapPin, X } from "lucide-react";
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
import { PontinhosDeCarregamento } from "@/components/ui/loading";
import { rotuloMotivoDesconsideracao } from "@/lib/motivos";
import { GavetaDeAcao } from "@/components/GavetaDeAcao";
import { GavetaMedico } from "@/pages/Ranking";
import type { BuscaDeMedico } from "@/pages/Home";

/**
 * Aba Recomendações do Ped.AI.
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
 *    o total no cabeçalho. Sem selo de prioridade desde 20/09/2026, decisão
 *    de George ao alinhar ao protótipo; o `destaques` do backend segue em uso
 *    só pela Home, para os cinco cards do chat.
 *
 *    **Esta linha era falsa até 04/09/2026.** O backend cortava em 5 e o resto
 *    não aparecia: medido no ciclo daquela data, a mediana era de 132
 *    pendências por pessoa e tipo, e o máximo 629, então mais de 96% ficavam
 *    invisíveis sem aviso. O corte vinha de um combinado antigo de 5 inclusões
 *    e 5 exclusões por semana, que virou limite de lista sem querer. George
 *    decidiu em 04/09/2026 mostrar todas.
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
const FUNDO_LISTA = "#F7F7FA";
const BORDA_FILTRO = "#E0E0E0";
const BORDA_BOTAO = "#D1D5DB";
const TEXTO_BOTAO = "#374151";
const TEXTO_BOTAO_SECUNDARIO = "#4A5565";
const TEXTO_AVISO = "#9B1B5A";
const VERDE_PONTUACAO = "#16A34A";
const AZUL_STATUS = "#3B82F6";
const ROXO_TEXTO = "#4B3B8C";
const ROXO_CLARO = "#EDE8F5";


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

export function motivoDoDetalhe(item: RecomendacaoItem, tipo: TipoAba): string {
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

/** A tabela guarda o nome em caixa alta; a tela mostra com inicial maiúscula,
 *  decisão de George em 10/08/2026. Conectivos ficam em minúscula. */
const CONECTIVOS = new Set(["de", "da", "do", "das", "dos", "e"]);

export function capitalizarNome(nome: string): string {
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
export function formatarPontos(valor?: number | null): string {
  if (valor === null || valor === undefined) return "—";
  return `${valor.toLocaleString("pt-BR", {
    maximumFractionDigits: 0,
  })} pts`;
}



/** Placeholder do CardRecomendacao enquanto a lista carrega, no formato do
 *  card real para a troca não "pular" o layout quando os dados chegam. */
function CardRecomendacaoEsqueleto() {
  return (
    <div
      className="rounded-[var(--radius-xl)] border border-[var(--color-border)] bg-[var(--color-card)] p-4 shadow-sm"
      aria-hidden="true"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1 space-y-2">
          <div className="h-3.5 w-2/3 rounded-sm skeleton-shimmer" />
          <div className="h-3 w-1/3 rounded-sm skeleton-shimmer" />
          <div className="h-3 w-1/4 rounded-sm skeleton-shimmer" />
        </div>
        <div className="h-6 w-10 flex-shrink-0 rounded-full skeleton-shimmer" />
      </div>

      <div className="mt-3 flex gap-4">
        <div className="h-9 w-28 rounded-sm skeleton-shimmer" />
        <div className="h-9 w-20 rounded-sm skeleton-shimmer" />
      </div>

      <div className="mt-3 flex gap-2">
        <div className="h-8.5 flex-1 rounded-lg skeleton-shimmer" />
        <div className="h-8.5 flex-1 rounded-lg skeleton-shimmer" />
      </div>
      <div className="mt-2 h-9 w-full rounded-lg skeleton-shimmer" />
    </div>
  );
}

/** Placeholder do CardArquivada, mesma lógica do esqueleto acima. */
function CardArquivadaEsqueleto() {
  return (
    <div
      className="overflow-hidden rounded-lg bg-[var(--color-card)] shadow-sm"
      style={{ border: "1px solid var(--color-border)", borderLeft: "4px solid var(--color-border)" }}
      aria-hidden="true"
    >
      <div className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1 space-y-2">
            <div className="h-3.5 w-1/2 rounded-sm skeleton-shimmer" />
            <div className="h-3 w-1/3 rounded-sm skeleton-shimmer" />
          </div>
          <div className="h-6 w-16 flex-shrink-0 rounded-lg skeleton-shimmer" />
        </div>

        <div className="flex flex-wrap gap-2">
          <div className="h-6 w-20 rounded-lg skeleton-shimmer" />
          <div className="h-6 w-28 rounded-lg skeleton-shimmer" />
        </div>

        <div className="h-3 w-4/5 rounded-sm skeleton-shimmer" />
      </div>
    </div>
  );
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
  /** Se a aba está em primeiro plano agora — App.tsx manda `aba ===
   *  "recomendacoes"`. A tela só é desmontada quando a pessoa sai do app
   *  (ver Faixa), então é isto, e não a montagem, que diz quando ela voltou
   *  a abrir a aba. */
  ativa: boolean;
  onMaisDetalhes?: (busca: BuscaDeMedico) => void;
}

export function Recomendacoes({ email, setor, ativa, onMaisDetalhes }: RecomendacoesProps) {
  const [entrada, setEntrada] = useState<RecomendacaoItem[]>([]);
  const [exclusao, setExclusao] = useState<RecomendacaoItem[]>([]);
  // Quantas pendências existem no ciclo, contra quantas já foram carregadas.
  // A mediana é de 132 por pessoa e tipo, e o máximo medido é 629: sem
  // paginação a tela receberia tudo de uma vez.
  const [totalEntrada, setTotalEntrada] = useState(0);
  const [totalExclusao, setTotalExclusao] = useState(0);
  const [carregandoMais, setCarregandoMais] = useState(false);
  // Quem é a pessoa e onde ela atua, para a linha do cabeçalho. Chega depois
  // e não segura a tela: até responder, o cabeçalho mostra só o setor, que já
  // vem da sessão.
  const [ondeAtua, setOndeAtua] = useState<string | null>(null);
  const [aba, setAba] = useState<Aba>("entrada");
  const [mostrarSobreATela, setMostrarSobreATela] = useState(false);
  const [detalhe, setDetalhe] = useState<RecomendacaoItem | null>(null);
  const [desconsiderando, setDesconsiderando] = useState<RecomendacaoItem | null>(null);
  // Em que passo a gaveta de ação abre: "escolha" (aceitar ou desconsiderar)
  // ou direto no "motivo". Os botões do card do médico pedem um ou outro.
  const [passoAcao, setPassoAcao] = useState<"confirmar" | "motivo">("confirmar");
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

  // A tela é montada uma vez só e fica em memória depois (ver Faixa em
  // App.tsx) — sem isto, o modal só apareceria na primeira visita da
  // sessão. `ativa` é o que diz que a pessoa voltou a abrir a aba, então é
  // nisso que o modal reabre, sem persistir a escolha em storage.
  useEffect(() => {
    if (ativa) setMostrarSobreATela(true);
  }, [ativa]);

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
        const partes = [cidade, p.uf].filter(Boolean);
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
    if (jaCarregouArquivadas) return;
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
  }, [email, jaCarregouArquivadas]);

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
    setJaCarregouArquivadas(false);
  }

  function abrirDesconsiderar(item: RecomendacaoItem, passo: "escolha" | "motivo" = "escolha") {
    setDetalhe(null);
    setPassoAcao(passo === "motivo" ? "motivo" : "confirmar");
    setDesconsiderando(item);
  }

  /** Reversão é ação de menor risco que desconsiderar — não perde histórico
   *  (qtd_vezes_desconsiderado fica preservado no backend) e pode ser
   *  desconsiderada de novo se for engano. Por isso confirmação simples
   *  (window.confirm), sem a gaveta completa usada em (a). */
  function reverterItem(item: DesconsideradaItem) {
    const nome = item.nome_medico ? capitalizarNome(item.nome_medico) : "este médico";
    const foiAceite = !item.data_desconsideracao;
    const confirmado = window.confirm(
      foiAceite
        ? `Desfazer o aceite de ${nome}? A recomendação volta a aparecer como pendente e não será enviada ao SalesFarma.`
        : `Reverter a recomendação de ${nome}? Ela volta a aparecer como pendente em Entrada ou Exclusão.`,
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
        // 409 é o aceite já enviado ao SalesFarma: a mensagem do servidor
        // traz a data, e a lista é recarregada para o botão sumir.
        window.alert(
          excecao instanceof ApiError
            ? excecao.message
            : "Não foi possível desfazer esta recomendação. Tente novamente.",
        );
        if (excecao instanceof ApiError && excecao.status === 409) {
          listarDesconsideradas(email)
            .then((resp) => setDesconsideradas(resp.recomendacoes))
            .catch(() => {});
        }
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
      <div className="min-h-full space-y-3 px-4 py-4" style={{ background: FUNDO_LISTA }}>
        <PontinhosDeCarregamento texto="Carregando recomendações" />
        {[0, 1, 2].map((i) => (
          <CardRecomendacaoEsqueleto key={i} />
        ))}
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
    <div className="mx-auto min-h-full w-full" style={{ background: FUNDO_LISTA }}>
      {mostrarSobreATela && (
        <SobreATelaDeRecomendacoes aoFechar={() => setMostrarSobreATela(false)} />
      )}

      <div className="border-b border-[var(--color-border)] bg-[var(--color-card)] px-4 pb-4 pt-5">
        <p className="mb-1 text-xs text-[var(--color-muted-foreground)]">
          Recomendações
        </p>
        <p className="text-lg font-bold leading-tight text-[var(--color-foreground)]">
          Recomendações do seu setor
        </p>
        <p className="mt-1.5 text-xs leading-relaxed text-[var(--color-muted-foreground)]">
          {ondeAtua ? `Sugestões de ${ondeAtua}.` : `Sugestões do Setor ${setor}.`} Suas decisões
          são integradas automaticamente ao Sales Pharma.
        </p>

        <div className="mt-4 flex flex-wrap gap-1.5">
          {(
            [
              { id: "entrada", rotulo: "Inclusão", contagem: null },
              { id: "exclusao", rotulo: "Exclusão", contagem: null },
              {
                id: "arquivadas",
                rotulo: "Histórico",
                contagem: desconsideradas.length > 0 ? desconsideradas.length : null,
              },
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
                      color: "var(--color-primary-foreground)",
                      borderColor: "var(--color-primary)",
                    }
                  : {
                      background: "var(--color-card)",
                      color: "var(--color-muted-foreground)",
                      borderColor: BORDA_FILTRO,
                    }
              }
            >
              {rotulo}
              {contagem !== null ? ` (${contagem})` : ""}
            </button>
          ))}
        </div>

        {totalPendente > 0 && (
          <div className="mt-3.5 flex items-center gap-2 rounded-lg bg-[var(--color-accent)] px-3 py-2">
            <span className="flex h-5 min-w-5 flex-shrink-0 items-center justify-center rounded-full bg-[var(--color-primary)] px-1 text-[11px] font-bold text-[var(--color-primary-foreground)]">
              {totalPendente}
            </span>
            <p className="text-xs font-semibold leading-5" style={{ color: TEXTO_AVISO }}>
              {totalPendente}{" "}
              {totalPendente === 1
                ? "recomendação pendente aguardando sua avaliação"
                : "recomendações pendentes aguardando sua avaliação"}
            </p>
          </div>
        )}
      </div>

      {/* Cards — Entrada/Exclusão */}
      {aba !== "arquivadas" && (
        <div className="space-y-3 px-4 py-4">
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
              {lista.map((item) => (
                <CardRecomendacao
                  key={item.id_recomendacao}
                  item={item}
                  tipo={tipoAtual}
                  onDetalhes={() => setDetalhe(item)}
                  onResolver={(passo) => abrirDesconsiderar(item, passo)}
                />
              ))}

              {lista.length < totalDaAba && (
                <button
                  type="button"
                  onClick={carregarMais}
                  disabled={carregandoMais}
                  className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] py-3 text-sm font-semibold text-[var(--color-primary)] disabled:opacity-50"
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
            <>
              <PontinhosDeCarregamento texto="Carregando recomendações arquivadas" />
              {[0, 1, 2].map((i) => (
                <CardArquivadaEsqueleto key={i} />
              ))}
            </>
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

      {/* "Ver detalhes" abre o card do médico, o mesmo do Ranking: faixa da
          recomendação, posição e pontos, líder, por que, endereços e dados.
          Alinhado ao protótipo em 20/09/2026. Os botões do rodapé abrem a
          gaveta de ação no passo pedido. */}
      {detalhe && (
        <GavetaMedico
          email={email}
          ufcrm={detalhe.ufcrm}
          medico={{
            id_recomendacao_pendente: detalhe.id_recomendacao,
            tipo_recomendacao_pendente: tipoAtual === "entrada" ? "ENTRADA_PAINEL" : "REVISAO_PAINEL",
          }}
          onFechar={() => setDetalhe(null)}
          onResolver={(passo) => abrirDesconsiderar(detalhe, passo)}
          onMaisDetalhes={
            onMaisDetalhes
              ? () => {
                  onMaisDetalhes({ nome: detalhe.nome_medico ?? detalhe.ufcrm, ufcrm: detalhe.ufcrm });
                  setDetalhe(null);
                }
              : undefined
          }
          variante="recomendacao"
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
          passoInicial={passoAcao}
          ufcrm={desconsiderando.ufcrm}
          especialidade={
            desconsiderando.especialidade ? capitalizarNome(desconsiderando.especialidade) : null
          }
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
  onDetalhes: () => void;
  onResolver: (passo: "escolha" | "motivo") => void;
}

function CardRecomendacao({ item, tipo, onDetalhes, onResolver }: CardRecomendacaoProps) {
  const cor = tipo === "entrada" ? "var(--color-primary)" : LARANJA_EXCLUSAO;
  return (
    <div className="rounded-[var(--radius-xl)] border border-[var(--color-border)] bg-[var(--color-card)] p-4 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <p className="text-sm font-semibold leading-snug text-[var(--color-foreground)]">
              {capitalizarNome(item.nome_medico)}
            </p>
            <span
              className="rounded-full px-2 py-0.5 text-[10px] font-bold text-white"
              style={{ background: cor }}
            >
              {tipo === "entrada" ? "Inclusão" : "Exclusão"}
            </span>
          </div>
          {item.especialidade && (
            <p className="mt-0.5 text-xs text-[var(--color-muted-foreground)]">
              {capitalizarNome(item.especialidade)}
            </p>
          )}
          {item.cidade && (
            <p className="mt-0.5 flex items-center gap-1 text-xs text-[var(--color-muted-foreground)]">
              <MapPin className="h-3 w-3 flex-shrink-0" aria-hidden="true" />
              {capitalizarNome(item.cidade)}
              {item.uf ? `, ${item.uf}` : ""}
            </p>
          )}
        </div>
        {item.posicao_ranking != null && (
          <span
            className="flex-shrink-0 rounded-full px-2 py-1 text-xs font-bold"
            style={{ background: ROXO_CLARO, color: ROXO_TEXTO }}
          >
            #{item.posicao_ranking}
          </span>
        )}
      </div>

      <div className="mt-3 flex gap-4">
        <div>
          <p className="text-[11px] font-medium uppercase text-[var(--color-muted-foreground)]">
            Pontuação
          </p>
          <p className="text-[15px] font-bold leading-tight" style={{ color: VERDE_PONTUACAO }}>
            {formatarPontos(item.soma_pontuacao)}
          </p>
        </div>
        <div>
          <p className="text-[11px] font-medium uppercase text-[var(--color-muted-foreground)]">
            Status
          </p>
          <p className="text-[15px] font-semibold leading-tight" style={{ color: AZUL_STATUS }}>
            Pendente
          </p>
        </div>
      </div>

      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={onDetalhes}
          className="h-8.5 flex-1 rounded-lg border bg-[var(--color-card)] text-xs font-semibold transition-colors active:opacity-80"
          style={{ borderColor: BORDA_BOTAO, color: TEXTO_BOTAO }}
        >
          Ver detalhes
        </button>
        <button
          type="button"
          onClick={() => onResolver("motivo")}
          className="h-8.5 flex-1 rounded-lg bg-[var(--color-secondary)] text-xs font-semibold transition-colors active:opacity-80"
          style={{ color: TEXTO_BOTAO_SECUNDARIO }}
        >
          Desconsiderar
        </button>
      </div>
      <button
        type="button"
        onClick={() => onResolver("escolha")}
        className="mt-2 h-9 w-full rounded-lg text-xs font-semibold text-white transition-colors active:opacity-80"
        style={{ background: cor }}
      >
        Aceitar recomendação
      </button>
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
/** O desfecho de uma decisão que já saiu do estado em que foi tomada. Fica
 *  fora do componente porque é vocabulário do backend, não texto de tela. */
const DESFECHO: Record<string, string> = {
  APLICADA: "Aplicada no painel",
  EXPIRADA: "Expirou sem aplicação",
};

function CardArquivada({ item, revertendo, onReverter }: CardArquivadaProps) {
  // Qual foi a decisão, e não em que estado ela está hoje. Aceite não tem data
  // de desconsideração, e essa é a única discriminação que sobrevive à
  // mudança de status depois da decisão.
  const foiAceite = !item.data_desconsideracao;

  const cor = item.tipo_recomendacao === "ENTRADA_PAINEL" ? "var(--color-primary)" : LARANJA_EXCLUSAO;
  const mostrarMesesSemVisita =
    item.tipo_recomendacao === "REVISAO_PAINEL" && item.meses_sem_visita != null;

  return (
    <div
      className="overflow-hidden rounded-lg bg-[var(--color-card)] shadow-sm"
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
            className="flex-shrink-0 rounded-lg px-2.5 py-1 text-xs font-bold text-white"
            style={{ background: cor }}
          >
            {item.tipo_recomendacao === "ENTRADA_PAINEL" ? "Entrada" : "Exclusão"}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-lg bg-[var(--color-muted)] px-2.5 py-1 text-[11px] font-medium text-[var(--color-muted-foreground)]">
            Ciclo {item.ciclo_recomendacao}
          </span>
          {/* A aba virou Histórico em 04/09/2026 e mostra as duas decisões, o
              que muda o rótulo: uma recomendação aceita não foi
              desconsiderada. A data vem de `data_decisao`, que o backend
              unifica, com recuo para a antiga quando o servidor for velho. */}
          <span className="rounded-lg bg-[var(--color-muted)] px-2.5 py-1 text-[11px] font-medium text-[var(--color-muted-foreground)]">
            {foiAceite ? "Aceita em " : "Desconsiderada em "}
            {formatarData(item.data_decisao ?? item.data_desconsideracao ?? "")}
          </span>
          {/* O que aconteceu depois da decisão. Um aceite pode ter virado
              aplicado, quando o job confirmou no painel, ou expirado, quando o
              ciclo virou sem aplicação. Sem isto a linha diria só "Aceita em"
              e esconderia o desfecho. */}
          {DESFECHO[item.status_recomendacao ?? ""] && (
            <span className="rounded-full bg-[var(--color-muted)] px-2.5 py-1 text-[11px] font-medium text-[var(--color-muted-foreground)]">
              {DESFECHO[item.status_recomendacao ?? ""]}
            </span>
          )}
          {/* Estado do aceite em relação ao SalesFarma, regra de 20/09/2026:
              enquanto não foi enviado, ainda pode ser desfeito; depois do
              envio, a data do envio é o aviso de que não volta mais. */}
          {foiAceite && item.status_recomendacao === "ACEITA" && (
            <span className="rounded-full bg-[var(--color-muted)] px-2.5 py-1 text-[11px] font-medium text-[var(--color-muted-foreground)]">
              {item.data_exportacao
                ? `Enviada ao SalesFarma em ${formatarData(item.data_exportacao)}`
                : "Aguardando envio ao SalesFarma"}
            </span>
          )}
          {item.bloquear_novas_recomendacoes && (
            <span className="rounded-lg border border-[var(--color-destructive)]/30 bg-[var(--color-destructive)]/8 px-2.5 py-1 text-[11px] font-medium text-[var(--color-destructive)]">
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

        {!foiAceite && item.motivo_desconsideracao && (
          <p className="text-xs leading-relaxed text-[var(--color-foreground)]">
            <span className="font-semibold">Motivo da desconsideração:</span>{" "}
            {rotuloMotivoDesconsideracao(item.motivo_desconsideracao)}
          </p>
        )}

        {/* O backend diz se dá para desfazer (`pode_desfazer`): desconsiderada
            sempre; aceita só enquanto não foi enviada ao SalesFarma. A tela
            não repete a regra. Servidor antigo, sem o campo, recua para o
            critério anterior, desconsiderada apenas. Decisão de George em
            20/09/2026, alinhando o Histórico ao protótipo. */}
        {(item.pode_desfazer ?? item.status_recomendacao === "DESCONSIDERADA") && (
          <button
            type="button"
            onClick={onReverter}
            disabled={revertendo}
            className="w-full rounded-lg border py-2.5 text-sm font-semibold transition-colors active:opacity-80 disabled:opacity-50"
            style={{
              borderColor: "var(--color-primary)",
              color: "var(--color-primary)",
              background: "var(--color-card)",
            }}
          >
            {revertendo ? "Desfazendo…" : "Desfazer e voltar para pendente"}
          </button>
        )}
      </div>
    </div>
  );
}

/** Explicação da tela, aberta de baixo para cima assim que a aba é
 *  visitada — mesmo gesto do SobreORanking (Ranking.tsx), mas em gaveta
 *  por já ser o padrão de modal desta tela (GavetaMedico/GavetaDeAcao).
 *  Fecha por escolha da pessoa, sem persistir em storage de propósito. */
function SobreATelaDeRecomendacoes({ aoFechar }: { aoFechar: () => void }) {
  return (
    <div
      // `bottom-14` para parar exatamente onde a navegação principal começa
      // (botões de `h-14` em App.tsx): no protótipo o fundo escurecido não
      // cobre a barra, ela continua visível e clicável embaixo do modal.
      className="fixed inset-x-0 top-0 bottom-14 z-50 flex flex-col items-center justify-end"
      style={{ background: "rgba(0,0,0,0.45)" }}
      onClick={aoFechar}
    >
      {/* Encostado nas bordas, sem respiro lateral — no protótipo o card fica
          rente à largura da tela, diferente da gaveta com `px-3` usada em
          GavetaDeAcao/GavetaMedico. */}
      <div
        className="flex max-h-[85vh] w-full flex-col rounded-t-3xl bg-[var(--color-card)]"
        onClick={(evento) => evento.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Sobre esta tela"
      >
        <div className="flex-shrink-0 px-5 pb-3 pt-4">
          <div className="mx-auto mb-4 h-1 w-10 rounded-full bg-[var(--color-border)]" />
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Info
                className="h-5 w-5 flex-shrink-0 text-[var(--color-primary)]"
                aria-hidden="true"
              />
              <p className="text-base font-bold text-[var(--color-foreground)]">
                Sobre esta tela
              </p>
            </div>
            <button
              type="button"
              onClick={aoFechar}
              aria-label="Fechar"
              className="flex-shrink-0 p-1 text-[var(--color-muted-foreground)]"
            >
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-5 pb-2">
          <p className="text-sm leading-relaxed text-[var(--color-muted-foreground)]">
            As recomendações são sugestões geradas pelo Ped.AI com base no perfil prescritivo
            dos médicos do seu setor.
          </p>

          <div className="space-y-3 rounded-[var(--radius-xl)] bg-[var(--color-muted)] p-4">
            <div>
              <p className="text-xs font-bold uppercase tracking-wide text-[var(--color-primary)]">
                Aceitar inclusão / Aceitar exclusão
              </p>
              <p className="mt-1 text-xs leading-relaxed text-[var(--color-muted-foreground)]">
                A decisão é registrada e enviada automaticamente ao Sales Pharma. Acompanhe o
                status na aba{" "}
                <span className="font-semibold text-[var(--color-foreground)]">Status</span>.
              </p>
            </div>
            <div className="border-t border-[var(--color-border)] pt-3">
              <p className="text-xs font-bold uppercase tracking-wide text-[var(--color-muted-foreground)]">
                Desconsiderar sugestão
              </p>
              <p className="mt-1 text-xs leading-relaxed text-[var(--color-muted-foreground)]">
                O médico{" "}
                <span className="font-semibold text-[var(--color-foreground)]">
                  não aparecerá mais para você neste ciclo
                </span>
                . Se o perfil dele continuar elegível, poderá reaparecer em ciclos futuros.
              </p>
            </div>
          </div>
        </div>

        <div className="flex-shrink-0 px-5 pb-5 pt-3">
          <button
            type="button"
            onClick={aoFechar}
            className="w-full rounded-[var(--radius-xl)] bg-[var(--color-primary)] py-3.5 text-sm font-semibold text-white"
          >
            Entendi
          </button>
        </div>
      </div>
    </div>
  );
}
