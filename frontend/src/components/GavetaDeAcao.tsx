import { useEffect, useState } from "react";
import { Ban, Bell, CircleCheck, X } from "lucide-react";
import {
  aceitarRecomendacao,
  ApiError,
  desconsiderar,
  MOTIVOS_DESCONSIDERACAO,
  type MotivoDesconsideracao,
} from "@/lib/api";
import { Alert } from "@/components/ui/alert";
import { ROTULO_MOTIVO } from "@/lib/motivos";

/** O que o aceite significa, por tipo de recomendação.
 *
 *  Precisa variar: aceitar uma recomendação de saída não inclui ninguém, e a
 *  frase de inclusão estaria errada na maioria dos casos. Medido em
 *  04/09/2026: das pendentes, 381.534 são de saída e 211.278 de entrada. */
const EFEITO_DO_ACEITE: Record<string, string> = {
  ENTRADA_PAINEL:
    "Registramos o aceite. A inclusão no painel acontece na próxima carga.",
  REVISAO_PAINEL:
    "Registramos o aceite. A saída do painel acontece na próxima carga.",
};

const EFEITO_DO_ACEITE_PADRAO =
  "Registramos o aceite. A atualização do painel acontece na próxima carga.";

const BORDA_RADIO = "#D1D5DC";
const ROSA_CLARO = "#FFF5F9";
const ROSA_SELECIONADO = "#FDF2F8";
const CINZA_BOTAO = "#364153";
const VERDE_SUCESSO = "#16A34A";
const VERDE_CLARO = "#F0FDF4";
const TEMPO_FECHAMENTO_MS = 2500;

/** Gaveta de ação sobre a recomendação, de baixo para cima.
 *
 *  Três passos, e os textos são os do protótipo do Figma Make, palavra por
 *  palavra, por decisão de George em 04/09/2026. Sem emoji e sem as cores do
 *  protótipo: aceitar e bloquear em rosa, desconsiderar e apenas desconsiderar
 *  em cinza e branco.
 *
 *  A frase da recomendação não é escrita aqui: vem de `fraseDaRecomendacao`,
 *  a mesma do detalhe e do chat, para a mesma recomendação nunca aparecer com
 *  dois textos diferentes em duas telas.
 *
 *  **O aceite grava intenção, não fato.** Quem confirma que o médico entrou no
 *  painel é o job diário que compara contra o painel real. Por isso o texto
 *  fala em "próxima carga" e nunca afirma que o médico já está no painel. */
