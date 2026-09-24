import { useEffect, useState } from "react";
import { Eye, LogOut, Search } from "lucide-react";
import {
  ApiError,
  listarOpcoesAdmin,
  listarPropagandistasAdmin,
  type OpcoesAdminResponse,
  type PropagandistaAdmin,
} from "@/lib/api";
import type { VerComo } from "@/auth/sessao";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
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
      <header className="flex items-center justify-between gap-4 bg-[var(--color-primary)] px-4 py-3 text-white sm:px-6">
        <span className="font-semibold tracking-wide">Ped.AI</span>
        <Button variant="ghost" onClick={onSair} className="gap-2 text-white hover:bg-white/15">
          <LogOut className="size-4" />
          Sair
        </Button>
      </header>

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
  return (
    <div>
      <Label htmlFor={id}>{rotulo}</Label>
      <select
        id={id}
        value={valor}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1.5 h-11 w-full rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-input-background)] px-3 text-base outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]"
      >
        <option value="">Todas</option>
        {opcoes.map((opcao) => (
          <option key={opcao} value={opcao}>
            {opcao}
          </option>
        ))}
      </select>
    </div>
  );
}
