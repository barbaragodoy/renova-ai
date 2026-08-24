import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface AlertProps {
  children: ReactNode;
  variant?: "erro" | "aviso";
  className?: string;
}

/** Mensagem de erro ou aviso. Usa role="alert" para que leitores de tela
 *  anunciem o conteúdo assim que ele aparece. */
export function Alert({ children, variant = "erro", className }: AlertProps) {
  return (
    <div
      role="alert"
      className={cn(
        "rounded-[var(--radius-md)] border px-3.5 py-3 text-sm",
        variant === "erro"
          ? "border-[var(--color-destructive)]/30 bg-[var(--color-destructive)]/8 text-[var(--color-destructive)]"
          : "border-[var(--color-primary)]/25 bg-[var(--color-accent)] text-[var(--color-accent-foreground)]",
        className,
      )}
    >
      {children}
    </div>
  );
}
