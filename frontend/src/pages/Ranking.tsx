import { useEffect, useRef, useState } from "react";
import { Info, MapPin, MessageSquare, Search, TrendingUp, X } from "lucide-react";
import {
  ApiError,
  detalharMedico,
  listarRanking,
  type DetalheMedicoResponse,
  type MedicoRanking,
  corrigirEndereco,
  type EnderecoAtendimento,
  type EnderecoCorrecao,
} from "@/lib/api";
import { Alert } from "@/components/ui/alert";
import { GavetaDeAcao } from "@/components/GavetaDeAcao";
import { PontinhosDeCarregamento } from "@/components/ui/loading";

/**
 * Aba Ranking do Ped.AI.
 *
 * Espelha o `RankingScreen` do Figma Make `cuZGbZpvR0aBJhixqBnYYB`, relido em
 * 11/08/2026: cartão de cabeçalho roxo com os números do setor, busca, lista
 * de médicos e gaveta de detalhes.
 *
 * Pontos em que o conteúdo não segue o protótipo ao pé da letra:
 *
 * 1. Pódio ouro, prata e bronze nos três primeiros e verde no top 10, como
 *    no protótipo, desde 18/09/2026, quando o portal foi alinhado a ele. A
 *    decisão de 11/08/2026 de não ter medalha foi revertida. Da 11ª à 50ª a
 *    pontuação é roxa e da 51ª em diante cinza escuro, copiado do protótipo
 *    por decisão de George na mesma data, enquanto a Ju não confirma outro
 *    critério.
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

/** Roxo do cartão de cabeçalho, o `#512D67` do protótipo, sem token no design
 *  system. O gradiente que existia aqui saiu em 18/09/2026: o protótipo usa a
 *  cor chapada e o contraste do cartão passou a seguir o desenho. */
const ROXO_HEADER = "#512D67";
/** Roxo dos textos de apoio, o `PURPLE` do protótipo. */
const ROXO_TEXTO = "#4B3B8C";

/** Pódio das três primeiras posições e verde do top 10, cores do protótipo. */
const OURO = "#FFB800";
const PRATA = "#9CA3AF";
const BRONZE = "#CD7F32";
const VERDE_TOP10 = "#16A34A";
/** Vermelho de alerta do protótipo, para "Sim" em sem visita e nunca visitado. */
const VERMELHO_ALERTA = "#DC2626";
/** Cinza escuro do protótipo, pontuação da 51ª posição em diante. */
const CINZA_ESCURO = "#374151";
const ROXO_CLARO = "#EDE8F5";
const VERDE_CLARO = "#F0FDF4";
const CINZA_BOTAO = "#364153";
const AMARELO_CLARO = "#FEF3C7";
const LARANJA_TEXTO = "#D97706";

function corDaMedalha(posicao?: number | null): string | null {
  if (posicao === 1) return OURO;
  if (posicao === 2) return PRATA;
  if (posicao === 3) return BRONZE;
  return null;
}

/** Cor da pontuação na lista, a escala do protótipo: verde até a 10ª, roxo
 *  até a 50ª, cinza escuro depois. George mandou copiar o protótipo em
 *  18/09/2026, enquanto a Ju não confirma outro critério. */
function corDaPontuacao(posicao?: number | null): string {
  if (posicao === null || posicao === undefined) return "var(--color-primary)";
  if (posicao <= 10) return VERDE_TOP10;
  if (posicao <= 50) return ROXO_TEXTO;
  return CINZA_ESCURO;
}

/** Os quatro textos de "Por que está nesta posição?" do protótipo, por faixa.
 *  O primeiro nome entra como lá. */
function textoDaPosicao(posicao?: number | null, nome?: string): string {
  const primeiro = capitalizarNome((nome ?? "").split(" ")[0] || "o médico");
  if (posicao === null || posicao === undefined) {
    return "Posição não disponível para este médico no ciclo atual.";
  }
  if (posicao <= 10) {
    return `Alta pontuação combinada de prescrição, demanda regional e relevância estratégica dos produtos coloca ${primeiro} entre os primeiros do setor.`;
  }
  if (posicao <= 100) {
    return `Bom histórico prescritivo e alinhamento com os critérios de mercado posicionam ${primeiro} entre os destaques do setor.`;
  }
  if (posicao <= 500) {
    return "Presença relevante no setor, com potencial de ascensão caso o volume prescritivo aumente nos próximos ciclos.";
  }
  return "Baixa pontuação combinada, principalmente prescrição abaixo da média do setor, resulta nessa posição no ranking.";
}

/** "Set 2026" a partir de "202609", recuo da coluna Atualizado do cabeçalho. */
function formatarCicloCurto(ciclo: string): string {
  const mes = Number(ciclo.slice(4, 6));
  const ano = ciclo.slice(0, 4);
  const nome = MESES_LONGOS[mes - 1];
  return nome ? `${nome.slice(0, 3)} ${ano}` : ciclo;
}
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

/** "2026-09-18 12:56:35" vira "18/09/2026". */
function formatarDataCurta(iso: string): string {
  const [ano, mes, dia] = iso.slice(0, 10).split("-");
  return dia && mes && ano ? `${dia}/${mes}/${ano}` : iso;
}

