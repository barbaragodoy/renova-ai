import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Check, ChevronDown, Eye, LogOut, Search } from "lucide-react";
import {
  ApiError,
  listarOpcoesAdmin,
  listarPropagandistasAdmin,
  type OpcoesAdminResponse,
  type PropagandistaAdmin,
} from "@/lib/api";
import type { VerComo } from "@/auth/sessao";
import { Header } from "@/components/Header";
import { Alert } from "@/components/ui/alert";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface SeletorProps {
  /** Identidade real de quem entrou; vai só no modo de desenvolvimento. */
  email: string;
  onEscolher: (alvo: VerComo) => void;
  onSair: () => void;
}

/**
 * Tela do administrador: escolher qual propagandista visualizar.
 *
 * Aparece depois do login para quem está na lista administrativa, no lugar
 * das abas. A cascata (linha, regional, UF) e a busca por nome ou setor vêm
 * dos endpoints de `backend/app/auth/administrativo.py`. Escolhido o setor,
 * o cliente HTTP passa a mandar `X-Ver-Como` em toda chamada e o portal abre
 * como aquele propagandista, somente leitura.
 *
 * O alvo é o setor, não o e-mail, porque é o que o backend aceita no header:
 * setor é único por propagandista e opaco o bastante para trafegar em log.
 */