export function GavetaDeAcao({
  nome,
  idRecomendacao,
  tipoRecomendacao,
  frase,
  ufcrm,
  especialidade,
  passoInicial = "escolha",
  onFechar,
  onResolvida,
}: {
  nome: string;
  idRecomendacao: string;
  /** `ENTRADA_PAINEL` ou `REVISAO_PAINEL`. Decide o texto do efeito do aceite:
   *  aceitar uma recomendação de saída não inclui ninguém. */
  tipoRecomendacao?: string | null;
  /** Frase que explica a recomendação. `null` enquanto a tela ainda busca.
   *  Vem de fora porque cada tela já tem a sua fonte: o Ranking lê do detalhe
   *  do médico, a aba Recomendações já tem o item em mãos. Escrever a frase
   *  aqui criaria uma terceira versão do mesmo texto. */
  frase: string | null;
  ufcrm?: string | null;
  especialidade?: string | null;
  /** Passo em que a gaveta abre. "escolha" mostra aceitar e desconsiderar;
   *  "motivo" pula direto para a lista de motivos da desconsideração. O card
   *  do médico no Ranking usa os dois, um por botão, desde 18/09/2026. */
  passoInicial?: "escolha" | "confirmar" | "motivo";
  onFechar: () => void;
  onResolvida: (statusNovo: string | null) => void;
}) {
  type Passo = "escolha" | "confirmar" | "motivo" | "bloqueio" | "pronto";
  const [passo, setPasso] = useState<Passo>(passoInicial);
  const [motivo, setMotivo] = useState<MotivoDesconsideracao | null>(null);
  const [textoOutros, setTextoOutros] = useState("");
  const [bloquear, setBloquear] = useState<boolean | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [mensagemFinal, setMensagemFinal] = useState("");
  const id = idRecomendacao;
  const efeitoDoAceite =
    EFEITO_DO_ACEITE[tipoRecomendacao ?? ""] ?? EFEITO_DO_ACEITE_PADRAO;
  const exclusao = tipoRecomendacao === "REVISAO_PAINEL";

  /** 400 e 409 querem dizer que a recomendação saiu de pendente enquanto a
   *  gaveta estava aberta, por ação em outra aba ou pela virada de ciclo.
   *  Some com o selo da linha: insistir no botão só repetiria o mesmo erro
   *  até recarregar a lista. Achado da revisão independente de 04/09/2026. */
  function naoEstaMaisPendente(excecao: ApiError) {
    // `null` porque aqui o backend não diz qual é o estado novo: só que já não
    // é pendente. A linha perde a ação e volta ao selo de painel até a próxima
    // carga da lista.
    if (excecao.status === 400 || excecao.status === 409) onResolvida(null);
  }
  useEffect(() => {
    if (passo !== "pronto") return;
    const temporizador = window.setTimeout(onFechar, TEMPO_FECHAMENTO_MS);
    return () => window.clearTimeout(temporizador);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [passo]);

  const podeConfirmarMotivo =
    motivo !== null && (motivo !== "OUTROS" || textoOutros.trim() !== "");

  function aceitar() {
    setEnviando(true);
    setErro(null);
    aceitarRecomendacao(id)
      .then(() => {
        onResolvida("ACEITA");
        onFechar();
      })
      .catch((excecao) => {
        setErro(
          excecao instanceof ApiError
            ? excecao.message
            : "Não foi possível registrar o aceite. Tente novamente.",
        );
        if (excecao instanceof ApiError) naoEstaMaisPendente(excecao);
      })
      .finally(() => setEnviando(false));
  }

  function confirmarDesconsideracao(comBloqueio: boolean) {
    if (!motivo) return;
    setEnviando(true);
    setErro(null);
    desconsiderar(id, {
      motivo,
      motivo_outros_texto: motivo === "OUTROS" ? textoOutros.trim() : null,
      bloquear_novas_recomendacoes: comBloqueio,
    })
      .then(() => {
        setMensagemFinal(
          comBloqueio
            ? "A recomendação foi descartada e você não receberá recomendações futuras sobre este médico."
            : "A recomendação foi descartada, mas você poderá receber novas recomendações deste médico.",
        );
        setPasso("pronto");
        onResolvida("DESCONSIDERADA");
      })
      .catch((excecao) => {
        setErro(
          excecao instanceof ApiError
            ? excecao.message
            : "Não foi possível desconsiderar. Tente novamente.",
        );
        if (excecao instanceof ApiError) naoEstaMaisPendente(excecao);
      })
      .finally(() => setEnviando(false));
  }

  const titulo = {
    escolha: "Recomendação pendente",
    confirmar: exclusao ? "Confirmar exclusão?" : "Confirmar inclusão?",
    motivo: "Desconsiderar sugestão",
    bloqueio: "Bloquear médico?",
    pronto: "Pronto",
  }[passo];

  const subtitulo =
    passo === "motivo" || passo === "bloqueio"
      ? [nome, ufcrm, especialidade].filter(Boolean).join(" · ")
      : nome;

  const botaoSecundario =
    "rounded-xl bg-[var(--color-muted)] py-3 text-sm font-semibold text-[var(--color-muted-foreground)] disabled:opacity-50";

  return (
    <div
      className="fixed inset-x-0 top-0 bottom-14 z-[60] flex items-end"
      style={{ background: "rgba(0,0,0,0.45)" }}
      onClick={onFechar}
    >
      <div
        className="flex max-h-full w-full flex-col rounded-t-3xl bg-[var(--color-card)]"
        onClick={(evento) => evento.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={titulo}
      >
        {passo === "pronto" ? (
          <div className="flex flex-col items-center px-5 pb-10 pt-10 text-center">
            <span
              className="flex h-20 w-20 items-center justify-center rounded-full"
              style={{ background: VERDE_CLARO, color: VERDE_SUCESSO }}
            >
              <CircleCheck className="h-11 w-11" aria-hidden="true" />
            </span>
            <p className="mt-4 text-lg font-bold text-[var(--color-foreground)]">
              Sugestão desconsiderada com sucesso
            </p>
            <p className="mt-4 text-sm text-[var(--color-muted-foreground)]">{mensagemFinal}</p>
          </div>
        ) : (
        <>
        <div className="flex-shrink-0 px-5 pb-4 pt-4">
          <div className="mx-auto mb-4 h-1 w-10 rounded-full bg-[var(--color-border)]" />
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-lg font-bold leading-tight text-[var(--color-foreground)]">
                {titulo}
              </p>
              <p className="mt-1 truncate text-xs text-[var(--color-muted-foreground)]">
                {subtitulo}
              </p>
            </div>
            {passo !== "confirmar" && (
              <button
                type="button"
                onClick={onFechar}
                aria-label="Fechar"
                className="flex-shrink-0 p-1 text-[var(--color-muted-foreground)]"
              >
                <X className="h-5 w-5" aria-hidden="true" />
              </button>
            )}
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-5 pb-5">
          {erro && <Alert variant="erro">{erro}</Alert>}

          {passo === "escolha" && (
            <>
              <p className="text-sm leading-relaxed text-[var(--color-foreground)]">
                {frase === null ? "Carregando…" : frase}
              </p>
              <p className="text-xs font-semibold text-[var(--color-muted-foreground)]">
                Como deseja proceder?
              </p>

              <div className="space-y-3">
                <div>
                  <button
                    type="button"
                    disabled={enviando}
                    onClick={aceitar}
                    className="w-full rounded-xl bg-[var(--color-primary)] py-3 text-sm font-semibold text-white disabled:opacity-50"
                  >
                    {enviando ? "Registrando..." : "Aceitar recomendação"}
                  </button>
                  <p className="mt-1.5 text-xs text-[var(--color-muted-foreground)]">
                    {efeitoDoAceite}
                  </p>
                </div>

                <div>
                  <button
                    type="button"
                    disabled={enviando}
                    onClick={() => setPasso("motivo")}
                    className={`w-full ${botaoSecundario}`}
                  >
                    Desconsiderar a recomendação
                  </button>
                  <p className="mt-1.5 text-xs text-[var(--color-muted-foreground)]">
                    A sugestão sai da sua lista neste ciclo. Pode reaparecer no próximo se o
                    médico continuar elegível.
                  </p>
                </div>
              </div>
            </>
          )}

          {passo === "confirmar" && (
            <p className="text-sm leading-relaxed text-[var(--color-foreground)]">
              {exclusao
                ? "Este médico será excluído do seu Ranking e a alteração será enviada ao Sales Pharma."
                : "Este médico será incluído no seu Ranking e a alteração será enviada ao Sales Pharma."}
            </p>
          )}

          {passo === "motivo" && (
            <>
              <div>
                <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--color-primary)]">
                  Por que deseja desconsiderar?
                </p>
                <p className="mt-1 text-[11px] leading-relaxed text-[var(--color-muted-foreground)]">
                  A sugestão sai da sua lista neste ciclo. Pode reaparecer no próximo se o médico
                  continuar elegível.
                </p>
              </div>
              <div className="space-y-2.5" role="radiogroup" aria-label="Motivo da desconsideração">
                {MOTIVOS_DESCONSIDERACAO.map((codigo) => {
                  const marcado = motivo === codigo;
                  return (
                    <button
                      key={codigo}
                      type="button"
                      role="radio"
                      aria-checked={marcado}
                      onClick={() => setMotivo(codigo)}
                      className="flex w-full items-center gap-3 rounded-xl border border-[var(--color-border)] px-4 py-3.5 text-left"
                      style={marcado ? { background: ROSA_SELECIONADO } : undefined}
                    >
                      <span
                        className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full border"
                        style={{ borderColor: marcado ? "var(--color-primary)" : BORDA_RADIO }}
                        aria-hidden="true"
                      >
                        {marcado && <span className="h-2.5 w-2.5 rounded-full bg-[var(--color-primary)]" />}
                      </span>
                      <span className="text-[13px] font-medium leading-5 text-[var(--color-foreground)]">
                        {ROTULO_MOTIVO[codigo]}
                      </span>
                    </button>
                  );
                })}
              </div>

              {motivo === "OUTROS" && (
                <textarea
                  value={textoOutros}
                  onChange={(e) => setTextoOutros(e.target.value.slice(0, 300))}
                  maxLength={300}
                  placeholder="Descreva rapidamente o motivo."
                  aria-label="Descreva rapidamente o motivo"
                  className="w-full resize-none rounded-xl border border-[var(--color-border)] px-4 py-3 text-sm outline-none"
                  rows={3}
                />
              )}
            </>
          )}

          {passo === "bloqueio" && (
            <>
              <p className="text-sm text-[var(--color-foreground)]">
                O que você deseja fazer com este médico?
              </p>

              <div className="space-y-4">
                <button
                  type="button"
                  disabled={enviando}
                  onClick={() => {
                    setBloquear(false);
                    confirmarDesconsideracao(false);
                  }}
                  className="flex w-full items-center gap-3 rounded-xl border border-[var(--color-border)] p-4 text-left disabled:opacity-50"
                >
                  <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-[var(--color-muted)] text-[var(--color-muted-foreground)]">
                    <Bell className="h-5 w-5" aria-hidden="true" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-sm font-semibold text-[var(--color-foreground)]">
                      {enviando && bloquear === false ? "Salvando..." : "Apenas desconsiderar"}
                    </span>
                    <span className="mt-0.5 block text-xs text-[var(--color-muted-foreground)]">
                      Este médico não aparecerá nas suas recomendações neste ciclo. Se o perfil
                      continuar elegível, poderá reaparecer futuramente.
                    </span>
                  </span>
                </button>

                <button
                  type="button"
                  disabled={enviando}
                  onClick={() => {
                    setBloquear(true);
                    confirmarDesconsideracao(true);
                  }}
                  className="flex w-full items-center gap-3 rounded-xl border p-4 text-left disabled:opacity-50"
                  style={{ borderColor: "var(--color-primary)", background: ROSA_CLARO }}
                >
                  <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-[var(--color-accent)] text-[var(--color-primary)]">
                    <Ban className="h-5 w-5" aria-hidden="true" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-sm font-semibold text-[var(--color-primary)]">
                      {enviando && bloquear === true ? "Salvando..." : "Bloquear permanentemente"}
                    </span>
                    <span className="mt-0.5 block text-xs text-[var(--color-muted-foreground)]">
                      Este médico nunca mais aparecerá nas suas recomendações, independentemente
                      do ciclo ou perfil prescritivo.
                    </span>
                  </span>
                </button>
              </div>
            </>
          )}

        </div>
        </>
        )}

        {passo !== "escolha" && passo !== "pronto" && (
        <div className="flex flex-shrink-0 gap-3 border-t border-[var(--color-border)] px-5 py-4">
          {passo === "confirmar" && (
            <>
              <button
                type="button"
                disabled={enviando}
                onClick={onFechar}
                className="flex-1 rounded-xl bg-[var(--color-secondary)] py-3 text-sm font-semibold disabled:opacity-50"
                style={{ color: CINZA_BOTAO }}
              >
                Cancelar
              </button>
              <button
                type="button"
                disabled={enviando}
                onClick={aceitar}
                className="flex-1 rounded-xl bg-[var(--color-primary)] py-3 text-sm font-semibold text-white disabled:opacity-50"
              >
                {enviando ? "Registrando..." : "Confirmar"}
              </button>
            </>
          )}

          {passo === "motivo" && (
            <>
              <button
                type="button"
                onClick={passoInicial === "motivo" ? onFechar : () => setPasso(passoInicial)}
                className={`flex-shrink-0 px-6 ${botaoSecundario}`}
              >
                Cancelar
              </button>
              <button
                type="button"
                disabled={!podeConfirmarMotivo}
                onClick={() => setPasso("bloqueio")}
                className="flex-1 rounded-xl border border-[var(--color-primary)] bg-[var(--color-card)] py-3 text-sm font-semibold text-[var(--color-primary)] disabled:opacity-40"
              >
                Confirmar
              </button>
            </>
          )}

          {passo === "bloqueio" && (
            <button
              type="button"
              disabled={enviando}
              onClick={() => setPasso("motivo")}
              className={`flex-1 ${botaoSecundario}`}
            >
              Voltar
            </button>
          )}

        </div>
        )}
      </div>
    </div>
  );
}
