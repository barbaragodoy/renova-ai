import { LogOut, X, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export interface ItemDeMenu {
  id: string;
  rotulo: string;
  icone: LucideIcon;
}

interface MenuLateralProps {
  aberto: boolean;
  itens: readonly ItemDeMenu[];
  abaAtiva: string;
  onSelecionar: (id: string) => void;
  onFechar: () => void;
  onSair: () => void;
}

export function MenuLateral({
  aberto,
  itens,
  abaAtiva,
  onSelecionar,
  onFechar,
  onSair,
}: MenuLateralProps) {
  if (!aberto) return null;

  return (
    <div
      className="fixed inset-0 z-50"
      role="dialog"
      aria-modal="true"
      aria-label="Menu de navegação"
    >
      <div
        className="absolute inset-0 bg-black/45"
        onClick={onFechar}
        aria-hidden="true"
      />

      <nav className="relative flex h-full w-64 max-w-[80vw] flex-col bg-[var(--color-card)] shadow-xl">
        <div className="flex items-center justify-between gap-2 px-5 py-4">
          <div className="flex items-center gap-2">
            <span
              className="h-2 w-2 flex-shrink-0 rounded-full bg-[var(--color-primary)]"
              aria-hidden="true"
            />
            <span className="text-base font-bold text-[var(--color-foreground)]">
              PedAI
            </span>
          </div>
          <button
            type="button"
            onClick={onFechar}
            aria-label="Fechar menu"
            className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full text-[var(--color-muted-foreground)] transition-colors hover:bg-[var(--color-muted)]"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        <div className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
          {itens.map(({ id, rotulo, icone: Icone }) => {
            const ativo = id === abaAtiva;
            return (
              <button
                key={id}
                type="button"
                onClick={() => onSelecionar(id)}
                aria-current={ativo ? "page" : undefined}
                className={cn(
                  "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm font-semibold transition-colors",
                  ativo
                    ? "bg-[var(--color-primary)] text-white"
                    : "text-[var(--color-muted-foreground)] hover:bg-[var(--color-muted)]",
                )}
              >
                <Icone className="h-5 w-5 flex-shrink-0" aria-hidden="true" />
                {rotulo}
              </button>
            );
          })}
        </div>

        <div className="flex-shrink-0 border-t border-[var(--color-border)] px-3 py-3">
          <button
            type="button"
            onClick={onSair}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm font-semibold text-[var(--color-muted-foreground)] transition-colors hover:bg-[var(--color-muted)]"
          >
            <LogOut className="h-5 w-5 flex-shrink-0" aria-hidden="true" />
            Sair
          </button>
        </div>
      </nav>
    </div>
  );
}