function formatarData(iso?: string | null): string {
  if (!iso) return "Sem visita registrada";
  const [ano, mes, dia] = iso.split("-");
  return `${dia}/${mes}/${ano}`;
}

/* Frases da recomendação, as mesmas do chat e da aba Recomendações. */
/** Texto do alerta de recomendação, por tipo e pelo motivo que o ranking
 *  registrou. Pedido de George em 20/09/2026: nada de frase genérica, o
 *  propagandista lê por que o sistema está dizendo aquilo. "Painel", nunca
 *  "ranking", no que é dele: o protótipo trocou por engano. */
function fraseDaRecomendacao(d: DetalheMedicoResponse): string {
  const posicao = d.posicao ? `na posição ${d.posicao} do ranking do setor` : "bem colocado no ranking do setor";
  const meses = d.meses_sem_visita;
  const semVisita =
    meses === null || meses === undefined
      ? "não tem visita registrada"
      : meses === 0
        ? "não recebe visita neste mês"
        : `não recebe visita há ${meses} ${meses === 1 ? "mês" : "meses"}`;
  const visitado =
    meses === null || meses === undefined
      ? "sem visita registrada"
      : meses === 0
        ? "foi visitado neste mês"
        : meses === 1
          ? "foi visitado há um mês"
          : `foi visitado há ${meses} meses`;
  switch (d.recomendacao) {
    case "ADICIONAR":
      return `Recomendamos incluir este médico no seu painel: está ${posicao}, dentro do limite do painel.`;
    case "CONTINUAR":
      return `Recomendamos que este médico permaneça no seu painel: está ${posicao} e ${visitado}.`;
    case "REMOVER":
      switch (d.criterio_saida) {
        case "ranking e visita":
          return `Recomendamos excluir este médico do seu painel: caiu para a posição ${d.posicao ?? "—"} do ranking, fora do limite do painel, e ${semVisita}.`;
        case "saiu do corte":
          return `Recomendamos excluir este médico do seu painel: caiu para a posição ${d.posicao ?? "—"} do ranking, fora do limite do painel.`;
        default:
          return `Recomendamos excluir este médico do seu painel: ${semVisita}.`;
      }
    default:
      return "Sem recomendação do sistema para este médico neste ciclo.";
  }
}

/** Cores do alerta, decisão de George em 20/09/2026: verde para incluir,
 *  rosa para excluir, amarelo para permanecer. Fundo pastel e texto escuro
 *  da mesma família, como o alerta do protótipo. */
const ESTILO_RECOMENDACAO: Record<string, { fundo: string; texto: string }> = {
  ADICIONAR: { fundo: "#DCFCE7", texto: "#166534" },
  REMOVER: { fundo: "#FCE7F3", texto: "#BE185D" },
  CONTINUAR: { fundo: "#FEF3C7", texto: "#92400E" },
};
const ESTILO_SEM_ACAO = { fundo: "#F3F4F6", texto: "#4B5563" };

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
function SobreORanking() {
  return (
    <div className="space-y-3 rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] p-4 shadow-sm">
      <div className="flex items-center gap-2">
        <Info className="h-4 w-4 flex-shrink-0 text-[var(--color-primary)]" aria-hidden="true" />
        <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--color-primary)]">
          O que é o ranking?
        </p>
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
        <p className="text-xs leading-relaxed" style={{ color: ROXO_TEXTO }}>
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
  passoInicial,
  onFechar,
  onResolvida,
}: {
  medico: MedicoRanking;
  email: string;
  passoInicial?: "escolha" | "motivo";
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
      passoInicial={passoInicial}
      onFechar={onFechar}
      onResolvida={onResolvida}
    />
  );
}

interface RankingProps {
  email: string;
  setor: string;
  /** Leva o médico para o chat, na aba Home. */
}