export function SeletorDePropagandista({ email, onEscolher, onSair }: SeletorProps) {
  const [opcoes, setOpcoes] = useState<OpcoesAdminResponse | null>(null);
  const [linha, setLinha] = useState("");
  const [regional, setRegional] = useState("");
  const [uf, setUf] = useState("");
  const [busca, setBusca] = useState("");
  const [itens, setItens] = useState<PropagandistaAdmin[]>([]);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    listarOpcoesAdmin(email)
      .then(setOpcoes)
      .catch((e) => setErro(e instanceof ApiError ? e.message : "Erro ao carregar as opções."));
  }, [email]);

  // A lista só é pedida quando há algum filtro: sem filtro seriam 2.146
  // nomes, e ninguém escolhe rolando uma lista desse tamanho no celular.
  const temFiltro = Boolean(linha || regional || uf || busca.trim());

  useEffect(() => {
    if (!temFiltro) {
      setItens([]);
      return;
    }
    const controle = { cancelado: false };
    // Pequeno atraso na busca por texto, para não disparar uma consulta ao
    // Databricks a cada letra digitada.
    const temporizador = setTimeout(() => {
      setCarregando(true);
      setErro(null);
      listarPropagandistasAdmin(email, { linha, regional, uf, busca: busca.trim() })
        .then((resposta) => {
          if (!controle.cancelado) setItens(resposta.itens);
        })
        .catch((e) => {
          if (!controle.cancelado) {
            setErro(e instanceof ApiError ? e.message : "Erro ao buscar propagandistas.");
          }
        })
        .finally(() => {
          if (!controle.cancelado) setCarregando(false);
        });
    }, 300);
    return () => {
      controle.cancelado = true;
      clearTimeout(temporizador);
    };
  }, [email, linha, regional, uf, busca, temFiltro]);

  return (
    <div className="grid h-dvh grid-rows-[auto_minmax(0,1fr)]">
      <Header
        acoes={
          <button
            type="button"
            onClick={onSair}
            className="flex h-9 items-center gap-2 rounded-full px-3 text-sm font-medium text-[var(--color-muted-foreground)] transition-colors hover:bg-[var(--color-muted)]"
          >
            <LogOut className="h-4 w-4" aria-hidden="true" />
            Sair
          </button>
        }
      />

      <main className="h-full min-h-0 overflow-y-auto bg-[var(--color-muted)] px-4 py-6 sm:px-6">
        <div className="mx-auto max-w-2xl space-y-4">
          <div>
            <h1 className="text-xl font-bold">Ver o portal como um propagandista</h1>
            <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">
              Acesso administrativo, somente leitura. Nenhuma ação feita nesta sessão é
              registrada em nome do propagandista.
            </p>
          </div>

          {erro && <Alert>{erro}</Alert>}

          <Card className="space-y-4 p-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <CampoSelecao
                id="linha"
                rotulo="Linha"
                valor={linha}
                opcoes={opcoes?.linhas ?? []}
                onChange={setLinha}
              />
              <CampoSelecao
                id="regional"
                rotulo="Regional"
                valor={regional}
                opcoes={opcoes?.regionais ?? []}
                onChange={setRegional}
              />
              <CampoSelecao
                id="uf"
                rotulo="UF"
                valor={uf}
                opcoes={opcoes?.ufs ?? []}
                onChange={setUf}
              />
            </div>

            <div>
              <Label htmlFor="busca">Nome ou setor</Label>
              <div className="relative mt-1.5">
                <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-[var(--color-muted-foreground)]" />
                <Input
                  id="busca"
                  value={busca}
                  onChange={(e) => setBusca(e.target.value)}
                  placeholder="Digite parte do nome ou o código do setor"
                  className="pl-9"
                  autoComplete="off"
                />
              </div>
            </div>
          </Card>

          {!temFiltro && (
            <p className="text-center text-sm text-[var(--color-muted-foreground)]">
              Escolha um filtro ou digite um nome para listar.
            </p>
          )}

          {temFiltro && carregando && itens.length === 0 && (
            <p className="text-center text-sm text-[var(--color-muted-foreground)]">Buscando...</p>
          )}

          {temFiltro && !carregando && itens.length === 0 && !erro && (
            <p className="text-center text-sm text-[var(--color-muted-foreground)]">
              Nenhum propagandista com esses filtros.
            </p>
          )}

          {itens.length > 0 && (
            <ul className="space-y-2">
              {itens.map((item) => (
                <li key={item.setor}>
                  <button
                    type="button"
                    onClick={() => onEscolher({ setor: item.setor, nome: item.nome ?? null })}
                    className="flex w-full items-center justify-between gap-3 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-card)] px-4 py-3 text-left transition-colors hover:border-[var(--color-primary)]"
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-medium">
                        {item.nome ?? "Sem nome"}
                      </span>
                      <span className="block truncate text-xs text-[var(--color-muted-foreground)]">
                        Setor {item.setor}
                        {item.linha ? ` · ${item.linha}` : ""}
                        {item.regional ? ` · ${item.regional}` : ""}
                        {item.uf ? ` · ${item.uf}` : ""}
                      </span>
                    </span>
                    <Eye className="size-4 shrink-0 text-[var(--color-primary)]" aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </main>
    </div>
  );
}

function CampoSelecao({
  id,
  rotulo,
  valor,
  opcoes,
  onChange,
}: {
  id: string;
  rotulo: string;
  valor: string;
  opcoes: string[];
  onChange: (valor: string) => void;
}) {
  const [aberto, setAberto] = useState(false);
  const [destaque, setDestaque] = useState(0);
  const raiz = useRef<HTMLDivElement>(null);
  const lista = useRef<HTMLUListElement>(null);
  const itens = ["", ...opcoes];
  const idLista = `${id}-opcoes`;

  useEffect(() => {
    if (!aberto) return;
    function tocarFora(evento: PointerEvent) {
      if (!raiz.current?.contains(evento.target as Node)) setAberto(false);
    }
    document.addEventListener("pointerdown", tocarFora);
    return () => document.removeEventListener("pointerdown", tocarFora);
  }, [aberto]);

  useEffect(() => {
    if (aberto) lista.current?.children[destaque]?.scrollIntoView({ block: "nearest" });
  }, [aberto, destaque]);

  function abrir() {
    setDestaque(Math.max(0, itens.indexOf(valor)));
    setAberto(true);
  }

  function escolher(indice: number) {
    onChange(itens[indice]);
    setAberto(false);
  }

  function teclar(evento: KeyboardEvent<HTMLButtonElement>) {
    switch (evento.key) {
      case "ArrowDown":
        evento.preventDefault();
        if (aberto) setDestaque((d) => Math.min(d + 1, itens.length - 1));
        else abrir();
        break;
      case "ArrowUp":
        evento.preventDefault();
        if (aberto) setDestaque((d) => Math.max(d - 1, 0));
        else abrir();
        break;
      case "Enter":
      case " ":
        if (aberto) {
          evento.preventDefault();
          escolher(destaque);
        }
        break;
      case "Escape":
        if (aberto) {
          evento.preventDefault();
          setAberto(false);
        }
        break;
      case "Tab":
        setAberto(false);
        break;
    }
  }

  return (
    <div ref={raiz} className="relative">
      <Label htmlFor={id}>{rotulo}</Label>
      <button
        id={id}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={aberto}
        aria-controls={idLista}
        aria-activedescendant={aberto ? `${idLista}-${destaque}` : undefined}
        onClick={() => (aberto ? setAberto(false) : abrir())}
        onKeyDown={teclar}
        className="mt-1.5 flex h-11 w-full items-center justify-between gap-2 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-input-background)] px-3 text-left text-base outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]"
      >
        <span className="truncate">{valor || "Todas"}</span>
        <ChevronDown
          className={`h-4 w-4 shrink-0 text-[var(--color-muted-foreground)] transition-transform ${aberto ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
      </button>

      {aberto && (
        <ul
          ref={lista}
          id={idLista}
          role="listbox"
          aria-label={rotulo}
          className="absolute top-full right-0 left-0 z-20 mt-1 max-h-64 overflow-y-auto rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-card)] py-1 shadow-lg"
        >
          {itens.map((item, indice) => {
            const selecionado = item === valor;
            return (
              <li
                key={item || "__todas"}
                id={`${idLista}-${indice}`}
                role="option"
                aria-selected={selecionado}
                onPointerDown={(evento) => evento.preventDefault()}
                onClick={() => escolher(indice)}
                onPointerEnter={() => setDestaque(indice)}
                className={`flex cursor-pointer items-center justify-between gap-2 px-3 py-2 text-sm ${
                  indice === destaque ? "bg-[var(--color-muted)]" : ""
                } ${selecionado ? "font-semibold text-[var(--color-primary)]" : ""}`}
              >
                <span className="truncate">{item || "Todas"}</span>
                {selecionado && <Check className="h-4 w-4 shrink-0" aria-hidden="true" />}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
