import { useEffect, useRef, useState } from "react";
import { MapPin, Send } from "lucide-react";
import {
  ApiError,
  listarEntrada,
  listarRanking,
  listarRevisao,
  type MedicoRanking,
  type RecomendacaoItem,
} from "@/lib/api";
import { GavetaDeAcao } from "@/components/GavetaDeAcao";
import { capitalizarNome, formatarPontos, motivoDoDetalhe } from "@/pages/Recomendacoes";

/**
 * Home do portal: o fluxo guiado do protótipo `ped_prototipo_novo_fluxo.html`.
 *
 * Decisão de George em 20/09/2026: a Home funciona exatamente como o HTML,
 * sem o motor no fluxo. A pessoa navega por chips, e o que é dado real vem
 * dos endpoints que já existem: os cinco cards de inclusão e de exclusão de
 * `/recomendacoes/entrada` e `/revisao`, e a busca de médico de `/ranking?q=`.
 * "Veja mais" em qualquer card responde "O fluxo será definido pelo time de
 * Negócios e Produto", porque é o Bruno e a Ju que vão definir. O que o motor
 * sabe fazer (o que levar, o que mais prescreve, tempo de visita, memória de
 * visitas) sai do chat por enquanto e vira botão separado depois; o `Chat.tsx`
 * continua no repositório para esse dia.
 *
 * O texto livre na caixa responde por palavra-chave, copiado do HTML. Não
 * chama o motor.
 *
 * Acabamento visual fica com o Thiago quando a Ju fechar o Figma; aqui o
 * objetivo é o fluxo funcionando com dado real.
 */

const FUNDO_CONVERSA = "#F7F7FA";
const LARANJA_EXCLUSAO = "#F59E0B";
const VERDE_PONTUACAO = "#16A34A";
const ROXO_TEXTO = "#4B3B8C";
const ROXO_CLARO = "#EDE8F5";
const AZUL_STATUS = "#4B62D1";

const FLUXO_A_DEFINIR = "O fluxo será definido pelo time de **Negócios** e **Produto**.";

type Acao = "portal" | "recomendacao" | "ranking" | "medico";
type TipoRecomendacao = "entrada" | "revisao";

const CHIPS: { acao: Acao; rotulo: string }[] = [
  { acao: "portal", rotulo: "O que posso fazer no portal?" },
  { acao: "recomendacao", rotulo: "Como funcionam as recomendações?" },
  { acao: "ranking", rotulo: "Como funciona o ranking?" },
  { acao: "medico", rotulo: "Pesquisar médico" },
];

type Chip = { rotulo: string; destaque?: boolean; ao: () => void };

type Item =
  | { tipo: "usuario"; texto: string }
  | { tipo: "assistente"; texto: string }
  | { tipo: "guia"; titulo: string; intro: string; itens: string[] }
  | { tipo: "chips"; rotulo?: string; chips: Chip[] }
  | { tipo: "recomendacoes"; recomendacao: TipoRecomendacao; itens: RecomendacaoItem[] }
  | { tipo: "busca"; medicos: MedicoRanking[] };

/** Trecho em negrito no meio da linha; a marca sempre em rosa, como no HTML. */
function ComNegrito({ children }: { children: string }) {
  const partes = children.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {partes.map((parte, i) => {
        if (!parte.startsWith("**") || !parte.endsWith("**")) return parte;
        const texto = parte.slice(2, -2);
        return (
          <strong
            key={i}
            className="font-semibold"
            style={texto === "Ped.AI" ? { color: "var(--color-primary)" } : undefined}
          >
            {texto}
          </strong>
        );
      })}
    </>
  );
}

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

function Bolha({ texto }: { texto: string }) {
  return (
    <div className="flex gap-3">
      <Avatar />
      <div className="min-w-0 flex-1">
        <div className="w-fit max-w-full rounded-lg rounded-tl-sm border border-[var(--color-border)] bg-white px-4 py-3 text-sm leading-relaxed shadow-sm">
          {texto.split("\n").map((linha, i) => (
            <p key={i} className={i > 0 ? "mt-2" : undefined}>
              <ComNegrito>{linha}</ComNegrito>
            </p>
          ))}
        </div>
      </div>
    </div>
  );
}

