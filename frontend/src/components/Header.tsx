import { Bell, Menu } from "lucide-react";

interface HeaderProps {
  onAbrirMenu: () => void;
}

export function Header({ onAbrirMenu }: HeaderProps) {
  return (
    <header className="flex items-center justify-between gap-3 border-b border-[var(--color-border)] bg-[var(--color-card)] px-4 py-3 sm:px-6">
      <div className="flex items-center gap-2">
        <span
          className="h-2 w-2 flex-shrink-0 rounded-full bg-[var(--color-primary)]"
          aria-hidden="true"
        />
        <span className="text-base font-bold text-[var(--color-foreground)]">
          PedAI
        </span>
        <span className="rounded-lg bg-[var(--color-accent)] px-2.5 py-1 text-[11px] font-bold tracking-wide text-[var(--color-primary)]">
          ACHÉ
        </span>
      </div>

      <div className="flex items-center gap-1">
        <button
          type="button"
          aria-label="Notificações"
          disabled
          className="flex h-9 w-9 items-center justify-center rounded-full text-[var(--color-muted-foreground)] disabled:opacity-100"
        >
          <Bell className="h-5 w-5" aria-hidden="true" />
        </button>

        <button
          type="button"
          onClick={onAbrirMenu}
          aria-label="Abrir menu"
          className="flex h-9 w-9 items-center justify-center rounded-full text-[var(--color-muted-foreground)] transition-colors hover:bg-[var(--color-muted)]"
        >
          <Menu className="h-5 w-5" aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}