export function Ranking({ email, setor }: RankingProps) {
  const [medicos, setMedicos] = useState<MedicoRanking[]>([]);
  const [ciclo, setCiclo] = useState("");
  const [atualizadoEm, setAtualizadoEm] = useState<string | null>(null);
  const [totalMedicos, setTotalMedicos] = useState(0);
  const [pontosLider, setPontosLider] = useState<number | null>(null);
  const [busca, setBusca] = useState("");
  const [carregando, setCarregando] = useState(true);
  const [carregandoMais, setCarregandoMais] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [ufcrmAberto, setUfcrmAberto] = useState<string | null>(null);
  // Médico cuja recomendação pendente está sendo resolvida na gaveta de ação.
  // Separado de `ufcrmAberto`, que abre a gaveta de detalhes: tocar no selo
  // age sobre a recomendação, tocar no resto da linha abre o detalhe.
  const [acaoAberta, setAcaoAberta] = useState<MedicoRanking | null>(null);
  // Passo em que a gaveta de ação abre. O selo da lista abre na escolha; os
  // botões do card abrem na escolha ou direto nos motivos.
  const [passoAcao, setPassoAcao] = useState<"escolha" | "motivo">("escolha");

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
        setAtualizadoEm(resp.atualizado_em ?? null);
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
      <div className="rounded-2xl p-4 text-white" style={{ background: ROXO_HEADER }}>
        <p className="mb-0.5 text-base font-bold">Ranking de médicos</p>
        <p className="mb-3 text-xs opacity-80">
          {formatarCiclo(ciclo)} · Setor S{setor}
        </p>
        <div className="flex gap-4">
          <div>
            <p className="text-[10px] uppercase tracking-wider opacity-70">Médicos</p>
            {/* Branco como no protótipo. Era rosa para ler junto com o limite
                do painel na aba Usuário; o limite saiu de lá em 18/09/2026. */}
            <p className="text-lg font-bold">{totalMedicos.toLocaleString("pt-BR")}</p>
          </div>
          <div className="w-px bg-white/20" />
          <div>
            <p className="text-[10px] uppercase tracking-wider opacity-70">Líder</p>
            <p className="text-sm font-bold leading-tight">{formatarPontos(pontosLider)}</p>
          </div>
          <div className="w-px bg-white/20" />
          <div>
            <p className="text-[10px] uppercase tracking-wider opacity-70">Atualizado</p>
            {/* Data da última carga do histórico de recomendações, indicada
                por George em 18/09/2026 porque a tabela do ranking só tem o
                ciclo. Cai no ciclo quando o backend não conseguiu ler. */}
            <p className="text-sm font-bold">
              {atualizadoEm ? formatarDataCurta(atualizadoEm) : formatarCicloCurto(ciclo)}
            </p>
          </div>
        </div>
      </div>

      {/* Permanente desde 18/09/2026, decisão de George ao alinhar ao
          protótipo. Antes fechava com um X e não voltava. */}
      <SobreORanking />

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
        {medicos.map((medico) => {
          const medalha = corDaMedalha(medico.posicao);
          return (
          <div
            key={medico.ufcrm}
            className="flex w-full items-center gap-3 rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] px-4 py-3 shadow-sm"
            style={medalha ? { borderLeft: `3px solid ${medalha}` } : undefined}
          >
            <button
              type="button"
              onClick={() => setUfcrmAberto(medico.ufcrm)}
              className="flex min-w-0 flex-1 items-center gap-3 text-left transition-opacity active:opacity-75"
            >
              {/* Pódio nos três primeiros: círculo na cor da medalha com o
                  número em branco, como no protótipo. */}
              {medalha ? (
                <span
                  className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full text-xs font-bold text-white"
                  style={{ background: medalha }}
                >
                  {medico.posicao}
                </span>
              ) : (
                <span className="w-7 flex-shrink-0 text-center text-sm font-bold text-[var(--color-muted-foreground)]">
                  {medico.posicao}
                </span>
              )}
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
              <p className="text-sm font-bold" style={{ color: corDaPontuacao(medico.posicao) }}>
                {formatarPontos(medico.pontos)}
              </p>
              {/* Recomendação pendente vira ação; sem ela, volta o selo de
                  painel, que é informação. Médico que deve permanecer não
                  mostra nada de ação, decisão de George em 04/09/2026. */}
              {medico.id_recomendacao_pendente && medico.tipo_recomendacao_pendente ? (
                <button
                  type="button"
                  aria-label={`Resolver recomendação de ${capitalizarNome(medico.nome_medico)}`}
                  onClick={() => {
                    setPassoAcao("escolha");
                    setAcaoAberta(medico);
                  }}
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
          );
        })}

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
          key={`${acaoAberta.ufcrm}-${passoAcao}`}
          medico={acaoAberta}
          email={email}
          passoInicial={passoAcao}
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
          medico={medicos.find((m) => m.ufcrm === ufcrmAberto) ?? null}
          onFechar={() => setUfcrmAberto(null)}
          onResolver={(passo) => {
            const alvo = medicos.find((m) => m.ufcrm === ufcrmAberto);
            if (!alvo) return;
            setPassoAcao(passo);
            setAcaoAberta(alvo);
          }}
        />
      )}
    </div>
  );
}

/** Etiqueta da fonte do endereço. A auditoria pede conferência porque grava
 *  cidade agregada e endereço sem tipo de logradouro; o CNES é vínculo
 *  institucional, hospital ou posto, e pode não ser o consultório. */
function CardEndereco({
  endereco: e,
  onCorrigir,
}: {
  endereco: EnderecoAtendimento;
  /** Abre o formulário de correção preenchido com este cartão. */
  onCorrigir?: () => void;
}) {
  const linha1 = [capitalizarNome(e.logradouro ?? ""), e.numero, e.complemento && capitalizarNome(e.complemento)]
    .filter(Boolean)
    .join(", ");
  const linha2 = [e.bairro && capitalizarNome(e.bairro), e.cidade && capitalizarNome(e.cidade), e.uf]
    .filter(Boolean)
    .join(", ");
  return (
    <div className="flex items-start gap-2 rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] p-4">
      <MapPin className="mt-0.5 h-4 w-4 flex-shrink-0" style={{ color: ROXO_TEXTO }} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        {e.local && (
          <p className="text-xs font-semibold text-[var(--color-foreground)]">{capitalizarNome(e.local)}</p>
        )}
        <p className="text-xs leading-relaxed text-[var(--color-foreground)]">{linha1}</p>
        <p className="text-xs leading-relaxed text-[var(--color-muted-foreground)]">
          {linha2}
          {e.cep ? ` · CEP ${e.cep}` : ""}
        </p>
        {e.telefone && (
          <p className="text-xs leading-relaxed text-[var(--color-muted-foreground)]">Tel. {e.telefone}</p>
        )}
        {onCorrigir && (
          <button
            type="button"
            onClick={onCorrigir}
            className="mt-2 text-[11px] font-semibold text-[var(--color-primary)]"
          >
            Endereço incorreto?
          </button>
        )}
      </div>
    </div>
  );
}

