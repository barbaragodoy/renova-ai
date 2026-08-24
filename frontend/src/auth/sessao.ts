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
 * Pendente antes de produção: a expiração do token não é guardada aqui, então
 * a interface continua exibindo o usuário como autenticado depois dos 60
 * minutos. Falta guardar a validade, limpar a sessão ao receber 401 e devolver
 * a pessoa ao login com um aviso.
 */

const CHAVE = "renovai.sessao";

export interface Sessao {
  email: string;
  nome: string | null;
  setor: string;
  /** Bearer token devolvido pelo login, enviado nas chamadas seguintes. */
  token?: string;
}

export function lerSessao(): Sessao | null {
  const bruto = sessionStorage.getItem(CHAVE);
  if (!bruto) return null;
  try {
    const dados = JSON.parse(bruto) as Sessao;
    return dados.email && dados.setor ? dados : null;
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