function BolhaUsuario({ texto }: { texto: string }) {
  return (
    <div className="flex justify-end">
      <div
        className="max-w-[75%] rounded-lg rounded-br-sm px-4 py-2.5 text-sm text-white"
        style={{ background: "var(--color-primary)" }}
      >
        {texto}
      </div>
    </div>
  );
}

function Chips({ rotulo, chips }: { rotulo?: string; chips: Chip[] }) {
  return (
    <div className="ml-11">
      {rotulo && (
        <p className="mb-2 text-[11px] font-bold uppercase tracking-widest text-[var(--color-muted-foreground)]">
          {rotulo}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {chips.map((chip) => (
          <button
            key={chip.rotulo}
            type="button"
            onClick={chip.ao}
            className="rounded-full border px-3 py-2 text-xs font-semibold shadow-sm"
            style={
              chip.destaque
                ? { background: "var(--color-accent)", borderColor: "#F6C5DC", color: "#C42C72" }
                : { background: "white", borderColor: "var(--color-border)" }
            }
          >
            {chip.rotulo}
          </button>
        ))}
      </div>
    </div>
  );
}

function CardGuia({ titulo, intro, itens }: { titulo: string; intro: string; itens: string[] }) {
  return (
    <div className="ml-11 rounded-2xl border border-[var(--color-border)] bg-white p-4 shadow-sm">
      <p className="text-sm font-bold">{titulo}</p>
      <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">{intro}</p>
      <ul className="mt-2 divide-y divide-[var(--color-border)]">
        {itens.map((item) => (
          <li key={item} className="flex gap-2 py-2 text-xs leading-relaxed">
            <span className="mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-[var(--color-primary)]" />
            <span>
              <ComNegrito>{item}</ComNegrito>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Metrica({ rotulo, valor, cor }: { rotulo: string; valor: string; cor?: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[9px] font-semibold uppercase tracking-wider text-[var(--color-muted-foreground)]">
        {rotulo}
      </p>
      <p className="text-sm font-bold leading-tight" style={cor ? { color: cor } : undefined}>
        {valor}
      </p>
    </div>
  );
}

/** Card de recomendação no chat, como o HTML: posição, três métricas e os
 *  três botões. */
function CardRecomendacao({
  item,
  recomendacao,
  onVerMais,
  onAceitar,
  onDesconsiderar,
}: {
  item: RecomendacaoItem;
  recomendacao: TipoRecomendacao;
  onVerMais: () => void;
  onAceitar: () => void;
  onDesconsiderar: () => void;
}) {
  const entrada = recomendacao === "entrada";
  const corTipo = entrada ? "var(--color-primary)" : LARANJA_EXCLUSAO;
  const nome = capitalizarNome(item.nome_medico ?? item.ufcrm);
  return (
    <div className="relative rounded-2xl border border-[var(--color-border)] bg-white p-4 shadow-sm">
      {item.posicao_ranking != null && (
        <span
          className="absolute right-3 top-3 rounded-full px-2 py-0.5 text-[10px] font-bold"
          style={{ background: ROXO_CLARO, color: ROXO_TEXTO }}
        >
          #{item.posicao_ranking}
        </span>
      )}
      <p className="pr-12 text-sm font-bold">{nome}</p>
      {item.especialidade && (
        <p className="text-xs text-[var(--color-muted-foreground)]">{capitalizarNome(item.especialidade)}</p>
      )}
      {item.cidade && (
        <p className="mt-0.5 flex items-center gap-1 text-xs text-[var(--color-muted-foreground)]">
          <MapPin className="h-3 w-3" aria-hidden="true" />
          {capitalizarNome(item.cidade)}
          {item.uf ? `, ${item.uf}` : ""}
        </p>
      )}
      <div className="mt-3 grid grid-cols-3 gap-2">
        <Metrica rotulo="Pontuação" valor={formatarPontos(item.soma_pontuacao)} cor={VERDE_PONTUACAO} />
        <Metrica rotulo="Recomendação" valor={entrada ? "Inclusão" : "Exclusão"} cor={corTipo} />
        <Metrica rotulo="Status" valor="Pendente" cor={AZUL_STATUS} />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={onVerMais}
          className="rounded-xl border px-3 py-2 text-xs font-bold"
          style={{ borderColor: "var(--color-primary)", color: "var(--color-primary)" }}
        >
          Veja mais
        </button>
        <button
          type="button"
          onClick={onDesconsiderar}
          className="rounded-xl border px-3 py-2 text-xs font-bold"
          style={{ borderColor: "var(--color-primary)", color: "var(--color-primary)" }}
        >
          Desconsiderar
        </button>
        <button
          type="button"
          onClick={onAceitar}
          className="col-span-2 rounded-xl px-3 py-2 text-xs font-bold text-white"
          style={{ background: corTipo }}
        >
          {entrada ? "Aceitar inclusão" : "Aceitar exclusão"}
        </button>
      </div>
    </div>
  );
}

function statusDoMedico(m: MedicoRanking): string {
  if (m.status_recomendacao === "PENDENTE" && m.tipo_recomendacao_pendente === "ENTRADA_PAINEL") {
    return "Recomendado para inclusão";
  }
  if (m.status_recomendacao === "PENDENTE" && m.tipo_recomendacao_pendente === "REVISAO_PAINEL") {
    return "Recomendado para revisão";
  }
  return m.no_painel ? "No painel" : "Fora do painel";
}

function formatarData(iso?: string | null): string {
  if (!iso) return "—";
  const [ano, mes, dia] = iso.slice(0, 10).split("-");
  return dia && mes && ano ? `${dia}/${mes}/${ano}` : iso;
}

/** Card do médico buscado, como o HTML: quatro métricas e Veja mais, mais
 *  Incluir ou Excluir quando há recomendação pendente. */
function CardBusca({
  medico,
  onVerMais,
  onResolver,
}: {
  medico: MedicoRanking;
  onVerMais: () => void;
  onResolver?: () => void;
}) {
  const pendente = medico.status_recomendacao === "PENDENTE" && medico.id_recomendacao_pendente;
  const entrada = medico.tipo_recomendacao_pendente === "ENTRADA_PAINEL";
  return (
    <div className="rounded-2xl border border-[var(--color-border)] bg-white p-4 shadow-sm">
      <p className="text-sm font-bold">{capitalizarNome(medico.nome_medico)}</p>
      {medico.especialidade && (
        <p className="text-xs text-[var(--color-muted-foreground)]">{capitalizarNome(medico.especialidade)}</p>
      )}
      <p className="mt-0.5 text-[11px] font-semibold text-[var(--color-muted-foreground)]">CRM: {medico.ufcrm}</p>
      {medico.cidade && (
        <p className="mt-0.5 flex items-center gap-1 text-xs text-[var(--color-muted-foreground)]">
          <MapPin className="h-3 w-3" aria-hidden="true" />
          {capitalizarNome(medico.cidade)}
          {medico.uf ? `, ${medico.uf}` : ""}
        </p>
      )}
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metrica rotulo="Pontuação" valor={formatarPontos(medico.pontos)} cor={VERDE_PONTUACAO} />
        <Metrica rotulo="No painel" valor={medico.no_painel ? "Sim" : "Não"} />
        <Metrica rotulo="Status" valor={statusDoMedico(medico)} cor="var(--color-primary)" />
        <Metrica rotulo="Última visita" valor={formatarData(medico.data_ultima_visita)} />
      </div>
      <div className={`mt-3 grid gap-2 ${pendente && onResolver ? "grid-cols-2" : "grid-cols-1"}`}>
        <button
          type="button"
          onClick={onVerMais}
          className="rounded-xl border px-3 py-2 text-xs font-bold"
          style={{ borderColor: "var(--color-primary)", color: "var(--color-primary)" }}
        >
          Veja mais
        </button>
        {pendente && onResolver && (
          <button
            type="button"
            onClick={onResolver}
            className="rounded-xl px-3 py-2 text-xs font-bold text-white"
            style={{ background: entrada ? "var(--color-primary)" : LARANJA_EXCLUSAO }}
          >
            {entrada ? "Incluir" : "Excluir"}
          </button>
        )}
      </div>
    </div>
  );
}

/** Respostas por palavra-chave do texto livre, copiadas do HTML. */
function respostaLivre(texto: string): string {
  const t = texto.toLowerCase();
  if (t.includes("recomenda")) {
    return "Você pode acessar a área de **Recomendações** para entender as sugestões geradas pelo Ped.AI e acompanhar as ações realizadas.";
  }
  if (t.includes("ranking")) {
    return "Na área de **Ranking**, você consulta a lista priorizada de médicos do seu setor e pode abrir os detalhes de cada um.";
  }
  if (t.includes("médico") || t.includes("medico") || t.includes("crm")) {
    return "Para consultar um médico, informe o **nome ou CRM**. A partir do resultado, você poderá abrir as informações disponíveis.";
  }
  if (t.includes("histórico") || t.includes("historico")) {
    return "No **Histórico**, você acompanha o que já aconteceu com as recomendações, incluindo decisões aceitas ou desconsideradas.";
  }
  return "Posso te orientar sobre as principais áreas do portal: **consulta de médicos, recomendações, ranking e histórico**.";
}

/** Ação pendente aberta na gaveta compartilhada. `origem` diz de qual lista
 *  tirar o card depois de resolvida. */
type AcaoAberta = {
  idRecomendacao: string;
  nome: string;
  tipoRecomendacao: "ENTRADA_PAINEL" | "REVISAO_PAINEL";
  frase: string | null;
  passo: "escolha" | "motivo";
};

export function Home({ email, nome }: { email: string; nome?: string | null }) {
  const primeiro = nome?.trim().split(" ")[0];
  const [itens, setItens] = useState<Item[]>([]);
  const [rascunho, setRascunho] = useState("");
  const [aguardandoBusca, setAguardandoBusca] = useState(false);
  const [carregando, setCarregando] = useState(false);
  const [acao, setAcao] = useState<AcaoAberta | null>(null);
  const vistos = useRef(new Set<TipoRecomendacao>());
  const fim = useRef<HTMLDivElement>(null);
  const entrada = useRef<HTMLInputElement>(null);

  function adicionar(...novos: Item[]) {
    setItens((atual) => [...atual, ...novos]);
  }

  useEffect(() => {
    fim.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [itens, carregando]);

  // Abertura e os quatro chips, como no HTML.
  useEffect(() => {
    setItens([
      {
        tipo: "assistente",
        texto:
          `Olá${primeiro ? `, ${primeiro}` : ""}! Eu sou o **Ped.AI**, seu assistente inteligente.\n` +
          "Posso te ajudar a encontrar respostas e entender melhor as informações do seu dia a dia.",
      },
      { tipo: "chips", rotulo: "Sugestões de perguntas", chips: chipsIniciais(null) },
    ]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function chipsIniciais(exceto: Acao | null): Chip[] {
    return CHIPS.filter((c) => c.acao !== exceto).map((c, i) => ({
      rotulo: c.rotulo,
      destaque: exceto === null && i === 0,
      ao: () => executar(c.acao),
    }));
  }

  function outrasSugestoes(atual: Acao): Item {
    return { tipo: "chips", rotulo: "Você também pode perguntar", chips: chipsIniciais(atual) };
  }

  function chipsDeRecomendacoes(tipos: TipoRecomendacao[], destaquePrimeiro = false): Chip[] {
    return tipos.map((t, i) => ({
      rotulo: t === "entrada" ? "Ver as recomendações de inclusão" : "Ver as recomendações de exclusão",
      destaque: destaquePrimeiro && i === 0,
      ao: () => verRecomendacoes(t),
    }));
  }

  function executar(a: Acao) {
    const rotulo = CHIPS.find((c) => c.acao === a)!.rotulo;
    if (a === "portal") {
      adicionar(
        { tipo: "usuario", texto: rotulo },
        {
          tipo: "assistente",
          texto: "O Ped.AI reúne informações para apoiar sua rotina antes e durante o acompanhamento dos médicos do seu setor.",
        },
        {
          tipo: "guia",
          titulo: "Principais recursos do portal",
          intro: "Aqui você pode navegar pelas principais informações do Ped.AI:",
          itens: [
            "**Consultar médicos** pelo nome ou CRM e visualizar informações disponíveis sobre o perfil.",
            "**Acompanhar recomendações** geradas pelo Ped.AI para inclusão, exclusão ou revisão.",
            "**Consultar o ranking** do seu setor e acessar os médicos apresentados.",
            "**Visualizar o histórico** das decisões tomadas sobre recomendações.",
            "**Acessar informações para a visita** a partir do contexto disponível para cada médico.",
          ],
        },
        outrasSugestoes("portal"),
      );
      return;
    }
    if (a === "recomendacao") {
      adicionar(
        { tipo: "usuario", texto: rotulo },
        {
          tipo: "assistente",
          texto:
            "As recomendações são sugestões geradas pelo **Ped.AI** com base no perfil prescritivo dos médicos do seu setor.\n" +
            "**Aceitar inclusão / Aceitar exclusão**\n" +
            "A decisão é registrada e enviada automaticamente ao Sales Pharma. Você pode acompanhar na aba **Histórico**.\n" +
            "**Desconsiderar sugestão**\n" +
            "O médico **não aparecerá mais para você neste ciclo**. Se o perfil continuar elegível, ele poderá reaparecer em ciclos futuros.",
        },
        { tipo: "chips", chips: chipsDeRecomendacoes(["entrada", "revisao"], true) },
      );
      return;
    }
    if (a === "ranking") {
      adicionar(
        { tipo: "usuario", texto: rotulo },
        {
          tipo: "assistente",
          texto:
            "O **Ranking** ajuda a identificar médicos com maior potencial para cada setor, apoiando a priorização das visitas.\n" +
            "Para definir a posição, são combinadas diferentes informações, como:\n" +
            "• histórico de prescrições do médico;\n" +
            "• demanda do mercado na região;\n" +
            "• dados de pesquisas;\n" +
            "• relevância estratégica dos produtos para cada linha;\n" +
            "• categoria do médico (CAT 1, 2 ou 3).\n" +
            "Esses indicadores podem ter pesos diferentes conforme o mercado e a região. A combinação desses fatores gera uma pontuação, que determina a posição do médico no Ranking.\n" +
            "O Ranking funciona como um apoio à tomada de decisão, indicando oportunidades com base nos dados e critérios disponíveis.",
        },
        { tipo: "chips", rotulo: "Sugestões de perguntas", chips: chipsDeRecomendacoes(["entrada", "revisao"]) },
      );
      return;
    }
    // medico
    adicionar(
      { tipo: "usuario", texto: rotulo },
      { tipo: "assistente", texto: "Me diga o **Nome** ou o **CRM** do médico que você deseja consultar." },
    );
    setAguardandoBusca(true);
    entrada.current?.focus();
  }

  async function verRecomendacoes(recomendacao: TipoRecomendacao) {
    const inclusao = recomendacao === "entrada";
    vistos.current.add(recomendacao);
    adicionar({
      tipo: "usuario",
      texto: inclusao ? "Ver as recomendações de inclusão" : "Ver as recomendações de exclusão",
    });
    setCarregando(true);
    try {
      const lista = inclusao ? await listarEntrada(email, 0) : await listarRevisao(email, 0);
      const principais = lista.recomendacoes.slice(0, lista.destaques || 5);
      const oposto: TipoRecomendacao = inclusao ? "revisao" : "entrada";
      adicionar(
        {
          tipo: "assistente",
          texto:
            principais.length === 0
              ? `Você não tem recomendações de ${inclusao ? "inclusão" : "exclusão"} pendentes neste ciclo.`
              : `Estas são as **${principais.length} principais recomendações de ${inclusao ? "inclusão" : "exclusão"}** disponíveis no momento.`,
        },
        { tipo: "recomendacoes", recomendacao, itens: principais },
        vistos.current.has(oposto)
          ? outrasSugestoes("recomendacao")
          : { tipo: "chips", rotulo: "Sugestões de perguntas", chips: chipsDeRecomendacoes([oposto]) },
      );
    } catch (excecao) {
      adicionar({
        tipo: "assistente",
        texto:
          excecao instanceof ApiError ? excecao.message : "Não consegui carregar as recomendações agora. Tente de novo.",
      });
    } finally {
      setCarregando(false);
    }
  }

  function verMais(nomeMedico: string) {
    adicionar({ tipo: "usuario", texto: capitalizarNome(nomeMedico) }, { tipo: "assistente", texto: FLUXO_A_DEFINIR });
  }

  function abrirAcao(item: RecomendacaoItem, recomendacao: TipoRecomendacao, passo: "escolha" | "motivo") {
    setAcao({
      idRecomendacao: item.id_recomendacao,
      nome: capitalizarNome(item.nome_medico ?? item.ufcrm),
      tipoRecomendacao: recomendacao === "entrada" ? "ENTRADA_PAINEL" : "REVISAO_PAINEL",
      frase: motivoDoDetalhe(item, recomendacao === "entrada" ? "entrada" : "exclusao"),
      passo,
    });
  }

  function abrirAcaoDaBusca(m: MedicoRanking) {
    if (!m.id_recomendacao_pendente) return;
    setAcao({
      idRecomendacao: m.id_recomendacao_pendente,
      nome: capitalizarNome(m.nome_medico),
      tipoRecomendacao: m.tipo_recomendacao_pendente === "ENTRADA_PAINEL" ? "ENTRADA_PAINEL" : "REVISAO_PAINEL",
      frase: null,
      passo: "escolha",
    });
  }

  // Depois de resolvida, o card sai da lista do chat e a busca perde a
  // pendência, para a tela não oferecer a mesma ação duas vezes.
  function resolvida(id: string) {
    setItens((atual) =>
      atual.map((item) => {
        if (item.tipo === "recomendacoes") {
          return { ...item, itens: item.itens.filter((r) => r.id_recomendacao !== id) };
        }
        if (item.tipo === "busca") {
          return {
            ...item,
            medicos: item.medicos.map((m) =>
              m.id_recomendacao_pendente === id
                ? { ...m, id_recomendacao_pendente: null, status_recomendacao: null, tipo_recomendacao_pendente: null }
                : m,
            ),
          };
        }
        return item;
      }),
    );
  }

  async function enviar() {
    const texto = rascunho.trim();
    if (!texto || carregando) return;
    setRascunho("");
    adicionar({ tipo: "usuario", texto });

    if (!aguardandoBusca) {
      adicionar({ tipo: "assistente", texto: respostaLivre(texto) });
      return;
    }

    setAguardandoBusca(false);
    setCarregando(true);
    try {
      const resposta = await listarRanking(email, texto, 0);
      const medicos = resposta.medicos.slice(0, 5);
      if (medicos.length === 0) {
        adicionar(
          { tipo: "assistente", texto: `Não encontrei **${texto}** no ranking do seu setor. Confira o nome ou o CRM e tente de novo.` },
          outrasSugestoes("medico"),
        );
      } else {
        adicionar(
          {
            tipo: "assistente",
            texto:
              medicos.length === 1
                ? `Encontrei **${capitalizarNome(medicos[0].nome_medico)}** no seu setor. Veja os detalhes abaixo:`
                : `Encontrei ${medicos.length} médicos para **${texto}** no seu setor. Veja os detalhes abaixo:`,
          },
          { tipo: "busca", medicos },
          outrasSugestoes("medico"),
        );
      }
    } catch (excecao) {
      adicionar({
        tipo: "assistente",
        texto: excecao instanceof ApiError ? excecao.message : "Não consegui buscar agora. Tente de novo.",
      });
    } finally {
      setCarregando(false);
    }
  }

  return (
    <div className="flex h-full w-full flex-col" style={{ background: FUNDO_CONVERSA }}>
      <div className="flex-1 space-y-4 overflow-y-auto px-4 pb-6 pt-4">
        {itens.map((item, i) => {
          if (item.tipo === "usuario") return <BolhaUsuario key={i} texto={item.texto} />;
          if (item.tipo === "assistente") return <Bolha key={i} texto={item.texto} />;
          if (item.tipo === "guia") return <CardGuia key={i} {...item} />;
          if (item.tipo === "chips") return <Chips key={i} rotulo={item.rotulo} chips={item.chips} />;
          if (item.tipo === "recomendacoes") {
            return (
              <div key={i} className="ml-11 space-y-2">
                {item.itens.map((r) => (
                  <CardRecomendacao
                    key={r.id_recomendacao}
                    item={r}
                    recomendacao={item.recomendacao}
                    onVerMais={() => verMais(r.nome_medico ?? r.ufcrm)}
                    onAceitar={() => abrirAcao(r, item.recomendacao, "escolha")}
                    onDesconsiderar={() => abrirAcao(r, item.recomendacao, "motivo")}
                  />
                ))}
              </div>
            );
          }
          return (
            <div key={i} className="ml-11 space-y-2">
              {item.medicos.map((m) => (
                <CardBusca
                  key={m.ufcrm}
                  medico={m}
                  onVerMais={() => verMais(m.nome_medico)}
                  onResolver={m.id_recomendacao_pendente ? () => abrirAcaoDaBusca(m) : undefined}
                />
              ))}
            </div>
          );
        })}
        {carregando && (
          <div className="flex gap-3">
            <Avatar />
            <div className="w-fit rounded-lg rounded-tl-sm border border-[var(--color-border)] bg-white px-4 py-3 shadow-sm">
              <div className="flex h-4 items-center gap-1" role="status" aria-label="Consultando">
                {[0, 1, 2].map((n) => (
                  <span
                    key={n}
                    className="h-1.5 w-1.5 animate-bounce rounded-full bg-[var(--color-primary)]"
                    style={{ animationDelay: `${n * 120}ms` }}
                  />
                ))}
              </div>
            </div>
          </div>
        )}
        <div ref={fim} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void enviar();
        }}
        className="w-full border-t border-[var(--color-border)] bg-white px-4 pb-5 pt-3"
      >
        <div className="mx-auto flex w-full items-center gap-2 rounded-lg bg-[var(--color-muted)] px-4 py-2.5">
          <input
            ref={entrada}
            value={rascunho}
            onChange={(e) => setRascunho(e.target.value)}
            placeholder="Digite o nome do médico ou faça uma pergunta."
            aria-label="Mensagem"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-[var(--color-muted-foreground)]"
          />
          <button
            type="submit"
            disabled={!rascunho.trim() || carregando}
            aria-label="Enviar"
            className="grid h-8 w-8 flex-shrink-0 place-items-center rounded-full bg-[var(--color-primary)] text-white disabled:opacity-40"
          >
            <Send className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </form>

      {acao && (
        <GavetaDeAcao
          nome={acao.nome}
          idRecomendacao={acao.idRecomendacao}
          tipoRecomendacao={acao.tipoRecomendacao}
          frase={acao.frase}
          passoInicial={acao.passo}
          onFechar={() => setAcao(null)}
          onResolvida={() => resolvida(acao.idRecomendacao)}
        />
      )}
    </div>
  );
}
