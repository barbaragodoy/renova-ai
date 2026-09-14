import { type MemoriaDeVisitas } from "@/lib/api";

/** Rótulos da classificação automática do momento da relação. O vocabulário
 *  fechado vem do backend; valor desconhecido simplesmente não exibe selo. */
const MOMENTOS_DA_RELACAO: Record<string, { rotulo: string; classe: string }> = {
  primeira_visita: { rotulo: "Primeira visita", classe: "bg-[var(--color-accent)] text-[var(--color-accent-foreground)]" },
  conquista: { rotulo: "Em conquista", classe: "bg-[var(--color-accent)] text-[var(--color-accent-foreground)]" },
  defensor: { rotulo: "Defensor", classe: "bg-[var(--color-primary)] text-[var(--color-primary-foreground)]" },
  risco_de_perda: { rotulo: "Risco de perda", classe: "bg-[var(--color-destructive)] text-[var(--color-destructive-foreground)]" },
  indefinido: { rotulo: "A classificar", classe: "bg-[var(--color-muted)] text-[var(--color-muted-foreground)]" },
};

/** A Memória de Visitas, no lugar do antigo "Como Tratar".
 *
 *  A última visita vem primeiro, crua e com data, porque é o que o
 *  propagandista pediu para lembrar. O resumo por dimensão vem depois, cada
 *  item com a data de origem. O selo do momento da relação é classificação
 *  automática e se declara como tal. Nome provisório até a definição com o
 *  design; trocar o título é trocar uma string.
 *
 *  `resumido` é a versão da gaveta de detalhes do Ranking: só o item mais
 *  recente de cada dimensão, comentário da última visita limitado a três
 *  linhas e sem o parágrafo de justificativa, que continua acessível no
 *  `title` do selo. O chat usa a versão completa. */
export function CardMemoriaDeVisitas({ memoria, perfilTexto, resumido = false }: {
  memoria: MemoriaDeVisitas;
  perfilTexto?: string;
  resumido?: boolean;
}) {
  const selo = memoria.momento_da_relacao
    ? MOMENTOS_DA_RELACAO[memoria.momento_da_relacao.classificacao]
    : undefined;

  const dimensoes: { titulo: string; itens: { data: string; texto: string }[] }[] = [
    { titulo: "Voz do médico", itens: memoria.voz_do_medico ?? [] },
    { titulo: "Momento clínico", itens: memoria.momento_clinico ?? [] },
    { titulo: "Toque pessoal", itens: memoria.toque_pessoal ?? [] },
  ]
    .map((d) => (resumido ? { ...d, itens: d.itens.slice(0, 1) } : d))
    .filter((d) => d.itens.length > 0);

  return (
    <div className="space-y-3 rounded-xl border border-[var(--color-border)] bg-white p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-muted-foreground)]">
          Memória de visitas
        </p>
        {selo && (
          <span
            className={`rounded-full px-2.5 py-0.5 text-[10px] font-semibold ${selo.classe}`}
            title={memoria.momento_da_relacao?.justificativa || "Classificação automática pelas últimas observações"}
          >
            {selo.rotulo}
          </span>
        )}
      </div>

      {memoria.ultima && memoria.ultima.comentario && (
        <div>
          <p className="text-[10px] uppercase tracking-wide text-[var(--color-muted-foreground)]">
            Última visita{memoria.ultima.data ? ` — ${memoria.ultima.data}` : ""}
            {memoria.ultima.tipo ? ` (${memoria.ultima.tipo.toLowerCase()})` : ""}
          </p>
          <p className={resumido ? "mt-1 line-clamp-3 text-sm" : "mt-1 text-sm"}>
            {memoria.ultima.comentario}
          </p>
        </div>
      )}

      {!resumido && memoria.momento_da_relacao?.justificativa && (
        <p className="text-xs text-[var(--color-muted-foreground)]">
          {memoria.momento_da_relacao.justificativa}
        </p>
      )}

      {dimensoes.map((d) => (
        <div key={d.titulo}>
          <p className="text-[10px] uppercase tracking-wide text-[var(--color-muted-foreground)]">
            {d.titulo}
          </p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
            {d.itens.map((item, i) => (
              <li key={i} className={resumido ? "line-clamp-2" : undefined}>
                {item.data ? `${item.data}: ` : ""}
                {item.texto}
              </li>
            ))}
          </ul>
        </div>
      ))}

      {perfilTexto && (
        <p className="border-t border-[var(--color-border)] pt-2 text-xs text-[var(--color-muted-foreground)]">
          Perfil de comunicação: {perfilTexto}
        </p>
      )}
    </div>
  );
}
