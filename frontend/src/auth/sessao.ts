/**
 * Sessão do propagandista no navegador.
 *
 * Guarda apenas o que a interface precisa exibir, mais o token. A senha não
 * passa por aqui: ela é usada uma vez no login e descartada.
 *
 * Usa sessionStorage, não localStorage: a sessão termina quando a aba fecha.
 * Quando o Entra ID entrar, esta camada é substituída pelo cache de token da
 * própria MSAL e este arquivo deixa de guardar identidade.
 *
 * A validade do token é guardada em `expiraEm` e conferida na leitura: sessão
 * vencida é descartada como se não existisse, e a pessoa volta ao login. O
 * complemento está em `lib/api.ts`, que trata o 401 do servidor: o relógio do
 * navegador pode estar errado, e o token pode ser invalidado antes do prazo.
 */

const CHAVE = "renovai.sessao";

/** Propagandista que um administrador escolheu visualizar. Fica na sessão
 *  para sobreviver ao recarregamento da página; a autorização continua sendo
 *  conferida no servidor a cada chamada. */
export interface VerComo {
  setor: string;
  nome: string | null;
}

export interface Sessao {
  email: string;
  nome: string | null;
  setor: string;
  /** Bearer token devolvido pelo login, enviado nas chamadas seguintes. */
  token?: string;
  /** Instante em que o token perde a validade, em milissegundos de época.
   *  O backend devolve `expira_em` como duração em segundos; a conversão
   *  para instante absoluto acontece no login. */
  expiraEm?: number;
  /** Preenchido só na sessão de conferência de um administrador. */
  verComo?: VerComo | null;
}

export function lerSessao(): Sessao | null {
  const bruto = sessionStorage.getItem(CHAVE);
  if (!bruto) return null;
  try {
    const dados = JSON.parse(bruto) as Sessao;
    if (!dados.email || !dados.setor) return null;
    // Sessão vencida não é sessão. Sem esta conferência a interface seguia
    // exibindo a pessoa como autenticada e toda chamada falhava em silêncio.
    if (dados.expiraEm !== undefined && Date.now() >= dados.expiraEm) {
      sessionStorage.removeItem(CHAVE);
      return null;
    }
    return dados;
  } catch {
    sessionStorage.removeItem(CHAVE);
    return null;
  }
}

export function gravarSessao(sessao: Sessao) {
  sessionStorage.setItem(CHAVE, JSON.stringify(sessao));
}

export function limparSessao() {
  sessionStorage.removeItem(CHAVE);
}