/** Formulário de correção do endereço, na própria gaveta. Pré-preenchido com
 *  o endereço 1 atual, para a pessoa só mudar o que está errado. Os campos
 *  seguem o corpo do PUT; a validação de UF e CEP é a do backend, repetida
 *  aqui só para não ir ao servidor buscar um 422. */
function FormularioEndereco({
  inicial,
  salvando,
  erro,
  onSalvar,
  onCancelar,
}: {
  inicial: EnderecoAtendimento | null;
  salvando: boolean;
  erro: string | null;
  onSalvar: (corpo: EnderecoCorrecao) => void;
  onCancelar: () => void;
}) {
  // No SalesFarma o número vem dentro do logradouro; deixa como está e a
  // pessoa separa se quiser.
  const [logradouro, setLogradouro] = useState(inicial?.logradouro ?? "");
  const [numero, setNumero] = useState(inicial?.numero ?? "");
  const [complemento, setComplemento] = useState(inicial?.complemento ?? "");
  const [bairro, setBairro] = useState(inicial?.bairro ?? "");
  const [cidade, setCidade] = useState((inicial?.cidade ?? "").replace(/-\s*[A-Za-z]{2}\s*$/, ""));
  const [uf, setUf] = useState(inicial?.uf ?? "");
  const [cep, setCep] = useState(inicial?.cep ?? "");
  const [observacao, setObservacao] = useState("");

  const cepDigitos = cep.replace(/\D/g, "");
  const invalido =
    logradouro.trim().length < 3 ||
    cidade.trim().length < 2 ||
    !/^[A-Za-z]{2}$/.test(uf.trim()) ||
    (cepDigitos.length > 0 && cepDigitos.length !== 8);

  const campo = "w-full rounded-xl border border-[var(--color-border)] bg-white px-3 py-2 text-sm text-[var(--color-foreground)] outline-none focus:border-pink-300";

  return (
    <div className="space-y-2 rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] p-4">
      <p className="text-xs font-semibold text-[var(--color-foreground)]">Corrigir endereço de atendimento</p>
      <input className={campo} placeholder="Logradouro" value={logradouro} onChange={(e) => setLogradouro(e.target.value)} />
      <div className="flex gap-2">
        <input className={campo} placeholder="Número" value={numero} onChange={(e) => setNumero(e.target.value)} />
        <input className={campo} placeholder="Complemento" value={complemento} onChange={(e) => setComplemento(e.target.value)} />
      </div>
      <input className={campo} placeholder="Bairro" value={bairro} onChange={(e) => setBairro(e.target.value)} />
      <div className="flex gap-2">
        <input className={campo} placeholder="Cidade" value={cidade} onChange={(e) => setCidade(e.target.value)} />
        <input className={`${campo} max-w-[72px] uppercase`} placeholder="UF" maxLength={2} value={uf} onChange={(e) => setUf(e.target.value)} />
      </div>
      <input className={campo} placeholder="CEP" value={cep} onChange={(e) => setCep(e.target.value)} />
      <input className={campo} placeholder="O que estava errado? (opcional)" value={observacao} onChange={(e) => setObservacao(e.target.value)} />
      {erro && <p className="text-xs text-[var(--color-destructive)]">{erro}</p>}
      <div className="flex gap-2 pt-1">
        <button
          type="button"
          disabled={salvando}
          onClick={onCancelar}
          className="flex-1 rounded-xl bg-[var(--color-muted)] py-2.5 text-sm font-medium text-[var(--color-muted-foreground)]"
        >
          Cancelar
        </button>
        <button
          type="button"
          disabled={salvando || invalido}
          onClick={() =>
            onSalvar({
              logradouro: logradouro.trim(),
              numero: numero.trim() || null,
              complemento: complemento.trim() || null,
              bairro: bairro.trim() || null,
              cidade: cidade.trim(),
              uf: uf.trim().toUpperCase(),
              cep: cepDigitos || null,
              observacao: observacao.trim() || null,
            })
          }
          className="flex-1 rounded-xl py-2.5 text-sm font-bold text-white disabled:opacity-50"
          style={{ background: "var(--color-primary)" }}
        >
          {salvando ? "Salvando..." : "Salvar"}
        </button>
      </div>
      <p className="text-[11px] text-[var(--color-muted-foreground)]">
        A correção vale para todos que visitam este médico e fica registrada com
        seu nome. O SalesFarma será atualizado quando a integração existir.
      </p>
    </div>
  );
}

interface GavetaMedicoProps {
  email: string;
  ufcrm: string;
  /** A recomendação pendente do médico, se houver. Quem já está no painel e
   *  não tem sugestão não ganha rodapé de ação. Só estes dois campos, para a
   *  aba Recomendações abrir a mesma gaveta a partir do item da lista. */
  medico?: Pick<MedicoRanking, "id_recomendacao_pendente" | "tipo_recomendacao_pendente"> | null;
  onFechar: () => void;
  /** Leva a conversa para a aba Home com o médico já perguntado. */
  /** Abre a gaveta de ação sobre a recomendação pendente, no passo pedido:
   *  "escolha" para aceitar, "motivo" para desconsiderar. Botões do rodapé,
   *  decisão de George em 18/09/2026. */
  onResolver?: (passo: "escolha" | "motivo") => void;
  onMaisDetalhes?: () => void;
  /** "recomendacao" é o detalhe do protótipo na aba Recomendações: sem
   *  endereços e com só dois dados (está no painel e tamanho do painel).
   *  Decisão de George em 20/09/2026. O padrão é o card completo do Ranking. */
  variante?: "completa" | "recomendacao";
}

