import { useEffect, useState } from "react";
import { Camera, Pencil, UserCircle } from "lucide-react";
import {
  ApiError,
  enviarFotoPerfil,
  obterPerfil,
  salvarNomePerfil,
  urlFotoPerfil,
  type PerfilResponse,
} from "@/lib/api";
import { Alert } from "@/components/ui/alert";
import { Card, Secao } from "@/components/ui/card";
import { PontinhosDeCarregamento } from "@/components/ui/loading";

/**
 * Aba Usuário do Ped.AI.
 *
 * Espelha o protótipo `UserScreen` do Figma Make `cuZGbZpvR0aBJhixqBnYYB`,
 * lido em 07/08/2026. A estrutura é a de lá: cartão de identificação com
 * avatar, nome, cargo e selo de status; seção Resumo com quatro cards em duas
 * colunas; seção Informações com nove campos em lista dividida.
 *
 * Uma versão anterior desta tela acrescentou campos que não existem no
 * protótipo (nome repetido, login, gerente regional, gerente nacional, cidade
 * e estado em campos separados) e um card de última atualização. Foram
 * retirados por instrução de George em 07/08/2026: a tela tinha informação
 * demais e o layout tinha se afastado do desenho.
 *
 * Três pontos em que o conteúdo não segue o protótipo ao pé da letra, e todos
 * vêm de decisão posterior a ele:
 *
 * 1. `Código do colaborador` virou `Matrícula`, nomenclatura confirmada com
 *    Caio no petit comitê de 06/08/2026.
 * 2. `Cidade / Estado` mostra as três cidades principais mais a UF, e não uma
 *    cidade única. A planilha oficial de bricks de 06/08/2026 mostrou que
 *    1.650 dos 2.238 setores têm mais de uma cidade, com máximo de 93, então
 *    cidade única mostraria informação errada.
 * 3. `Status da conta` é derivado da existência de setor, decisão de George em
 *    05/08/2026, e não lido de coluna. Na prática é sempre `Ativo`, porque
 *    quem não tem setor não entra na `tb_propagandistas`.
 *
 * A foto do protótipo não foi trazida. O botão de câmera aparece desabilitado
 * porque não há onde guardar o arquivo: a permissão de criar UC Volume em
 * `acheinfo_dev.renovai` não existe (grants verificados em 07/08/2026). Um
 * upload que se perde ao recarregar a página é pior que nenhum upload.
 */

const NAO_DISPONIVEL = "Não disponível";

/** Cores do protótipo que ainda não têm token no design system do portal.
 *
 *  O rosa e o rosa claro já existem como `--color-primary` e `--color-accent`,
 *  então saem daqui de propósito. Estas quatro entram cruas porque é assim que
 *  o Figma Make as define, e inventar token novo aqui divergiria do arquivo
 *  que a designer está migrando para o Figma Design. */
const ROXO_AVATAR = "#4B3B8C";
const FUNDO_AVATAR = "#EDE8F5";
const VERDE_FUNDO = "#ECFDF5";
const VERDE_TEXTO = "#16A34A";

const LIMITE_EXIBIDO = 3;

interface UsuarioProps {
  email: string;
}

/** Três primeiros itens da lista, com o resto resumido em contagem.
 *
 *  Decisão de George em 06/08/2026. As listas já chegam ordenadas por número
 *  de médicos decrescente, então as três primeiras são as que mais importam.
 *  A média é de 8,4 cidades e 18,2 especialidades por setor: sem corte, os
 *  setores ficam visualmente idênticos e o campo perde poder de informar. */
function resumir(itens: string[]): string | null {
  if (itens.length === 0) return null;
  const visiveis = itens.slice(0, LIMITE_EXIBIDO).join(" · ");
  const restantes = itens.length - LIMITE_EXIBIDO;
  return restantes > 0 ? `${visiveis} +${restantes}` : visiveis;
}

/** Data do acesso anterior no formato do dia a dia.
 *
 *  Nulo é primeiro acesso: a tela mostra o acesso ANTERIOR, nunca o em curso,
 *  que apareceria sempre como "agora". */
