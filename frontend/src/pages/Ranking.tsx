import { useEffect, useRef, useState } from "react";
import { Info, Search, TrendingUp, X } from "lucide-react";
import {
  ApiError,
  classificarMedico,
  CONDUTA_TAMANHO_MAXIMO,
  detalharMedico,
  enriquecerPerfil,
  listarRanking,
  PERFIS_SEGMENTACAO,
  registrarConduta,
  textoDoMercado,
  type MercadoDetalhe,
  type DetalheMedicoResponse,
  type MedicoRanking,
  type MemoriaDeVisitas,
  type PerfilSegmentacao,
} from "@/lib/api";
import { Alert } from "@/components/ui/alert";
import { CardMemoriaDeVisitas } from "@/components/CardMemoriaDeVisitas";
import { GavetaDeAcao } from "@/components/GavetaDeAcao";

/**
 * Aba Ranking do PedAI.
 *
 * Espelha o `RankingScreen` do Figma Make `cuZGbZpvR0aBJhixqBnYYB`, relido em
 * 11/08/2026: cartão de cabeçalho roxo com os números do setor, busca, lista
 * de médicos e gaveta de detalhes.
 *
 * Pontos em que o conteúdo não segue o protótipo ao pé da letra, todos por
 * decisão de George em 11/08/2026:
 *
 * 1. Sem medalhas nem cor especial para as três primeiras posições, e a
 *    pontuação é sempre rosa, sem a escala verde/roxo/cinza do protótipo.
 * 2. O selo "Fora" virou a informação completa: cada médico mostra
 *    "No painel" ou "Fora do painel".
 * 3. A lista é o ranking real do setor, paginada de 50 em 50, com busca por
 *    nome rodando no warehouse. O setor mediano tem cerca de mil médicos e o
 *    maior passa de doze mil, então a lista completa de uma vez não dá.
 * 4. A gaveta de detalhes ganhou o que o chat já tem mapeado: categorias mais
 *    prescritas com percentual, medicamentos mais prescritos, participação
 *    Aché e o produto da linha para a conversa com até duas opções a mais.
 * 5. O texto "Como o ranking é calculado" do protótipo saiu em 11/08/2026 por
 *    afirmar critérios não confirmados, e **voltou em 04/09/2026** por decisão
 *    de George, com o argumento de que o material foi apresentado ao negócio e
 *    aceito. Ver `SobreORanking` abaixo. O que a `SOMA_PONTUACAO` mede continua
 *    pendente de confirmação no cofre.
 */

/** Roxo do cartão de cabeçalho no protótipo, sem token no design system. */
const ROXO_HEADER = "#4B3B8C";
const ROXO_HEADER_CLARO = "#6B52C8";
const LARANJA_EXCLUSAO = "#F59E0B";

const MESES_LONGOS = [
  "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
  "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
];

/** Ciclo `202608` exibido como `Agosto 2026`. */
function formatarCiclo(ciclo: string): string {
  if (!/^\d{6}$/.test(ciclo)) return ciclo;
  const mes = Number(ciclo.slice(4)) - 1;
  return `${MESES_LONGOS[mes] ?? ciclo.slice(4)} ${ciclo.slice(0, 4)}`;
}

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

function formatarPontos(valor?: number | null): string {
  if (valor === null || valor === undefined) return "—";
  return `${valor.toLocaleString("pt-BR", {
    maximumFractionDigits: 0,
  })} pts`;
}

function formatarData(iso?: string | null): string {
  if (!iso) return "Sem visita registrada";
  const [ano, mes, dia] = iso.split("-");
  return `${dia}/${mes}/${ano}`;
}

/* Frases da recomendação, as mesmas do chat e da aba Recomendações. */
function fraseDaRecomendacao(d: DetalheMedicoResponse): string {
  const nome = capitalizarNome(d.nome_medico);
  const visita = d.meses_sem_visita
    ? `não recebe visita há ${d.meses_sem_visita} meses`
    : "não tem visita registrada";
  switch (d.recomendacao) {
    case "ADICIONAR":
      return `${nome} deveria estar no seu painel por conta da pontuação e do ranking, que vêm do que prescreve da sua linha.`;
    case "CONTINUAR":
      return `${nome} deve seguir no seu painel.`;
    case "REMOVER":
      switch (d.criterio_saida) {
        case "ranking e visita":
          return `${nome} caiu no ranking do seu setor, passou do limite do seu painel ideal e ainda ${visita}.`;
        case "saiu do corte":
          return `${nome} caiu no ranking do seu setor e passou do limite do seu painel ideal.`;
        case "sem visita registrada":
          return `${nome} está dentro do limite do seu painel ideal, mas não tem visita registrada.`;
        default:
          return `${nome} está dentro do limite do seu painel ideal, mas ${visita}.`;
      }
    default:
      return `${nome} não tem ação recomendada neste ciclo.`;
  }
}

const ROTULO_RECOMENDACAO: Record<string, { texto: string; cor: string }> = {
  ADICIONAR: { texto: "Entrada no painel", cor: "var(--color-primary)" },
  REMOVER: { texto: "Saída do painel", cor: LARANJA_EXCLUSAO },
  CONTINUAR: { texto: "Permanência", cor: ROXO_HEADER },
  SEM_ACAO: { texto: "Sem ação", cor: "#6B7280" },
};

function SeloPainel({ noPainel }: { noPainel: boolean }) {
  return (
    <span
      className="flex-shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold"
      style={
        noPainel
          ? { background: "var(--color-accent)", color: "var(--color-primary)" }
          : { background: "var(--color-muted)", color: "var(--color-muted-foreground)" }
      }
    >
      {noPainel ? "No painel" : "Fora do painel"}
    </span>
  );
}

