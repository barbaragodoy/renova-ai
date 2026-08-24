import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Superfície branca sobre o fundo da página.
 *
 *  Raio, borda e sombra vêm do protótipo `UserScreen` do Figma Make, lido em
 *  07/08/2026: `rounded-2xl` de 16px, e não o `--radius-lg` de 10px do tema, e
 *  `shadow-sm`. O tema traz o raio padrão do shadcn, que a designer sobrescreve
 *  no desenho da aba. */
export function Card({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] shadow-sm",
        className,
      )}
      {...props}
    />
  );
}

interface SecaoProps {
  titulo: string;
  children: ReactNode;
  className?: string;
}

/** Bloco com título curto acima do cartão.
 *
 *  O título é um `h2` de verdade, e não um parágrafo estilizado: a aba tem
 *  três seções e quem navega por leitor de tela precisa conseguir pular entre
 *  elas. */
export function Secao({ titulo, children, className }: SecaoProps) {
  return (
    <section className={className}>
      {/* Tipografia do protótipo: 10px, bold, tracking-widest. */}
      <h2 className="mb-2 px-1 text-[10px] font-bold tracking-widest text-[var(--color-muted-foreground)] uppercase">
        {titulo}
      </h2>
      {children}
    </section>
  );
}
