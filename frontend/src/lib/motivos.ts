import { type MotivoDesconsideracao } from "@/lib/api";

/**
 * Rótulos dos motivos de desconsideração.
 *
 * Mora fora das telas porque duas precisam dele: a aba Recomendações, que
 * oferece a lista e exibe o histórico, e a gaveta de ação do Ranking. Duplicar
 * significaria as duas telas divergirem no dia em que um rótulo mudasse.
 */

/** Rótulo em português de cada motivo fixo de desconsideração — espelha
 *  MOTIVOS_DESCONSIDERACAO em lib/api.ts / backend/app/schemas/recomendacoes.py. */
export const ROTULO_MOTIVO: Record<MotivoDesconsideracao, string> = {
  SEM_PERFIL_PARA_O_PAINEL: "Já avaliei e o médico não tem perfil para o meu ranking",
  TRABALHADO_POR_OUTRO_CANAL: "Médico já é trabalhado por outro canal ou colega",
  AGUARDAR_PROXIMO_CICLO: "Vou aguardar o próximo ciclo para decidir",
  DADOS_DESATUALIZADOS: "Dados do médico parecem desatualizados",
  FORA_DO_PLANEJAMENTO: "Não atende ao meu planejamento atual do setor",
  OUTROS: "Outro motivo",
};

/** Códigos aceitos até 04/09/2026, quando a lista virou a do protótipo. Não
 *  são mais oferecidos, mas as linhas já gravadas os guardam: sem esta
 *  tradução a aba Arquivadas mostraria o código cru para quem desconsiderou
 *  antes da troca.
 *
 *  Mapa separado de propósito. Juntar os dois num `Record<string, string>`
 *  faria o TypeScript parar de exigir rótulo para motivo novo, e um motivo
 *  acrescentado à lista sem rótulo apareceria como botão vazio. Achado da
 *  revisão independente de 04/09/2026. */
export const ROTULO_MOTIVO_HISTORICO: Record<string, string> = {
  MEDICO_NAO_ATUA_MAIS: "Médico não atua mais",
  MEDICO_APOSENTADO: "Médico aposentado",
  MEDICO_FALECIDO: "Médico falecido",
  SEM_INTERESSE_COMERCIAL: "Sem interesse comercial",
};

export const ROTULOS_DE_MOTIVO: Record<string, string> = {
  ...ROTULO_MOTIVO,
  ...ROTULO_MOTIVO_HISTORICO,
};

/** O backend formata o motivo "OUTROS" como "OUTROS: <texto informado>"
 *  (ver _formatar_motivo_desconsideracao em routers/recomendacoes.py) — já
 *  vem legível, só tira o prefixo. Os demais motivos são os códigos fixos
 *  de MOTIVOS_DESCONSIDERACAO, traduzidos via ROTULO_MOTIVO. */
export function rotuloMotivoDesconsideracao(bruto: string): string {
  if (bruto.startsWith("OUTROS:")) return bruto.replace(/^OUTROS:\s*/, "").trim();
  return ROTULOS_DE_MOTIVO[bruto] ?? bruto;
}