/** Explicação do que é o ranking e de como ele é calculado.
 *
 *  Texto literal do protótipo do Figma Make `cuZGbZpvR0aBJhixqBnYYB`, adotado
 *  por decisão de George em 04/09/2026. Ele já esteve na tela e saiu em
 *  11/08/2026 porque cinco dos critérios que cita não estão confirmados no
 *  cofre: demanda do mercado na região, dados de pesquisas, relevância
 *  estratégica dos produtos, categoria CAT 1/2/3 e pesos por região. George
 *  optou por publicar assim mesmo, com o argumento de que o material foi
 *  apresentado e aceito pelo negócio. **Não alterar o texto sem falar com ele**,
 *  e a origem dos critérios é pergunta para o negócio, não para o código.
 *
 *  Começa aberto e fecha por escolha da pessoa: o bloco é explicação, não
 *  aviso, e quem já entendeu não precisa vê-lo em toda visita à aba. A escolha
 *  não é persistida de propósito, para não guardar preferência de tela sem
 *  necessidade. */
function SobreORanking({ aoFechar }: { aoFechar: () => void }) {
  return (
    <div className="space-y-3 rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] p-4 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Info className="h-4 w-4 flex-shrink-0 text-[var(--color-primary)]" aria-hidden="true" />
          <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--color-primary)]">
            O que é o ranking?
          </p>
        </div>
        <button
          type="button"
          onClick={aoFechar}
          aria-label="Fechar a explicação do ranking"
          className="flex-shrink-0 rounded-full p-1 text-[var(--color-muted-foreground)]"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      <p className="text-xs leading-relaxed text-[var(--color-muted-foreground)]">
        O ranking ajuda a identificar médicos com maior potencial para cada
        setor, apoiando a{" "}
        <span className="font-semibold text-[var(--color-foreground)]">
          priorização das visitas
        </span>
        .
      </p>

      <p className="pt-1 text-[11px] font-bold uppercase tracking-widest text-[var(--color-primary)]">
        Como ele funciona
      </p>
      <p className="text-xs leading-relaxed text-[var(--color-muted-foreground)]">
        Para definir a posição, são combinadas diferentes informações, como o{" "}
        <span className="font-semibold text-[var(--color-foreground)]">
          histórico de prescrições
        </span>{" "}
        do médico, a{" "}
        <span className="font-semibold text-[var(--color-foreground)]">
          demanda do mercado na região
        </span>{" "}
        e{" "}
        <span className="font-semibold text-[var(--color-foreground)]">
          dados de pesquisas
        </span>
        .
      </p>
      <p className="text-xs leading-relaxed text-[var(--color-muted-foreground)]">
        A pontuação também considera a{" "}
        <span className="font-semibold text-[var(--color-foreground)]">
          relevância estratégica dos produtos
        </span>{" "}
        para cada linha e a categoria do médico (CAT 1, 2 ou 3). Esses
        indicadores podem ter pesos diferentes conforme o mercado e a região, e
        a combinação desses fatores gera uma pontuação, que determina a posição
        do médico no ranking.
      </p>

      <div className="mt-1 rounded-xl bg-[var(--color-muted)] p-3">
        <p className="text-xs leading-relaxed" style={{ color: ROXO_HEADER }}>
          O ranking funciona como um{" "}
          <span className="font-semibold">apoio à tomada de decisão</span>,
          indicando oportunidades com base nos dados e critérios disponíveis.
        </p>
      </div>
    </div>
  );
}

/** Rótulo da recomendação pendente na lista, no lugar do selo de painel.
 *
 *  Decisão de George em 04/09/2026: médico que deve permanecer não mostra
 *  nada. O selo só aparece quando existe recomendação pendente sobre a qual
 *  agir, e ele é o convite para a ação. Sem recomendação, volta o selo antigo
 *  de painel, que é informação e não ação. */
const SELO_DA_RECOMENDACAO: Record<string, { texto: string; fundo: string; cor: string }> = {
  ENTRADA_PAINEL: { texto: "Incluir no painel", fundo: "var(--color-accent)", cor: "var(--color-primary)" },
  REVISAO_PAINEL: { texto: "Rever no painel", fundo: "#FEF3C7", cor: "#92400E" },
};

/** Tipo que a tela não conhece ainda assim tem ação: o registro existe e pode
 *  ser aceito ou desconsiderado. Sem este padrão, um tipo novo vindo do backend
 *  quebrava a renderização da lista inteira antes de qualquer texto aparecer.
 *  Achado da revisão independente de 04/09/2026. */
const SELO_PADRAO = {
  texto: "Recomendação pendente",
  fundo: "var(--color-muted)",
  cor: "var(--color-muted-foreground)",
};

function seloDaRecomendacao(tipo: string) {
  return SELO_DA_RECOMENDACAO[tipo] ?? SELO_PADRAO;
}

/** O que a linha mostra quando a recomendação do ciclo já foi resolvida.
 *
 *  Sem isto, resolver a recomendação fazia a linha voltar ao selo de painel,
 *  como se nada tivesse acontecido, e o propagandista não via a própria
 *  decisão. `EXPIRADA` e `INELEGIVEL` ficam de fora de propósito: não são
 *  decisão dele, são estado do sistema, e para elas o selo de painel continua
 *  sendo a informação mais útil. */
const SELO_DO_ESTADO: Record<string, { texto: string; fundo: string; cor: string }> = {
  ACEITA: { texto: "Aceita", fundo: "var(--color-accent)", cor: "var(--color-primary)" },
  DESCONSIDERADA: { texto: "Desconsiderada", fundo: "var(--color-muted)", cor: "var(--color-muted-foreground)" },
  APLICADA: { texto: "Aplicada", fundo: "#DCFCE7", cor: "#166534" },
};

