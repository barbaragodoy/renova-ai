export function PontinhosDeCarregamento({ texto }: { texto: string }) {
  return (
    <div className="flex items-center justify-center gap-1 px-1" role="status" aria-label={texto}>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-2 w-2 animate-dot-wave rounded-sm bg-[var(--color-primary)]"
          style={{ animationDelay: `${i * 0.2}s` }}
        />
      ))}
    </div>
  );
}
