import { useState } from "react";
import { X } from "lucide-react";
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
  onFechar: () => void;
  onResolvida: (statusNovo: string | null) => void;
}) {
  type Passo = "escolha" | "motivo" | "bloqueio" | "pronto";
  const [passo, setPasso] = useState<Passo>("escolha");
  const [motivo, setMotivo] = useState<MotivoDesconsideracao | null>(null);
  const [textoOutros, setTextoOutros] = useState("");
  const [bloquear, setBloquear] = useState<boolean | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [mensagemFinal, setMensagemFinal] = useState("");
  const id = idRecomendacao;
  const efeitoDoAceite =
    EFEITO_DO_ACEITE[tipoRecomendacao ?? ""] ?? EFEITO_DO_ACEITE_PADRAO;

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
  const podeConfirmarMotivo =
    motivo !== null && (motivo !== "OUTROS" || textoOutros.trim() !== "");

  function aceitar() {
    setEnviando(true);
    setErro(null);
    aceitarRecomendacao(id)
      .then(() => {
        setMensagemFinal(efeitoDoAceite);
        setPasso("pronto");
        onResolvida("ACEITA");
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
    motivo: "Desconsiderar sugestão",
    bloqueio: "Bloquear médico?",
    pronto: "Pronto",
  }[passo];

  return (
    <div
      className="fixed inset-0 z-[60] flex items-end"
      style={{ background: "rgba(0,0,0,0.45)" }}
      onClick={onFechar}
    >
      <div
        className="flex max-h-[92vh] w-full flex-col rounded-t-3xl bg-[var(--color-card)]"
        onClick={(evento) => evento.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={titulo}
      >
        <div className="flex flex-shrink-0 items-start justify-between gap-3 px-5 pb-3 pt-4">
          <div className="min-w-0">
            <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--color-primary)]">
              {titulo}
            </p>
            <p className="truncate text-sm font-semibold text-[var(--color-foreground)]">
              {nome}
            </p>
          </div>
          <button
            type="button"
            onClick={onFechar}
            aria-label="Fechar"
            className="flex-shrink-0 p-1 text-[var(--color-muted-foreground)]"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-5 pb-6">
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
                    className="w-full rounded-[var(--radius-md)] bg-[var(--color-primary)] py-3 text-sm font-semibold text-white disabled:opacity-50"
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
                    className="w-full rounded-[var(--radius-md)] bg-[var(--color-muted)] py-3 text-sm font-semibold text-[var(--color-muted-foreground)] disabled:opacity-50"
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

          {passo === "motivo" && (
            <>
              <p className="text-xs font-semibold text-[var(--color-muted-foreground)]">
                Por que deseja desconsiderar?
              </p>
              <div className="space-y-2">
                {MOTIVOS_DESCONSIDERACAO.map((codigo) => (
                  <button
                    key={codigo}
                    type="button"
                    onClick={() => setMotivo(codigo)}
                    aria-pressed={motivo === codigo}
                    className="w-full rounded-[var(--radius-md)] border px-4 py-3 text-left text-sm"
                    style={
                      motivo === codigo
                        ? { borderColor: "var(--color-primary)", background: "var(--color-accent)" }
                        : { borderColor: "var(--color-border)" }
                    }
                  >
                    {ROTULO_MOTIVO[codigo]}
                  </button>
                ))}
              </div>

              {motivo === "OUTROS" && (
                <textarea
                  value={textoOutros}
                  onChange={(e) => setTextoOutros(e.target.value.slice(0, 300))}
                  maxLength={300}
                  placeholder="Descreva rapidamente o motivo."
                  aria-label="Descreva rapidamente o motivo"
                  className="w-full resize-none rounded-[var(--radius-md)] border border-[var(--color-border)] px-3 py-2 text-sm outline-none"
                  rows={3}
                />
              )}

              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setPasso("escolha")}
                  className="flex-1 rounded-[var(--radius-md)] border border-[var(--color-border)] py-3 text-sm font-semibold text-[var(--color-muted-foreground)]"
                >
                  Voltar
                </button>
                <button
                  type="button"
                  disabled={!podeConfirmarMotivo}
                  onClick={() => setPasso("bloqueio")}
                  className="flex-1 rounded-[var(--radius-md)] bg-[var(--color-primary)] py-3 text-sm font-semibold text-white disabled:opacity-50"
                >
                  Confirmar
                </button>
              </div>
            </>
          )}

          {passo === "bloqueio" && (
            <>
              <p className="text-xs font-semibold text-[var(--color-muted-foreground)]">
                O que você deseja fazer com este médico?
              </p>

              <div className="space-y-3">
                <div>
                  <button
                    type="button"
                    disabled={enviando}
                    onClick={() => {
                      setBloquear(true);
                      confirmarDesconsideracao(true);
                    }}
                    className="w-full rounded-[var(--radius-md)] bg-[var(--color-primary)] py-3 text-sm font-semibold text-white disabled:opacity-50"
                  >
                    {enviando && bloquear === true ? "Salvando..." : "Bloquear permanentemente"}
                  </button>
                  <p className="mt-1.5 text-xs text-[var(--color-muted-foreground)]">
                    Este médico nunca mais aparecerá nas suas recomendações, independentemente
                    do ciclo ou perfil prescritivo.
                  </p>
                </div>

                <div>
                  <button
                    type="button"
                    disabled={enviando}
                    onClick={() => {
                      setBloquear(false);
                      confirmarDesconsideracao(false);
                    }}
                    className="w-full rounded-[var(--radius-md)] border border-[var(--color-border)] bg-white py-3 text-sm font-semibold text-[var(--color-foreground)] disabled:opacity-50"
                  >
                    {enviando && bloquear === false ? "Salvando..." : "Apenas desconsiderar"}
                  </button>
                  <p className="mt-1.5 text-xs text-[var(--color-muted-foreground)]">
                    Este médico não aparecerá nas suas recomendações neste ciclo. Se o perfil
                    continuar elegível, poderá reaparecer futuramente.
                  </p>
                </div>
              </div>

              <button
                type="button"
                onClick={() => setPasso("motivo")}
                className="w-full rounded-[var(--radius-md)] border border-[var(--color-border)] py-3 text-sm font-semibold text-[var(--color-muted-foreground)]"
              >
                Voltar
              </button>
            </>
          )}

          {passo === "pronto" && (
            <>
              <p className="text-sm leading-relaxed text-[var(--color-foreground)]">
                {mensagemFinal}
              </p>
              <button
                type="button"
                onClick={onFechar}
                className="w-full rounded-[var(--radius-md)] bg-[var(--color-primary)] py-3 text-sm font-semibold text-white"
              >
                Fechar
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