/** Invólucro da gaveta de ação para o Ranking.
 *
 *  A gaveta em si é compartilhada com a aba Recomendações
 *  (`components/GavetaDeAcao`), por decisão de George em 04/09/2026: as duas
 *  telas resolvem a mesma recomendação, e ter duas implementações significaria
 *  as duas divergirem no dia em que um texto mudasse.
 *
 *  O que é específico daqui é a frase: a lista do ranking não traz o motivo da
 *  recomendação, então este invólucro busca o detalhe do médico e usa
 *  `fraseDaRecomendacao`, a mesma do resto da tela. */
function GavetaDeAcaoDoRanking({
  medico,
  email,
  onFechar,
  onResolvida,
}: {
  medico: MedicoRanking;
  email: string;
  onFechar: () => void;
  onResolvida: (statusNovo: string | null) => void;
}) {
  const [frase, setFrase] = useState<string | null>(null);

  useEffect(() => {
    let ativo = true;
    detalharMedico(email, medico.ufcrm)
      .then((d) => ativo && setFrase(fraseDaRecomendacao(d)))
      .catch(() => ativo && setFrase(""));
    return () => {
      ativo = false;
    };
  }, [email, medico.ufcrm]);

  return (
    <GavetaDeAcao
      nome={capitalizarNome(medico.nome_medico)}
      idRecomendacao={medico.id_recomendacao_pendente!}
      tipoRecomendacao={medico.tipo_recomendacao_pendente}
      frase={frase}
      onFechar={onFechar}
      onResolvida={onResolvida}
    />
  );
}

interface RankingProps {
  email: string;
  setor: string;
  /** Leva o médico para o chat, na aba Home. */
  onConversar: (nomeMedico: string) => void;
}