/** Card do médico. Compartilhado com a aba Recomendações desde 20/09/2026:
 *  o "Ver detalhes" do protótipo é este mesmo card, com os mesmos botões. */
export function GavetaMedico({
  email,
  ufcrm,
  medico,
  onFechar,
  onResolver,
  onMaisDetalhes,
  variante = "completa",
}: GavetaMedicoProps) {
  const compacta = variante === "recomendacao";
  const [detalhe, setDetalhe] = useState<DetalheMedicoResponse | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  // Correção de endereço. Decisão de George em 18/09/2026: o propagandista
  // mantém o endereço no portal. Desde 20/09/2026 todo cartão oferece a
  // correção, e o formulário abre preenchido com o cartão clicado:
  // `undefined` é fechado, `null` é "informar endereço" do zero.
  const [enderecoEmCorrecao, setEnderecoEmCorrecao] = useState<EnderecoAtendimento | null | undefined>(undefined);
  const [salvandoEndereco, setSalvandoEndereco] = useState(false);
  const [erroEndereco, setErroEndereco] = useState<string | null>(null);

  function salvarEndereco(corpo: EnderecoCorrecao) {
    setSalvandoEndereco(true);
    setErroEndereco(null);
    corrigirEndereco(email, ufcrm, corpo)
      .then((atualizado) => {
        setDetalhe(atualizado);
        setEnderecoEmCorrecao(undefined);
      })
      .catch((excecao) =>
        setErroEndereco(
          excecao instanceof ApiError ? excecao.message : "Não foi possível salvar o endereço. Tente novamente.",
        ),
      )
      .finally(() => setSalvandoEndereco(false));
  }
  useEffect(() => {
    let ativo = true;
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
    return () => {
      ativo = false;
    };
  }, [email, ufcrm]);

  // Corte de 3 meses fechado em 18/09/2026. Nulo quando o dado não veio.
  const semVisita3Meses =
    detalhe?.meses_sem_visita === null || detalhe?.meses_sem_visita === undefined
      ? null
      : detalhe.meses_sem_visita >= 3;

  // Uma lista só, na ordem: endereço da visita primeiro, depois o do CNES.
  // Sem etiqueta de fonte, sem "também atende em" e sem aviso de cidades
  // diferentes: decisão de George em 20/09/2026, para o card não virar
  // relatório. A regra de escolha continua em backend/app/enderecos.py.
  const todosOsEnderecos = detalhe ? [...detalhe.enderecos, ...detalhe.outros_locais] : [];

  const pctLider =
    detalhe?.pontos && detalhe?.pontos_lider
      ? Math.min(100, Math.round((detalhe.pontos / detalhe.pontos_lider) * 100))
      : null;


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
              {detalhe && compacta ? (
                <>
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <p className="text-lg font-bold leading-tight text-[var(--color-foreground)]">
                      {capitalizarNome(detalhe.nome_medico)}
                    </p>
                    {medico?.tipo_recomendacao_pendente && (
                      <span
                        className="rounded-full px-2 py-0.5 text-[10px] font-bold text-white"
                        style={{
                          background:
                            medico.tipo_recomendacao_pendente === "ENTRADA_PAINEL"
                              ? "var(--color-primary)"
                              : LARANJA_EXCLUSAO,
                        }}
                      >
                        {medico.tipo_recomendacao_pendente === "ENTRADA_PAINEL" ? "Inclusão" : "Exclusão"}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">
                    {[
                      detalhe.especialidade ? capitalizarNome(detalhe.especialidade) : null,
                      detalhe.cidade
                        ? `${capitalizarNome(detalhe.cidade)}${detalhe.uf ? `, ${detalhe.uf}` : ""}`
                        : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                </>
              ) : compacta ? (
                !erro && (
                  <div className="space-y-2" aria-hidden="true">
                    <div className="flex items-center gap-2">
                      <div className="h-5 w-48 rounded-sm skeleton-shimmer" />
                      <div className="h-4 w-14 rounded-full skeleton-shimmer" />
                    </div>
                    <div className="h-3 w-40 rounded-sm skeleton-shimmer" />
                  </div>
                )
              ) : detalhe ? (
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

        {compacta && !detalhe && erro && (
          <div className="flex min-h-[50vh] flex-1 items-center justify-center px-5 pb-6">
            <p className="text-center text-sm text-[var(--color-muted-foreground)]">{erro}</p>
          </div>
        )}

        {compacta && !detalhe && !erro && (
          <>
            <div className="flex-1 space-y-4 px-5 pb-6 pt-3">
              <PontinhosDeCarregamento texto="Carregando detalhes do médico" />
              <div className="space-y-4" aria-hidden="true">
                <div className="h-12 rounded-xl skeleton-shimmer" />
                <div className="flex gap-3">
                  <div className="h-20 flex-1 rounded-xl skeleton-shimmer" />
                  <div className="h-20 flex-1 rounded-xl skeleton-shimmer" />
                </div>
                <div className="space-y-1.5">
                  <div className="flex justify-between">
                    <div className="h-3 w-24 rounded-sm skeleton-shimmer" />
                    <div className="h-3 w-8 rounded-sm skeleton-shimmer" />
                  </div>
                  <div className="h-1.5 w-full rounded-full skeleton-shimmer" />
                </div>
                <div className="h-24 rounded-xl skeleton-shimmer" />
                <div className="space-y-2">
                  <div className="h-3 w-28 rounded-sm skeleton-shimmer" />
                  <div className="h-20 rounded-xl skeleton-shimmer" />
                </div>
                {onMaisDetalhes && <div className="h-11 rounded-xl skeleton-shimmer" />}
              </div>
            </div>
            {medico?.id_recomendacao_pendente && onResolver && (
              <div
                className="flex-shrink-0 space-y-2 border-t border-[var(--color-border)] px-5 py-4"
                aria-hidden="true"
              >
                <div className="h-10 rounded-xl skeleton-shimmer" />
                <div className="h-10 rounded-xl skeleton-shimmer" />
              </div>
            )}
          </>
        )}

        {detalhe && compacta && (
          <div className="flex-1 space-y-4 overflow-y-auto px-5 pb-6">
            <div
              role="status"
              className="rounded-xl px-4 py-3.5 text-xs font-semibold leading-5"
              style={(() => {
                const estilo =
                  detalhe.recomendacao === "ADICIONAR"
                    ? { fundo: "var(--color-accent)", texto: "var(--color-primary)" }
                    : detalhe.recomendacao === "REMOVER"
                      ? { fundo: AMARELO_CLARO, texto: LARANJA_TEXTO }
                      : ESTILO_RECOMENDACAO[detalhe.recomendacao] ?? ESTILO_SEM_ACAO;
                return { background: estilo.fundo, color: estilo.texto };
              })()}
            >
              {fraseDaRecomendacao(detalhe)}
            </div>

            <div className="flex gap-3">
              <div
                className="flex flex-1 flex-col items-center justify-center rounded-xl px-4 py-4 text-center"
                style={{ background: ROXO_CLARO }}
              >
                {corDaMedalha(detalhe.posicao) ? (
                  <span
                    className="mb-1 flex h-9 w-9 items-center justify-center rounded-full text-base font-bold text-white"
                    style={{ background: corDaMedalha(detalhe.posicao)! }}
                  >
                    {detalhe.posicao}
                  </span>
                ) : (
                  <p className="text-2xl font-bold leading-8" style={{ color: ROXO_TEXTO }}>
                    #{detalhe.posicao ?? "—"}
                  </p>
                )}
                <p className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: ROXO_TEXTO }}>
                  Posição no ranking
                </p>
              </div>
              <div
                className="flex flex-1 flex-col items-center justify-center rounded-xl px-4 py-4 text-center"
                style={{ background: VERDE_CLARO }}
              >
                <p className="text-base font-bold leading-tight" style={{ color: VERDE_TOP10 }}>
                  {detalhe.pontos != null
                    ? detalhe.pontos.toLocaleString("pt-BR", { maximumFractionDigits: 0 })
                    : "—"}
                </p>
                <p className="mt-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-muted-foreground)]">
                  Pontuação (pts)
                </p>
              </div>
            </div>

            {pctLider !== null && (
              <div>
                <div className="mb-1.5 flex justify-between text-[11px] text-[var(--color-muted-foreground)]">
                  <span>Vs. líder do setor</span>
                  <span className="font-semibold text-[var(--color-foreground)]">{pctLider}%</span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--color-muted)]">
                  <div
                    className="h-full rounded-full bg-[var(--color-primary)]"
                    style={{ width: `${pctLider}%` }}
                  />
                </div>
              </div>
            )}

            <div className="space-y-1.5 rounded-xl p-4" style={{ background: ROXO_CLARO }}>
              <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: ROXO_TEXTO }}>
                Por que está nesta posição?
              </p>
              <p className="text-xs leading-relaxed" style={{ color: ROXO_TEXTO }}>
                {textoDaPosicao(detalhe.posicao, detalhe.nome_medico)}
              </p>
            </div>

            <div>
              <p className="mb-2 text-[11px] font-bold uppercase tracking-widest text-[var(--color-primary)]">
                Dados do médico
              </p>
              <div className="divide-y divide-[var(--color-border)] rounded-xl border border-[var(--color-border)] bg-[var(--color-card)]">
                {[
                  {
                    rotulo: "Está no painel",
                    valor: detalhe.no_painel ? "Sim" : "Não",
                    cor: detalhe.no_painel ? VERDE_TOP10 : VERMELHO_ALERTA,
                  },
                  {
                    rotulo: "Tamanho do painel do setor",
                    valor: detalhe.qtd_painel_setor != null ? `${detalhe.qtd_painel_setor} médicos` : "—",
                    cor: "var(--color-foreground)",
                  },
                ].map((linha) => (
                  <div key={linha.rotulo} className="flex items-center justify-between gap-3 px-4 py-3">
                    <p className="flex-1 text-xs text-[var(--color-muted-foreground)]">{linha.rotulo}</p>
                    <p className="flex-shrink-0 text-right text-xs font-semibold" style={{ color: linha.cor }}>
                      {linha.valor}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            {onMaisDetalhes && (
              <button
                type="button"
                onClick={onMaisDetalhes}
                className="flex w-full items-center justify-center gap-2 rounded-xl border bg-[var(--color-card)] py-3 text-sm font-semibold transition-opacity active:opacity-80"
                style={{ borderColor: ROXO_TEXTO, color: ROXO_TEXTO }}
              >
                <MessageSquare className="h-4 w-4" aria-hidden="true" />
                Mais detalhes sobre esse médico
              </button>
            )}
          </div>
        )}

        {detalhe && !compacta && (
          <div className="flex-1 space-y-4 overflow-y-auto px-5 pb-6">
            {/* Recomendação do sistema: alerta colorido pelo tipo, sem
                título nem selo, como no protótipo. */}
            {(() => {
              const estilo = ESTILO_RECOMENDACAO[detalhe.recomendacao] ?? ESTILO_SEM_ACAO;
              return (
                <div
                  role="status"
                  className="rounded-2xl px-4 py-3 text-sm font-semibold leading-relaxed"
                  style={{ background: estilo.fundo, color: estilo.texto }}
                >
                  {fraseDaRecomendacao(detalhe)}
                </div>
              );
            })()}

            {/* Posição e pontos */}
            <div className="flex gap-3">
              {/* Caixas do protótipo: posição em lilás, pontuação em verde. */}
              <div className="flex flex-1 flex-col items-center rounded-2xl px-4 py-3 text-center" style={{ background: "#F0EDF8" }}>
                {/* Medalha nos três primeiros, como na lista e no protótipo. */}
                {corDaMedalha(detalhe.posicao) ? (
                  <span
                    className="mb-1 flex h-9 w-9 items-center justify-center rounded-full text-base font-bold text-white"
                    style={{ background: corDaMedalha(detalhe.posicao)! }}
                  >
                    {detalhe.posicao}
                  </span>
                ) : (
                  <p className="text-2xl font-bold" style={{ color: "#5D4A95" }}>
                    #{detalhe.posicao ?? "—"}
                  </p>
                )}
                <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-muted-foreground)]">
                  Posição no ranking
                </p>
              </div>
              <div className="flex-1 rounded-2xl px-4 py-3 text-center" style={{ background: "#ECF6EF" }}>
                <p className="text-base font-bold leading-tight" style={{ color: "#18A158" }}>
                  {formatarPontos(detalhe.pontos)}
                </p>
                <p className="mt-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-muted-foreground)]">
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

            {/* Por que está nesta posição: os textos do protótipo, um por
                faixa de posição, copiados palavra por palavra. Decisão de
                George em 18/09/2026. São genéricos de propósito: o motor não
                expõe os fatores por médico. */}
            <div className="space-y-1.5 rounded-2xl p-4" style={{ background: "#EDE8F5" }}>
              <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: ROXO_TEXTO }}>
                Por que está nesta posição?
              </p>
              <p className="text-xs leading-relaxed" style={{ color: ROXO_TEXTO }}>
                {textoDaPosicao(detalhe.posicao, detalhe.nome_medico)}
              </p>
            </div>

            {/* Endereços, na posição do protótipo. Endereço 1 é o da visita,
                SalesFarma ou auditoria; endereço 2 é "também atende em", do
                CNES. Regra e medições em backend/app/enderecos.py. A edição
                com sincronização de volta ao SalesFarma fica para quando a
                integração existir, decisão de George em 18/09/2026. */}
            <div>
              <p className="mb-2 text-[11px] font-bold uppercase tracking-widest text-[var(--color-primary)]">
                {todosOsEnderecos.length > 1 ? "Endereços de atendimento" : "Endereço de atendimento"}
              </p>
              {enderecoEmCorrecao !== undefined ? (
                <FormularioEndereco
                  inicial={enderecoEmCorrecao}
                  salvando={salvandoEndereco}
                  erro={erroEndereco}
                  onSalvar={salvarEndereco}
                  onCancelar={() => {
                    setEnderecoEmCorrecao(undefined);
                    setErroEndereco(null);
                  }}
                />
              ) : todosOsEnderecos.length === 0 ? (
                <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] p-4">
                  <p className="text-xs text-[var(--color-muted-foreground)]">
                    Endereço não cadastrado no SalesFarma nem na auditoria.
                  </p>
                  <button
                    type="button"
                    onClick={() => setEnderecoEmCorrecao(null)}
                    className="mt-2 text-[11px] font-semibold text-[var(--color-primary)]"
                  >
                    Informar endereço
                  </button>
                </div>
              ) : (
                <div className="space-y-2">
                  {todosOsEnderecos.map((e, i) => (
                    <CardEndereco
                      key={`${e.fonte}-${e.cep}-${i}`}
                      endereco={e}
                      onCorrigir={() => setEnderecoEmCorrecao(e)}
                    />
                  ))}
                </div>
              )}
            </div>

            {/* Dados do médico */}
            <div>
              <p className="mb-2 text-[11px] font-bold uppercase tracking-widest text-[var(--color-primary)]">
                Dados do médico
              </p>
              <div className="divide-y divide-[var(--color-border)] rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)]">
                {[
                  // Verde no Sim e vermelho no Não, cores do protótipo. O
                  // rótulo é "painel", não "ranking": decisão de nomenclatura
                  // de 16/09/2026, reafirmada por George em 18/09/2026.
                  {
                    rotulo: "Está no painel",
                    valor: detalhe.no_painel ? "Sim" : "Não",
                    cor: detalhe.no_painel ? VERDE_TOP10 : VERMELHO_ALERTA,
                  },
                  // Ordem pedida por George em 20/09/2026: primeiro o que é do
                  // painel (está, há quantos ciclos), depois o que é de visita.
                  {
                    rotulo: "Ciclos no painel",
                    valor: detalhe.ciclos_no_painel_janela?.toString() ?? "—",
                  },
                  { rotulo: "Última visita", valor: formatarData(detalhe.data_ultima_visita) },
                  {
                    rotulo: "Meses desde a última visita",
                    valor:
                      detalhe.meses_sem_visita !== null && detalhe.meses_sem_visita !== undefined
                        ? `${detalhe.meses_sem_visita} ${detalhe.meses_sem_visita === 1 ? "mês" : "meses"}`
                        : "—",
                  },
                  // Corte de 3 meses fechado por George em 18/09/2026; o
                  // protótipo mostra 5. Em vermelho quando é Sim, como lá.
                  {
                    rotulo: "Sem visita há 3 meses ou mais",
                    valor: semVisita3Meses === null ? "—" : semVisita3Meses ? "Sim" : "Não",
                    alerta: semVisita3Meses === true,
                  },
                  // Pela flag do ranking: no painel há toda a janela de 3
                  // ciclos e nunca visitado. O protótipo diz "(5 ciclos)"; o
                  // corte de 3 é decisão de George em 18/09/2026.
                  {
                    rotulo: "Nunca visitado (3 ciclos)",
                    valor:
                      detalhe.nunca_visitado_na_janela === null || detalhe.nunca_visitado_na_janela === undefined
                        ? "—"
                        : detalhe.nunca_visitado_na_janela ? "Sim" : "Não",
                    alerta: detalhe.nunca_visitado_na_janela === true,
                  },
                ].map((linha) => (
                  <div key={linha.rotulo} className="flex items-center justify-between gap-3 px-4 py-3">
                    <p className="flex-1 text-xs text-[var(--color-muted-foreground)]">{linha.rotulo}</p>
                    <p
                      className="flex-shrink-0 text-right text-xs font-semibold"
                      style={{
                        color:
                          "cor" in linha && linha.cor
                            ? linha.cor
                            : "alerta" in linha && linha.alerta
                              ? VERMELHO_ALERTA
                              : "var(--color-foreground)",
                      }}
                    >
                      {linha.valor}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Rodapé de ação, fixo, como no protótipo. Só aparece para médico
            com recomendação pendente: quem já está no painel e não tem
            sugestão não tem o que aceitar. Os dois botões abrem a mesma
            GavetaDeAcao, que já chama os endpoints; o de desconsiderar pula
            direto para os motivos. */}
        {detalhe && medico?.id_recomendacao_pendente && onResolver && compacta && (
          <div className="flex-shrink-0 space-y-2 border-t border-[var(--color-border)] px-5 py-4">
            <button
              type="button"
              onClick={() => onResolver("escolha")}
              className="w-full rounded-xl py-2.5 text-sm font-bold text-white transition-opacity active:opacity-80"
              style={{
                background:
                  medico.tipo_recomendacao_pendente === "ENTRADA_PAINEL"
                    ? "var(--color-primary)"
                    : LARANJA_EXCLUSAO,
              }}
            >
              {medico.tipo_recomendacao_pendente === "ENTRADA_PAINEL"
                ? "Aceitar inclusão"
                : "Aceitar exclusão"}
            </button>
            <button
              type="button"
              onClick={() => onResolver("motivo")}
              className="w-full rounded-xl bg-[var(--color-secondary)] py-2.5 text-sm font-semibold transition-opacity active:opacity-80"
              style={{ color: CINZA_BOTAO }}
            >
              Desconsiderar sugestão
            </button>
          </div>
        )}

        {detalhe && medico?.id_recomendacao_pendente && onResolver && !compacta && (
          <div className="flex-shrink-0 space-y-2 border-t border-[var(--color-border)] px-5 py-4">
            <button
              type="button"
              onClick={() => onResolver("escolha")}
              className="w-full rounded-2xl py-3 text-sm font-bold text-white transition-opacity active:opacity-80"
              style={{
                background:
                  medico.tipo_recomendacao_pendente === "ENTRADA_PAINEL"
                    ? "var(--color-primary)"
                    : LARANJA_EXCLUSAO,
              }}
            >
              {medico.tipo_recomendacao_pendente === "ENTRADA_PAINEL"
                ? "Aceitar inclusão"
                : "Aceitar exclusão"}
            </button>
            <button
              type="button"
              onClick={() => onResolver("motivo")}
              className="w-full rounded-2xl border border-[var(--color-border)] bg-white py-3 text-sm font-semibold text-[var(--color-muted-foreground)] transition-opacity active:opacity-80"
            >
              Desconsiderar sugestão
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