function formatarAcesso(valor?: string | null): string | null {
  if (!valor) return null;
  const data = new Date(valor);
  if (Number.isNaN(data.getTime())) return null;
  return data.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "CLINICA GERAL" vira "Clinica Geral". A origem grava em maiúsculas e sem
 *  acento; a tela não tenta devolver o acento, porque adivinhar erraria em
 *  parte dos nomes. */
function capitalizarEspecialidade(valor: string): string {
  return valor
    .toLowerCase()
    .split(" ")
    .map((parte) => (parte ? parte[0].toUpperCase() + parte.slice(1) : parte))
    .join(" ");
}

function numero(valor?: number | null): string | null {
  return valor === null || valor === undefined ? null : String(valor);
}

function Indicador({ rotulo, valor }: { rotulo: string; valor?: string | null }) {
  const vazio = !valor;
  return (
    <Card className="flex flex-col gap-1 p-4">
      <p className="text-[10px] leading-tight font-semibold tracking-wider text-[var(--color-muted-foreground)] uppercase">
        {rotulo}
      </p>
      <p
        className={
          vazio
            ? "text-sm text-[var(--color-muted-foreground)] italic"
            : "text-sm leading-snug font-bold text-[var(--color-foreground)]"
        }
      >
        {vazio ? NAO_DISPONIVEL : valor}
      </p>
    </Card>
  );
}

function Campo({
  rotulo,
  valor,
  destaque,
}: {
  rotulo: string;
  valor?: string | null;
  /** Usado só no status da conta, que o protótipo pinta de verde. */
  destaque?: boolean;
}) {
  const vazio = !valor;
  return (
    <div className="flex items-start justify-between gap-3 px-4 py-3.5">
      <p className="shrink-0 text-xs text-[var(--color-muted-foreground)]">
        {rotulo}
      </p>
      <p
        className={
          vazio
            ? "text-right text-xs text-[var(--color-muted-foreground)] italic"
            : "text-right text-xs font-semibold text-[var(--color-foreground)]"
        }
        style={destaque && !vazio ? { color: VERDE_TEXTO } : undefined}
      >
        {vazio ? NAO_DISPONIVEL : valor}
      </p>
    </div>
  );
}

function UsuarioEsqueleto() {
  return (
    <div className="space-y-4 px-4 py-5 pb-8" aria-hidden="true">
      <PontinhosDeCarregamento texto="Carregando seu perfil" />

      <Card className="p-5">
        <div className="flex flex-col items-center space-y-3">
          <div className="h-20 w-20 rounded-full skeleton-shimmer" />
          <div className="flex flex-col items-center gap-2">
            <div className="h-4 w-32 rounded-sm skeleton-shimmer" />
            <div className="h-3 w-20 rounded-sm skeleton-shimmer" />
          </div>
          <div className="h-5 w-16 rounded-full skeleton-shimmer" />
        </div>
        <div className="mt-4 border-t border-[var(--color-border)] pt-4">
          <div className="h-10 w-full rounded-xl skeleton-shimmer" />
        </div>
      </Card>

      <div className="space-y-2">
        <div className="h-3 w-20 rounded-sm skeleton-shimmer" />
        <div className="grid grid-cols-2 gap-3">
          {[0, 1, 2, 3].map((i) => (
            <Card key={i} className="flex flex-col gap-2 p-4">
              <div className="h-2.5 w-3/4 rounded-sm skeleton-shimmer" />
              <div className="h-4 w-1/2 rounded-sm skeleton-shimmer" />
            </Card>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <div className="h-3 w-24 rounded-sm skeleton-shimmer" />
        <Card className="divide-y divide-[var(--color-border)]">
          {[0, 1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
            <div key={i} className="flex items-center justify-between gap-3 px-4 py-3.5">
              <div className="h-2.5 w-1/3 rounded-sm skeleton-shimmer" />
              <div className="h-2.5 w-1/4 rounded-sm skeleton-shimmer" />
            </div>
          ))}
        </Card>
      </div>
    </div>
  );
}

export function Usuario({ email }: UsuarioProps) {
  const [perfil, setPerfil] = useState<PerfilResponse | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [editando, setEditando] = useState(false);
  const [rascunho, setRascunho] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [erroEdicao, setErroEdicao] = useState<string | null>(null);
  // Incrementado a cada troca de foto para forçar o <img> a recarregar. Sem
  // isso o navegador serviria a imagem antiga do cache, mesma URL.
  const [versaoFoto, setVersaoFoto] = useState(0);
  const [erroFoto, setErroFoto] = useState<string | null>(null);
  const [enviandoFoto, setEnviandoFoto] = useState(false);
  const [fotoQuebrada, setFotoQuebrada] = useState(false);

  useEffect(() => {
    let ativo = true;

    setCarregando(true);
    setErro(null);

    obterPerfil(email)
      .then((dados) => {
        if (ativo) setPerfil(dados);
      })
      .catch((excecao) => {
        if (!ativo) return;
        setErro(
          excecao instanceof ApiError
            ? excecao.message
            : "Não foi possível carregar o perfil. Tente novamente.",
        );
      })
      .finally(() => {
        if (ativo) setCarregando(false);
      });

    return () => {
      ativo = false;
    };
  }, [email]);

  if (carregando) {
    return <UsuarioEsqueleto />;
  }

  // A lista vazia não deveria chegar aqui: o backend responde 404 quando não
  // encontra linha. A guarda existe para uma mudança futura de contrato não
  // virar tela branca no celular de quem está em campo.
  if (erro || !perfil || perfil.atribuicoes.length === 0) {
    return (
      <div className="px-4 py-8">
        <Alert>{erro ?? "Perfil indisponível."}</Alert>
      </div>
    );
  }

  const primeira = perfil.atribuicoes[0];
  const setores = perfil.atribuicoes.map((a) => a.setor).join(" · ");

  // Item 1.4: com setor, `Ativo`. A `tb_propagandistas` só contém quem tem
  // setor, então na prática o outro estado não chega a aparecer.
  const status = primeira.setor ? "Ativo" : "Sem setor";

  const cidades = resumir(perfil.cidades);
  const cidadeEstado =
    cidades && perfil.uf ? `${cidades} · ${perfil.uf}` : (cidades ?? perfil.uf);

  function abrirEdicao() {
    setRascunho(perfil!.nome);
    setErroEdicao(null);
    setEditando(true);
  }

  // `null` desfaz a edição e devolve o nome da SIMV. Apagar o campo e salvar
  // tem o mesmo efeito, porque o backend normaliza vazio para nulo.
  function salvar(nome: string | null) {
    setSalvando(true);
    setErroEdicao(null);

    salvarNomePerfil(email, nome)
      .then((atualizado) => {
        setPerfil(atualizado);
        setEditando(false);
      })
      .catch((excecao) => {
        setErroEdicao(
          excecao instanceof ApiError
            ? excecao.message
            : "Não foi possível salvar o nome. Tente novamente.",
        );
      })
      .finally(() => setSalvando(false));
  }

  function trocarFoto(arquivo: File | undefined) {
    if (!arquivo) return;
    setEnviandoFoto(true);
    setErroFoto(null);

    enviarFotoPerfil(email, arquivo)
      .then(() => {
        setVersaoFoto((v) => v + 1);
        setFotoQuebrada(false);
        // Recarrega o perfil para foto_path refletir o novo estado; sem isso
        // o avatar continuaria caindo no ícone padrão até o próximo acesso.
        return obterPerfil(email).then(setPerfil);
      })
      .catch((excecao) => {
        setErroFoto(
          excecao instanceof ApiError
            ? excecao.message
            : "Não foi possível enviar a foto. Tente novamente.",
        );
      })
      .finally(() => setEnviandoFoto(false));
  }

  return (
    <div className="space-y-4 px-4 py-5 pb-8">
      {/* Identificação ---------------------------------------------------- */}
      <Card className="p-5">
        <div className="flex flex-col items-center space-y-3">
          <div className="relative">
            <div
              className="flex h-20 w-20 items-center justify-center overflow-hidden rounded-full border-2"
              style={
                editando
                  ? {
                      borderColor: "var(--color-primary)",
                      background: "var(--color-accent)",
                    }
                  : { borderColor: FUNDO_AVATAR, background: FUNDO_AVATAR }
              }
            >
              {perfil.foto_path && !fotoQuebrada ? (
                <img
                  src={urlFotoPerfil(email, versaoFoto)}
                  alt="Foto de perfil"
                  className="h-full w-full rounded-full object-cover"
                  onError={() => setFotoQuebrada(true)}
                />
              ) : (
                <UserCircle
                  className="h-10 w-10"
                  style={{
                    color: editando ? "var(--color-primary)" : ROXO_AVATAR,
                  }}
                />
              )}
            </div>

            {editando && (
              <label
                title="Trocar a foto"
                className={
                  "absolute -right-1 -bottom-1 flex h-7 w-7 cursor-pointer items-center justify-center rounded-full text-white shadow" +
                  (enviandoFoto ? " opacity-40" : "")
                }
                style={{ background: "var(--color-primary)" }}
              >
                <Camera className="h-3.5 w-3.5" aria-hidden="true" />
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  disabled={enviandoFoto}
                  onChange={(e) => trocarFoto(e.target.files?.[0])}
                  aria-label="Trocar a foto de perfil"
                  className="hidden"
                />
              </label>
            )}
          </div>

          {erroFoto && (
            <p className="text-xs text-[var(--color-destructive)]">{erroFoto}</p>
          )}

          {editando ? (
            <input
              value={rascunho}
              onChange={(evento) => setRascunho(evento.target.value)}
              // Mesmo limite do backend, para o corte aparecer enquanto a
              // pessoa digita e não só depois de salvar.
              maxLength={60}
              autoFocus
              disabled={salvando}
              aria-label="Nome exibido"
              className="w-full max-w-[220px] rounded-xl border border-transparent bg-[var(--color-muted)] px-3 py-2 text-center text-base font-bold text-[var(--color-foreground)] outline-none focus:border-[var(--color-primary)]"
            />
          ) : (
            <div className="text-center">
              <p className="text-base font-bold text-[var(--color-foreground)]">
                {perfil.nome}
              </p>
              <p className="mt-0.5 text-xs text-[var(--color-muted-foreground)]">
                {perfil.cargo ?? NAO_DISPONIVEL}
              </p>
            </div>
          )}

          <span
            className="rounded-full px-3 py-1 text-[11px] font-semibold"
            style={{ background: VERDE_FUNDO, color: VERDE_TEXTO }}
          >
            ● {status}
          </span>
        </div>

        <div className="mt-4 border-t border-[var(--color-border)] pt-4">
          {editando ? (
            <>
              {erroEdicao && (
                <div className="mb-3">
                  <Alert>{erroEdicao}</Alert>
                </div>
              )}

              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setEditando(false)}
                  disabled={salvando}
                  className="flex-1 rounded-xl bg-[var(--color-muted)] py-2.5 text-sm font-medium text-[var(--color-muted-foreground)]"
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  onClick={() => salvar(rascunho)}
                  disabled={salvando}
                  className="flex-1 rounded-xl py-2.5 text-sm font-bold text-white"
                  style={{ background: "var(--color-primary)" }}
                >
                  {salvando ? "Salvando..." : "Salvar"}
                </button>
              </div>

              <p className="mt-2 text-center text-[11px] text-[var(--color-muted-foreground)]">
                Nesta versão apenas nome e foto podem ser editados.
              </p>
            </>
          ) : (
            <button
              type="button"
              onClick={abrirEdicao}
              className="flex w-full items-center justify-center gap-2 rounded-xl border-2 bg-white py-2.5 text-sm font-semibold transition-colors active:opacity-80"
              style={{
                borderColor: "var(--color-primary)",
                color: "var(--color-primary)",
              }}
            >
              <Pencil className="h-4 w-4" />
              Editar informações
            </button>
          )}
        </div>
      </Card>

      {/* Resumo ----------------------------------------------------------- */}
      <Secao titulo="Resumo">
        <div className="grid grid-cols-2 gap-3">
          <Indicador
            rotulo={
              perfil.atribuicoes.length > 1 ? "Setores atendidos" : "Setor atendido"
            }
            valor={setores}
          />
          {/* As duas especialidades com mais médicos visitados em doze meses,
              nome e regra do protótipo. Substituiu "Especialidades da linha"
              em 18/09/2026; as franquias da linha desceram para o campo
              "Linha de produtos" em Informações. */}
          <Indicador
            rotulo="Especialidades predominantes"
            valor={
              perfil.especialidades_predominantes
                .map(capitalizarEspecialidade)
                .join(" · ") || null
            }
          />
          <Indicador
            rotulo="Médicos no painel"
            valor={numero(perfil.medicos_no_painel)}
          />
          <Indicador
            rotulo="Recomendações pendentes"
            valor={numero(perfil.recomendacoes_pendentes)}
          />
        </div>
      </Secao>

      {/* Informações ------------------------------------------------------ */}
      <Secao titulo="Informações">
        <Card className="divide-y divide-[var(--color-border)]">
          <Campo rotulo="Cargo" valor={perfil.cargo} />
          <Campo rotulo="Regional" valor={perfil.regional} />
          <Campo rotulo="Cidade / Estado" valor={cidadeEstado} />
          {/* As franquias da linha, como no protótipo ("Cardiovascular &
              Endocrinologia"), e não o nome ou o número da linha. Decisão de
              George em 18/09/2026. */}
          <Campo
            rotulo="Linha de produtos"
            valor={perfil.franquias_linha.join(" · ") || perfil.linha_nome}
          />
          <Campo rotulo="Supervisor" valor={primeira.gd_nome} />
          <Campo rotulo="Matrícula" valor={perfil.matricula} />
          <Campo rotulo="E-mail corporativo" valor={perfil.email} />
          <Campo
            rotulo="Último acesso"
            valor={formatarAcesso(perfil.dt_acesso_anterior)}
          />
          <Campo rotulo="Status da conta" valor={status} destaque />
        </Card>
      </Secao>
    </div>
  );
}