export function Ranking({ email, setor, onConversar }: RankingProps) {
  const [medicos, setMedicos] = useState<MedicoRanking[]>([]);
  const [ciclo, setCiclo] = useState("");
  const [totalMedicos, setTotalMedicos] = useState(0);
  const [pontosLider, setPontosLider] = useState<number | null>(null);
  const [busca, setBusca] = useState("");
  const [carregando, setCarregando] = useState(true);
  const [carregandoMais, setCarregandoMais] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [ufcrmAberto, setUfcrmAberto] = useState<string | null>(null);
  const [sobreAberto, setSobreAberto] = useState(true);
  // Médico cuja recomendação pendente está sendo resolvida na gaveta de ação.
  // Separado de `ufcrmAberto`, que abre a gaveta de detalhes: tocar no selo
  // age sobre a recomendação, tocar no resto da linha abre o detalhe.
  const [acaoAberta, setAcaoAberta] = useState<MedicoRanking | null>(null);

  // A busca espera a pessoa parar de digitar para não disparar uma consulta
  // ao warehouse por tecla.
  const timerBusca = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // Uma resposta lenta de busca antiga não pode sobrescrever a atual: só a
  // requisição mais recente aplica o resultado.
  const idRequisicao = useRef(0);

  function carregar(q: string, offset: number, substituir: boolean) {
    const id = ++idRequisicao.current;
    (offset === 0 && !substituir ? setCarregando : setCarregandoMais)(true);
    listarRanking(email, q || undefined, offset)
      .then((resp) => {
        if (id !== idRequisicao.current) return;
        setCiclo(resp.ciclo);
        setTotalMedicos(resp.total_medicos);
        setPontosLider(resp.pontos_lider ?? null);
        setMedicos((atual) => (offset === 0 ? resp.medicos : [...atual, ...resp.medicos]));
        setErro(null);
      })
      .catch((excecao) => {
        if (id !== idRequisicao.current) return;
        setErro(
          excecao instanceof ApiError
            ? excecao.message
            : "Não foi possível carregar o ranking.",
        );
      })
      .finally(() => {
        if (id !== idRequisicao.current) return;
        setCarregando(false);
        setCarregandoMais(false);
      });
  }

  useEffect(() => {
    carregar("", 0, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [email]);

  function aoDigitarBusca(valor: string) {
    setBusca(valor);
    clearTimeout(timerBusca.current);
    timerBusca.current = setTimeout(() => carregar(valor.trim(), 0, true), 400);
  }

  if (carregando) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6">
        <p className="text-[var(--color-muted-foreground)]">Carregando ranking…</p>
      </div>
    );
  }

  if (erro && medicos.length === 0) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6">
        <Alert>{erro}</Alert>
      </div>
    );
  }

  const haMais = !busca && medicos.length < totalMedicos;

  return (
    <div className="mx-auto w-full max-w-3xl space-y-4 px-4 py-5 sm:px-6">
      {/* Cartão de cabeçalho */}
      <div
        className="rounded-2xl p-4 text-white"
        style={{ background: `linear-gradient(135deg, ${ROXO_HEADER} 0%, ${ROXO_HEADER_CLARO} 100%)` }}
      >
        <p className="mb-0.5 text-base font-bold">Ranking de médicos</p>
        <p className="mb-3 text-xs opacity-80">
          {formatarCiclo(ciclo)} · Setor S{setor}
        </p>
        <div className="flex gap-4">
          <div>
            <p className="text-[10px] uppercase tracking-wider opacity-70">Médicos</p>
            {/* Em rosa, como o limite do painel na aba Usuário: os dois falam
                do tamanho do painel e passam a ser lidos juntos. */}
            <p className="text-lg font-bold text-[var(--color-primary)]">
              {totalMedicos.toLocaleString("pt-BR")}
            </p>
          </div>
          <div className="w-px bg-white/20" />
          <div>
            <p className="text-[10px] uppercase tracking-wider opacity-70">Líder</p>
            <p className="text-sm font-bold leading-tight">{formatarPontos(pontosLider)}</p>
          </div>
        </div>
      </div>

      {sobreAberto && <SobreORanking aoFechar={() => setSobreAberto(false)} />}

      {/* Busca */}
      <div className="flex items-center gap-2 rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] px-4 py-2.5 shadow-sm">
        <Search className="h-4 w-4 flex-shrink-0 text-[var(--color-muted-foreground)]" aria-hidden="true" />
        <input
          value={busca}
          onChange={(evento) => aoDigitarBusca(evento.target.value)}
          placeholder="Buscar médico pelo nome…"
          className="flex-1 bg-transparent text-sm text-[var(--color-foreground)] outline-none placeholder:text-[var(--color-muted-foreground)]"
        />
        {busca && (
          <button
            type="button"
            onClick={() => aoDigitarBusca("")}
            aria-label="Limpar busca"
            className="text-[var(--color-muted-foreground)]"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        )}
      </div>

      {/* Lista */}
      <div className="space-y-2">
        {/* Duas ações na mesma linha, então dois elementos irmãos e não um
            dentro do outro: botão dentro de botão é HTML inválido e o leitor
            de tela não sabe qual anunciar. A linha abre o detalhe; o selo da
            recomendação resolve a recomendação. */}
        {medicos.map((medico) => (
          <div
            key={medico.ufcrm}
            className="flex w-full items-center gap-3 rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] px-4 py-3 shadow-sm"
          >
            <button
              type="button"
              onClick={() => setUfcrmAberto(medico.ufcrm)}
              className="flex min-w-0 flex-1 items-center gap-3 text-left transition-opacity active:opacity-75"
            >
              <span className="w-10 flex-shrink-0 text-center text-sm font-bold text-[var(--color-muted-foreground)]">
                {medico.posicao}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-[var(--color-foreground)]">
                  {capitalizarNome(medico.nome_medico)}
                </p>
                <p className="text-xs text-[var(--color-muted-foreground)]">
                  {medico.especialidade ? capitalizarNome(medico.especialidade) : medico.ufcrm}
                </p>
              </div>
            </button>

            <div className="flex flex-shrink-0 flex-col items-end gap-1">
              <p className="text-sm font-bold text-[var(--color-primary)]">
                {formatarPontos(medico.pontos)}
              </p>
              {/* Recomendação pendente vira ação; sem ela, volta o selo de
                  painel, que é informação. Médico que deve permanecer não
                  mostra nada de ação, decisão de George em 04/09/2026. */}
              {medico.id_recomendacao_pendente && medico.tipo_recomendacao_pendente ? (
                <button
                  type="button"
                  aria-label={`Resolver recomendação de ${capitalizarNome(medico.nome_medico)}`}
                  onClick={() => setAcaoAberta(medico)}
                  className="flex-shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold transition-opacity active:opacity-75"
                  style={{
                    background: seloDaRecomendacao(medico.tipo_recomendacao_pendente).fundo,
                    color: seloDaRecomendacao(medico.tipo_recomendacao_pendente).cor,
                  }}
                >
                  {seloDaRecomendacao(medico.tipo_recomendacao_pendente).texto}
                </button>
              ) : medico.status_recomendacao &&
                SELO_DO_ESTADO[medico.status_recomendacao] ? (
                <span
                  className="flex-shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold"
                  style={{
                    background: SELO_DO_ESTADO[medico.status_recomendacao].fundo,
                    color: SELO_DO_ESTADO[medico.status_recomendacao].cor,
                  }}
                >
                  {SELO_DO_ESTADO[medico.status_recomendacao].texto}
                </span>
              ) : (
                <SeloPainel noPainel={medico.no_painel} />
              )}
            </div>
          </div>
        ))}

        {medicos.length === 0 && (
          <div className="flex flex-col items-center space-y-2 py-12 text-[var(--color-muted-foreground)]">
            <TrendingUp className="h-8 w-8 opacity-30" aria-hidden="true" />
            <p className="text-sm">Nenhum médico encontrado</p>
          </div>
        )}

        {haMais && (
          <button
            type="button"
            onClick={() => carregar("", medicos.length, false)}
            disabled={carregandoMais}
            className="w-full rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] py-3 text-sm font-semibold text-[var(--color-primary)] disabled:opacity-50"
          >
            {carregandoMais
              ? "Carregando…"
              : `Carregar mais (${medicos.length.toLocaleString("pt-BR")} de ${totalMedicos.toLocaleString("pt-BR")})`}
          </button>
        )}
      </div>

      {acaoAberta && (
        <GavetaDeAcaoDoRanking
          key={acaoAberta.ufcrm}
          medico={acaoAberta}
          email={email}
          onFechar={() => setAcaoAberta(null)}
          // A recomendação deixou de estar pendente, então o selo de ação
          // some da linha sem precisar recarregar a lista inteira.
          onResolvida={(statusNovo) =>
            setMedicos((atuais) =>
              atuais.map((m) =>
                m.ufcrm === acaoAberta.ufcrm
                  ? {
                      ...m,
                      id_recomendacao_pendente: null,
                      tipo_recomendacao_pendente: null,
                      status_recomendacao: statusNovo,
                    }
                  : m,
              ),
            )
          }
        />
      )}

      {ufcrmAberto && (
        <GavetaMedico
          // Remonta a gaveta a cada médico: nenhum estado interno (detalhe,
          // memória, rascunho de conduta) atravessa de um médico para outro.
          key={ufcrmAberto}
          email={email}
          ufcrm={ufcrmAberto}
          onFechar={() => setUfcrmAberto(null)}
          onConversar={(nome) => {
            setUfcrmAberto(null);
            onConversar(nome);
          }}
        />
      )}
    </div>
  );
}

