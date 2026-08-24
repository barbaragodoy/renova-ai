import type { InputHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function Input({
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-11 w-full rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-input-background)] px-3.5",
        "text-base text-[var(--color-foreground)] placeholder:text-[var(--color-muted-foreground)]",
        "outline-none transition-shadow",
        "focus-visible:border-transparent focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]",
        "disabled:opacity-60",
        "aria-[invalid=true]:border-[var(--color-destructive)]",
        className,
      )}
      {...props}
    />
  );
}