interface GavetaMedicoProps {
  email: string;
  ufcrm: string;
  onFechar: () => void;
  /** Leva a conversa para a aba Home com o médico já perguntado. */
  onConversar: (nomeMedico: string) => void;
}

/** 202607 vira 2026/07. A referência aparece na tela porque a auditoria fecha
 *  depois que o mês acaba e fica sempre um mês atrás do ciclo do painel: sem
 *  ela, o propagandista compara com o ciclo corrente e conclui que o número
 *  está errado. */
function formatarReferencia(ref: string): string {
  return /^\d{6}$/.test(ref) ? `${ref.slice(0, 4)}/${ref.slice(4)}` : ref;
}

/** Cor de cada perfil, em tom pastel.
 *
 *  Pastel e não saturado porque são quatro categorias lado a lado, sem ordem
 *  entre elas: cor forte sugeriria que uma é melhor que a outra. O tom de
 *  fundo separa os perfis, e o texto escuro da mesma família garante
 *  contraste legível.
 *
 *  RELACIONAL reaproveita o `accent` do tema, que já é o rosa pastel da
 *  marca. Os outros três são vizinhos dele em saturação. */
const COR_PERFIL: Record<string, { fundo: string; texto: string }> = {
  ANALITICO: { fundo: "#DBEAFE", texto: "#1E40AF" },
  PERFORMANCE: { fundo: "#FEF3C7", texto: "#92400E" },
  PESSOAL: { fundo: "#DCFCE7", texto: "#166534" },
  RELACIONAL: { fundo: "#FCE7F3", texto: "#9D174D" },
  "A DEFINIR": { fundo: "#F0F1F5", texto: "#6B7280" },
};

/** Rótulo de exibição dos perfis. O banco guarda sem acento, por causa da
 *  restrição CHECK; a tela mostra em português corrente. */
function rotularPerfil(perfil?: string | null): string {
  const mapa: Record<string, string> = {
    ANALITICO: "Analítico",
    PERFORMANCE: "Performance",
    PESSOAL: "Pessoal",
    RELACIONAL: "Relacional",
    "A DEFINIR": "A definir",
  };
  return perfil ? (mapa[perfil] ?? perfil) : "A definir";
}

function GavetaMedico({ email, ufcrm, onFechar, onConversar }: GavetaMedicoProps) {
  const [detalhe, setDetalhe] = useState<DetalheMedicoResponse | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  // A Memória de Visitas chega por outra rota e depois do detalhe, que é
  // instantâneo. Falha aqui não mostra nada: a gaveta continua inteira.
  const [memoria, setMemoria] = useState<MemoriaDeVisitas | null>(null);
  const [salvandoPerfil, setSalvandoPerfil] = useState(false);
  const [erroPerfil, setErroPerfil] = useState<string | null>(null);
  // Perfil escolhido e ainda não confirmado. Um clique sozinho não grava: a
  // gaveta abre com o dedo perto dos botões e trocar o perfil de um médico
  // por engano é silencioso, ninguém percebe depois.
  const [perfilPendente, setPerfilPendente] = useState<PerfilSegmentacao | null>(null);
  // Editor do Como Trata. Abre em tela cheia, e nao em caixa de rolagem dentro
  // da gaveta: a gaveta ja rola, e rolagem aninhada faz o dedo nao saber qual
  // das duas esta movendo.
  // Documento da KB do mercado. Um por vez: abrir outro fecha o anterior, para
  // a gaveta não virar uma pilha de textos abertos.
  const [kbAberto, setKbAberto] = useState<string | null>(null);
  const [kbDetalhe, setKbDetalhe] = useState<MercadoDetalhe | null>(null);
  const [kbCarregando, setKbCarregando] = useState(false);

  function abrirKb(mercado: string, codLinha: string) {
    if (kbAberto === mercado) {
      setKbAberto(null);
      return;
    }
    setKbAberto(mercado);
    setKbDetalhe(null);
    setKbCarregando(true);
    textoDoMercado(email, mercado, codLinha)
      .then(setKbDetalhe)
      .catch(() => setKbDetalhe(null))
      .finally(() => setKbCarregando(false));
  }

  const [editandoConduta, setEditandoConduta] = useState(false);
  const [rascunhoConduta, setRascunhoConduta] = useState("");
  const [salvandoConduta, setSalvandoConduta] = useState(false);
  const [erroConduta, setErroConduta] = useState<string | null>(null);

  function abrirConduta() {
    setRascunhoConduta(detalhe?.conduta_texto ?? "");
    setErroConduta(null);
    setEditandoConduta(true);
  }

  function salvarConduta() {
    const texto = rascunhoConduta.trim();
    if (!texto) return;
    setSalvandoConduta(true);
    setErroConduta(null);

    registrarConduta(email, ufcrm, texto)
      .then((atualizado) => {
        setDetalhe(atualizado);
        setEditandoConduta(false);
      })
      .catch(() =>
        setErroConduta("Não foi possível salvar. Tente novamente."),
      )
      .finally(() => setSalvandoConduta(false));
  }

  // A resposta traz o detalhe relido da view, então a tela reflete o que ficou
  // gravado e não o que foi enviado.
  function confirmarClassificacao() {
    if (!perfilPendente) return;
    setSalvandoPerfil(true);
    setErroPerfil(null);

    classificarMedico(email, ufcrm, perfilPendente)
      .then((atualizado) => {
        setDetalhe(atualizado);
        setPerfilPendente(null);
      })
      .catch(() =>
        setErroPerfil("Não foi possível salvar o perfil. Tente novamente."),
      )
      .finally(() => setSalvandoPerfil(false));
  }

  useEffect(() => {
    let ativo = true;
    // Se a mesma instância receber outro médico, a memória anterior não pode
    // continuar na tela enquanto a nova não chega, nem sobreviver a uma nova
    // chamada que falhe ou volte indisponível.
    setMemoria(null);
    detalharMedico(email, ufcrm)
      .then((resp) => ativo && setDetalhe(resp))
      .catch((excecao) => {
        if (!ativo) return;
        setErro(
          excecao instanceof ApiError
            ? excecao.message
            : "Não foi possível carregar os detalhes.",
        );
      });
    enriquecerPerfil(ufcrm)
      .then((extra) => {
        if (ativo && extra.visitas?.disponivel) setMemoria(extra.visitas);
      })
      .catch(() => {
        /* silencioso: a seção simplesmente não aparece */
      });
    return () => {
      ativo = false;
    };
  }, [email, ufcrm]);

  const pctLider =
    detalhe?.pontos && detalhe?.pontos_lider
      ? Math.min(100, Math.round((detalhe.pontos / detalhe.pontos_lider) * 100))
      : null;

  const rotulo = detalhe ? ROTULO_RECOMENDACAO[detalhe.recomendacao] : null;

  // Editor em tela cheia. Fica antes da gaveta e assume a tela inteira: com
  // ate 3000 caracteres, escrever dentro de uma folha que ja rola e ruim, e no
  // celular o teclado cobriria metade do campo.
  if (editandoConduta) {
    const restantes = CONDUTA_TAMANHO_MAXIMO - rascunhoConduta.length;
    return (
      <div className="fixed inset-0 z-50 flex flex-col bg-[var(--color-card)]">
        <div className="flex items-center justify-between gap-3 border-b border-[var(--color-border)] px-5 py-4">
          <div className="min-w-0">
            <p className="text-[11px] font-bold tracking-widest text-[var(--color-primary)] uppercase">
              Como trata
            </p>
            <p className="truncate text-sm font-semibold">{detalhe?.nome_medico}</p>
          </div>
          <button
            type="button"
            onClick={() => setEditandoConduta(false)}
            aria-label="Fechar"
            className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full text-[var(--color-muted-foreground)]"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        <textarea
          value={rascunhoConduta}
          onChange={(e) => setRascunhoConduta(e.target.value.slice(0, CONDUTA_TAMANHO_MAXIMO))}
          maxLength={CONDUTA_TAMANHO_MAXIMO}
          autoFocus
          placeholder="O que ele costuma prescrever, para que tipo de paciente, o que já disse sobre a conduta dele."
          aria-label="Como este médico trata"
          className="flex-1 resize-none px-5 py-4 text-sm leading-relaxed outline-none"
        />

        <div className="flex items-center justify-between gap-3 border-t border-[var(--color-border)] px-5 py-3">
          <span className="text-[11px] text-[var(--color-muted-foreground)]">
            {restantes} caracteres restantes
          </span>
          <div className="flex items-center gap-2">
            {erroConduta && (
              <span className="text-xs text-[var(--color-destructive)]">{erroConduta}</span>
            )}
            <button
              type="button"
              disabled={salvandoConduta || !rascunhoConduta.trim()}
              onClick={salvarConduta}
              className="rounded-[var(--radius-md)] bg-[var(--color-primary)] px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            >
              {salvandoConduta ? "Salvando..." : "Salvar"}
            </button>
          </div>
        </div>
      </div>
    );
  }

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
              {detalhe ? (
                <>
                  <p className="text-lg font-bold leading-tight text-[var(--color-foreground)]">
                    {capitalizarNome(detalhe.nome_medico)}
                  </p>
                  <p className="mt-0.5 text-xs text-[var(--color-muted-foreground)]">
                    {detalhe.ufcrm}
                    {detalhe.especialidade ? ` · ${capitalizarNome(detalhe.especialidade)}` : ""}
                  </p>
                  {detalhe.cidade && (
                    <p className="text-xs text-[var(--color-muted-foreground)]">
                      {capitalizarNome(detalhe.cidade)}
                      {detalhe.uf ? `, ${detalhe.uf}` : ""}
                    </p>
                  )}
                </>
              ) : (
                <p className="text-sm text-[var(--color-muted-foreground)]">
                  {erro ?? "Carregando…"}
                </p>
              )}
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
        </div>

        {detalhe && (
          <div className="flex-1 space-y-4 overflow-y-auto px-5 pb-6">
            {/* Posição e pontos */}
            <div className="flex gap-3">
              <div className="flex-1 rounded-2xl bg-[var(--color-muted)] px-4 py-3 text-center">
                <p className="text-2xl font-bold text-[var(--color-foreground)]">
                  #{detalhe.posicao ?? "—"}
                </p>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-muted-foreground)]">
                  Posição no ranking
                </p>
              </div>
              <div className="flex-1 rounded-2xl bg-[var(--color-accent)] px-4 py-3 text-center">
                <p className="text-base font-bold leading-tight text-[var(--color-primary)]">
                  {formatarPontos(detalhe.pontos)}
                </p>
                <p className="mt-1 text-[10px] font-semibold uppercase tracking-wider text-[#9B1B5A]">
                  Pontuação
                </p>
              </div>
            </div>

            {/* Comparação com o líder */}
            {pctLider !== null && (
              <div>
                <div className="mb-1.5 flex justify-between text-[11px] text-[var(--color-muted-foreground)]">
                  <span>Comparado ao líder do setor</span>
                  <span className="font-semibold">{pctLider}%</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--color-muted)]">
                  <div
                    className="h-full rounded-full bg-[var(--color-primary)]"
                    style={{ width: `${pctLider}%` }}
                  />
                </div>
              </div>
            )}

            {/* Dados do médico */}
            <div>
              <p className="mb-2 text-[11px] font-bold uppercase tracking-widest text-[var(--color-primary)]">
                Dados do médico
              </p>
              <div className="divide-y divide-[var(--color-border)] rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)]">
                {[
                  { rotulo: "Está no painel", valor: detalhe.no_painel ? "Sim" : "Não" },
                  { rotulo: "Última visita", valor: formatarData(detalhe.data_ultima_visita) },
                  {
                    rotulo: "Meses desde a última visita",
                    valor:
                      detalhe.meses_sem_visita !== null && detalhe.meses_sem_visita !== undefined
                        ? `${detalhe.meses_sem_visita} ${detalhe.meses_sem_visita === 1 ? "mês" : "meses"}`
                        : "—",
                  },
                  {
                    rotulo: "Ciclos no painel",
                    valor: detalhe.ciclos_no_painel_janela?.toString() ?? "—",
                  },
                ].map((linha) => (
                  <div key={linha.rotulo} className="flex items-center justify-between gap-3 px-4 py-3">
                    <p className="flex-1 text-xs text-[var(--color-muted-foreground)]">{linha.rotulo}</p>
                    <p className="flex-shrink-0 text-right text-xs font-semibold text-[var(--color-foreground)]">
                      {linha.valor}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            {/* Memória de visitas: o mesmo conteúdo do chat, resumido. O card
                traz o próprio título e o selo do momento da relação. */}
            {memoria && <CardMemoriaDeVisitas memoria={memoria} resumido />}

            {/* Como Trata --------------------------------------------------- */}
            <div>
              <p className="mb-2 text-[11px] font-bold tracking-widest text-[var(--color-primary)] uppercase">
                Como trata
              </p>
              <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] p-4">
                {detalhe.conduta_texto ? (
                  <>
                    {/* Quatro linhas na abertura. O texto inteiro fica atrás do
                        "ver tudo", em tela cheia. */}
                    <p className="line-clamp-4 text-sm leading-snug whitespace-pre-wrap text-[var(--color-foreground)]">
                      {detalhe.conduta_texto}
                    </p>
                    <div className="mt-2 flex items-center justify-between gap-3">
                      <button
                        type="button"
                        onClick={abrirConduta}
                        className="text-xs font-semibold text-[var(--color-primary)]"
                      >
                        Ver tudo e editar
                      </button>
                      {detalhe.conduta_em && (
                        <span className="text-[11px] text-[var(--color-muted-foreground)]">
                          {formatarData(detalhe.conduta_em)}
                          {detalhe.conduta_por ? ` · ${detalhe.conduta_por}` : ""}
                        </span>
                      )}
                    </div>
                  </>
                ) : (
                  <>
                    <p className="text-sm text-[var(--color-muted-foreground)]">
                      Você ainda não registrou como este médico vem tratando os
                      pacientes.
                    </p>
                    <button
                      type="button"
                      onClick={abrirConduta}
                      className="mt-3 rounded-[var(--radius-md)] bg-[var(--color-primary)] px-3 py-1.5 text-sm font-semibold text-white"
                    >
                      Registrar
                    </button>
                  </>
                )}
              </div>
            </div>

            {/* Perfil de comunicação ------------------------------------- */}
            <div>
              <p className="mb-2 text-[11px] font-bold tracking-widest text-[var(--color-primary)] uppercase">
                Perfil de comunicação
              </p>
              <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <span
                    className="rounded-full px-3 py-1 text-xs font-bold"
                    style={{
                      background: (COR_PERFIL[detalhe.perfil_comunicacao ?? "A DEFINIR"] ?? COR_PERFIL["A DEFINIR"]).fundo,
                      color: (COR_PERFIL[detalhe.perfil_comunicacao ?? "A DEFINIR"] ?? COR_PERFIL["A DEFINIR"]).texto,
                    }}
                  >
                    {rotularPerfil(detalhe.perfil_comunicacao)}
                  </span>
                  <p className="text-[11px] text-[var(--color-muted-foreground)]">
                    {detalhe.perfil_origem === "propagandista"
                      ? "definido por você"
                      : detalhe.perfil_origem === "salesfarma"
                        ? "sugerido pela base"
                        : "ainda sem definição"}
                  </p>
                </div>

                <p className="mb-3 text-xs text-[var(--color-foreground)]">
                  Este perfil combina com o médico que você visita? Se não
                  combinar, escolha outro abaixo.
                </p>

                <div className="flex flex-wrap gap-2">
                  {PERFIS_SEGMENTACAO.map((opcao) => {
                    const ativa = detalhe.perfil_comunicacao === opcao;
                    const escolhida = perfilPendente === opcao;
                    const cor = COR_PERFIL[opcao];
                    return (
                      <button
                        key={opcao}
                        type="button"
                        disabled={salvandoPerfil}
                        onClick={() => {
                          setErroPerfil(null);
                          setPerfilPendente(ativa ? null : opcao);
                        }}
                        aria-pressed={ativa}
                        className={
                          "rounded-full px-3 py-1.5 text-xs font-semibold transition-all disabled:opacity-50 " +
                          (ativa || escolhida
                            ? "ring-2 ring-offset-1"
                            : "opacity-70")
                        }
                        style={{
                          background: cor.fundo,
                          color: cor.texto,
                          // O anel usa a própria cor do perfil: com quatro
                          // pastéis lado a lado, um anel de cor única não
                          // diria qual deles está marcado.
                          ...(ativa || escolhida
                            ? ({ "--tw-ring-color": cor.texto } as React.CSSProperties)
                            : {}),
                        }}
                      >
                        {rotularPerfil(opcao)}
                      </button>
                    );
                  })}
                </div>

                {perfilPendente && (
                  <div className="mt-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-muted)] p-3">
                    <p className="text-xs text-[var(--color-foreground)]">
                      Alterar de{" "}
                      <strong>{rotularPerfil(detalhe.perfil_comunicacao)}</strong> para{" "}
                      <strong>{rotularPerfil(perfilPendente)}</strong>?
                    </p>
                    <div className="mt-2 flex gap-2">
                      <button
                        type="button"
                        disabled={salvandoPerfil}
                        onClick={confirmarClassificacao}
                        className="rounded-[var(--radius-md)] bg-[var(--color-primary)] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
                      >
                        {salvandoPerfil ? "Salvando..." : "Confirmar"}
                      </button>
                      <button
                        type="button"
                        disabled={salvandoPerfil}
                        onClick={() => setPerfilPendente(null)}
                        className="rounded-[var(--radius-md)] px-3 py-1.5 text-xs font-semibold text-[var(--color-muted-foreground)]"
                      >
                        Cancelar
                      </button>
                    </div>
                  </div>
                )}

                {erroPerfil && (
                  <p className="mt-2 text-xs text-[var(--color-destructive)]">{erroPerfil}</p>
                )}
              </div>
            </div>

            {/* Recomendação do sistema */}
            <div>
              <p className="mb-2 text-[11px] font-bold uppercase tracking-widest text-[var(--color-primary)]">
                Recomendação do sistema
              </p>
              <div className="space-y-2 rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] p-4">
                {rotulo && (
                  <span
                    className="inline-block rounded-full px-2.5 py-1 text-xs font-bold text-white"
                    style={{ background: rotulo.cor }}
                  >
                    {rotulo.texto}
                  </span>
                )}
                <p className="text-xs leading-relaxed text-[var(--color-muted-foreground)]">
                  {fraseDaRecomendacao(detalhe)}
                </p>
              </div>
            </div>

            {/* O que mais prescreveu no último ciclo -------------------------- */}
            <div>
              <div className="mb-2 flex items-baseline justify-between gap-3">
                <p className="text-[11px] font-bold tracking-widest text-[var(--color-primary)] uppercase">
                  O que mais prescreveu no último ciclo
                </p>
                {detalhe.mercados_referencia && (
                  <span className="text-[11px] text-[var(--color-muted-foreground)]">
                    {formatarReferencia(detalhe.mercados_referencia)}
                  </span>
                )}
              </div>

              <div className="divide-y divide-[var(--color-border)] rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)]">
                {(detalhe.mercados ?? []).length === 0 && (
                  <p className="px-4 py-3 text-xs text-[var(--color-muted-foreground)]">
                    Sem prescrição registrada na auditoria deste ciclo.
                  </p>
                )}

                {(detalhe.mercados ?? []).map((m, i) => (
                  <div key={m.mercado} className="px-4 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <p className="flex-1 text-sm font-semibold text-[var(--color-foreground)]">
                        {i + 1}. {capitalizarNome(m.mercado)}
                      </p>
                      <button
                        type="button"
                        onClick={() => abrirKb(m.mercado, m.cod_linha ?? "")}
                        className="flex-shrink-0 text-xs font-semibold text-[var(--color-primary)]"
                      >
                        Mais informação
                      </button>
                    </div>

                    {kbAberto === m.mercado && (
                      <div className="mt-3 space-y-3 rounded-xl bg-[var(--color-muted)] p-3">
                        {kbCarregando && (
                          <p className="text-xs text-[var(--color-muted-foreground)]">Carregando...</p>
                        )}

                        {!kbCarregando && !kbDetalhe && (
                          <p className="text-xs text-[var(--color-muted-foreground)]">
                            Sem material para este mercado.
                          </p>
                        )}

                        {!kbCarregando && kbDetalhe && (
                          <>
                            {kbDetalhe.indicacao && (
                              <div>
                                <p className="text-[10px] font-bold tracking-wider text-[var(--color-primary)] uppercase">
                                  Para que serve
                                </p>
                                <p className="mt-1 text-xs leading-relaxed text-[var(--color-foreground)]">
                                  {kbDetalhe.indicacao}
                                </p>
                              </div>
                            )}

                            {kbDetalhe.beneficios.length > 0 && (
                              <div>
                                <p className="text-[10px] font-bold tracking-wider text-[var(--color-muted-foreground)] uppercase">
                                  Argumentos
                                </p>
                                <ul className="mt-1 space-y-1">
                                  {kbDetalhe.beneficios.map((b) => (
                                    <li key={b} className="text-xs leading-relaxed text-[var(--color-foreground)]">
                                      · {b}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}

                            {!kbDetalhe.indicacao && kbDetalhe.beneficios.length === 0 && (
                              <p className="text-xs text-[var(--color-muted-foreground)]">
                                Sem material da Aché para este produto.
                              </p>
                            )}

                            {kbDetalhe.ciclos_origem.length > 0 && (
                              <p className="text-[10px] text-[var(--color-muted-foreground)]">
                                Material da Aché, ciclo{" "}
                                {kbDetalhe.ciclos_origem[0].toString().padStart(2, "0")}
                              </p>
                            )}
                          </>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Conduzir a conversa no chat ---------------------------------- */}
            <button
              type="button"
              onClick={() => onConversar(detalhe.nome_medico)}
              className="w-full rounded-2xl bg-[var(--color-primary)] px-4 py-3 text-sm font-semibold text-white"
            >
              Como conduzir a conversa
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
