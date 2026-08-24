/**
 * Cliente HTTP do Portal RenovAI.
 *
 * Os caminhos são relativos porque, na imagem única do container, o React é
 * servido pelo próprio FastAPI. Em desenvolvimento o proxy do Vite encaminha
 * para o backend local (ver vite.config.ts).
 *
 * Os contratos abaixo seguem o OpenAPI publicado em
 * https://asp-renoveai-hmg.azurewebsites.net/openapi.json
 */

const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

/** Provedor do Bearer token, alimentado pela sessão ativa. Ao ligar o Entra
 *  ID, é aqui que a origem do token muda. */
let obterToken: () => string | null = () => null;

export function configurarProvedorDeToken(provedor: () => string | null) {
  obterToken = provedor;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(caminho: string, init: RequestInit = {}): Promise<T> {
  const token = obterToken();
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let resposta: Response;
  try {
    resposta = await fetch(`${BASE}${caminho}`, { ...init, headers });
  } catch {
    throw new ApiError(
      "Não foi possível falar com o servidor. Verifique sua conexão.",
      0,
    );
  }

  if (!resposta.ok) {
    // O FastAPI devolve o erro em `detail`, que pode ser texto ou lista de
    // erros de validação do Pydantic.
    let detalhe = `Erro ${resposta.status} ao consultar o servidor.`;
    try {
      const corpo = await resposta.json();
      if (typeof corpo?.detail === "string") detalhe = corpo.detail;
    } catch {
      /* resposta sem corpo JSON: mantém a mensagem padrão */
    }
    throw new ApiError(detalhe, resposta.status);
  }

  return (await resposta.json()) as T;
}

/* ---------------------------------------------------------------- contexto */

export type StatusContexto =
  | "SETOR_RESOLVIDO"
  | "PROPAGANDISTA_NAO_ENCONTRADO"
  | "IDENTIDADE_AMBIGUA";

export interface ContextoResponse {
  status: StatusContexto;
  matricula?: string | null;
  setor?: string | null;
  nome?: string | null;
  mensagem?: string | null;
}

/**
 * Resolve matrícula, setor e nome do propagandista.
 *
 * Em DEV/HMG (`AUTH_REQUIRE_JWT=false`) o e-mail vai por query string. Em
 * produção o backend passa a extrair o e-mail do Bearer token do Entra ID e
 * ignora este parâmetro, sem alteração de contrato.
 */
export function obterContexto(email: string) {
  const query = email ? `?email=${encodeURIComponent(email)}` : "";
  return request<ContextoResponse>(`/auth/contexto${query}`);
}

/* --------------------------------------------------------------- sessão */

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expira_em: number;
  nome?: string | null;
  setor: string;
}

/**
 * Login do portal: e-mail corporativo e senha.
 *
 * Atende `POST /auth/login` de `backend/app/auth/sessao.py`, ativo enquanto
 * `AUTH_MODE=senha`. Com o Entra ID, o backend responde 404 aqui e a
 * interface passa a usar o fluxo de redirecionamento.
 *
 * Diferente de `/auth/contexto`, este endpoint devolve 401 quando a
 * credencial não confere, então o erro chega como ApiError.
 */
export function login(email: string, senha: string) {
  return request<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, senha }),
  });
}

/* ---------------------------------------------------------------- perfil */

/** Uma linha de `tb_propagandistas`: o setor e a cadeia de gestão dele.
 *
 *  A cadeia mora na atribuição, e não no perfil, porque um propagandista que
 *  cobre dois setores pode responder a gerentes distritais diferentes em cada
 *  um. */
export interface AtribuicaoSetor {
  setor: string;
  /** Código numérico da linha na origem ("4", "5", "6"), não o nome
   *  terapêutico. O de-para para nome não existe em fonte confirmada. */
  linha_produto?: string | null;
  gd_nome?: string | null;
  gd_email?: string | null;
  gr_nome?: string | null;
  gn_nome?: string | null;
}

export interface PerfilResponse {
  matricula: string;
  /** Valor final exibido: o nome editado quando existe, o nome de guerra da
   *  SIMV quando não existe. Nunca é o nome completo de cadastro, que não
   *  tem fonte. */
  nome: string;
  /** Diz de qual das duas fontes `nome` veio. Só quem editou vê a opção de
   *  voltar ao nome original. */
  nome_editado: boolean;
  email: string;
  login?: string | null;
  /** Caminho da foto. Sempre nulo enquanto o armazenamento não for definido. */
  foto_path?: string | null;

  /* Bloco 3 da aba. Todos saem da mesma linha de `tb_propagandistas`. */
  cargo?: string | null;
  regional?: string | null;
  /** Um setor pode cobrir mais de uma UF; a base guarda apenas uma. */
  uf?: string | null;
  /** Nome da linha ("LINHA 4"), não o código numérico. */
  linha_nome?: string | null;

  /** Listas completas, ordenadas por número de médicos decrescente. A tela
   *  corta nas três primeiras; o resto fica para o "veja mais". */
  cidades: string[];
  especialidades: string[];

  /** Penúltimo login, em ISO. O acesso em curso não entra, senão mostraria
   *  sempre "agora". Nulo no primeiro acesso. */
  dt_acesso_anterior?: string | null;

  /** Cards 2.3 e 2.5. Somados quando a pessoa atende mais de um setor. */
  medicos_no_painel?: number | null;
  recomendacoes_pendentes?: number | null;

  atribuicoes: AtribuicaoSetor[];
}

/**
 * Perfil do propagandista para a aba Usuário.
 *
 * Devolve 404 quando o e-mail não tem cadastro, então o erro chega como
 * ApiError e não como resposta de status, diferente de `/auth/contexto`.
 */
export function obterPerfil(email: string) {
  const query = email ? `?email=${encodeURIComponent(email)}` : "";
  return request<PerfilResponse>(`/auth/perfil${query}`);
}

/**
 * Grava o nome de exibição e devolve o perfil já atualizado.
 *
 * Enviar `null` desfaz a edição: o backend limpa a coluna e a leitura volta
 * sozinha para o nome da SIMV. Não existe rota de exclusão separada.
 *
 * A resposta é o perfil inteiro, e não só o nome, para a tela não precisar de
 * uma segunda chamada depois de salvar.
 */
export function salvarNomePerfil(email: string, nome: string | null) {
  const query = email ? `?email=${encodeURIComponent(email)}` : "";
  return request<PerfilResponse>(`/auth/perfil${query}`, {
    method: "PUT",
    body: JSON.stringify({ nome }),
  });
}

/* -------------------------------------------------------------- recomendações */

/** Uma linha pendente da `tb_recomendacoes_painel_historico` no ciclo vigente.
 *
 *  Os nomes seguem o contrato dos endpoints; no backend cada campo é um alias
 *  da coluna real da tabela. `motivo_revisao` só vem na lista de revisão e
 *  carrega o código do motivo, que a tela traduz para texto. */
export interface RecomendacaoItem {
  id_recomendacao: string;
  nome_medico: string;
  ufcrm: string;
  posicao_ranking?: number | null;
  soma_pontuacao?: number | null;
  ciclo_referencia: string;
  motivo_revisao?: string | null;
  /** Via LEFT JOIN com tb_dim_medicos, só existe no Databricks (ver
   *  known-issues.md). Vazios para médicos fora da janela de 08/06/2026 —
   *  a fonte do espelho está parada desde então, não é erro da tela. */
  especialidade?: string | null;
  cidade?: string | null;
  /** Calculado como LEFT(ufcrm, 2) no backend, funciona nas duas fontes. */
  uf?: string | null;
  /** Só populado quando a recomendação é REVISAO_PAINEL — sem sentido
   *  semântico para ENTRADA_PAINEL (médico que nunca esteve no painel não
   *  ter visita não é sinal de negligência). */
  meses_sem_visita?: number | null;
}

export interface ListaRecomendacoesResponse {
  tipo: "ENTRADA_PAINEL" | "REVISAO_PAINEL";
  total: number;
  /** Lista completa, já ordenada pelo backend: entrada por maior pontuação,
   *  revisão por maior posição no ranking. Limitada a `LIMITE_SUGESTOES`
   *  (5 hoje) pelo próprio backend. */
  recomendacoes: RecomendacaoItem[];
}

export function listarEntrada(email: string) {
  const query = email ? `?email=${encodeURIComponent(email)}` : "";
  return request<ListaRecomendacoesResponse>(`/recomendacoes/entrada${query}`);
}

export function listarRevisao(email: string) {
  const query = email ? `?email=${encodeURIComponent(email)}` : "";
  return request<ListaRecomendacoesResponse>(`/recomendacoes/revisao${query}`);
}

/** Lista fixa de motivos de desconsideração — espelha
 *  MOTIVOS_DESCONSIDERACAO em backend/app/schemas/recomendacoes.py.
 *  "OUTROS" exige motivo_outros_texto; os demais não aceitam texto livre. */
export const MOTIVOS_DESCONSIDERACAO = [
  "MEDICO_NAO_ATUA_MAIS",
  "MEDICO_APOSENTADO",
  "MEDICO_FALECIDO",
  "SEM_INTERESSE_COMERCIAL",
  "OUTROS",
] as const;

export type MotivoDesconsideracao = (typeof MOTIVOS_DESCONSIDERACAO)[number];

export interface DesconsiderarRequest {
  motivo: MotivoDesconsideracao;
  motivo_outros_texto?: string | null;
  bloquear_novas_recomendacoes: boolean;
}

export interface DesconsiderarResponse {
  success: boolean;
  message: string;
  id_recomendacao: string;
  status_recomendacao: string;
  data_desconsideracao: string;
}

/**
 * Desconsidera uma recomendação.
 *
 * Atende `POST /recomendacoes/{id}/desconsiderar` — identidade vem
 * exclusivamente da sessão (Bearer token), sem parâmetro de e-mail, diferente
 * dos demais endpoints desta seção.
 */
export function desconsiderar(idRecomendacao: string, body: DesconsiderarRequest) {
  return request<DesconsiderarResponse>(`/recomendacoes/${idRecomendacao}/desconsiderar`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Uma recomendação desconsiderada, para a aba Arquivadas. */
export interface DesconsideradaItem {
  id_recomendacao: string;
  nome_medico?: string | null;
  ufcrm: string;
  tipo_recomendacao: "ENTRADA_PAINEL" | "REVISAO_PAINEL";
  /** Motivo original da recomendação, não o motivo da desconsideração. */
  motivo_recomendacao?: string | null;
  motivo_desconsideracao: string;
  /** Optional no backend (Optional[bool] em DesconsideradaItem, ver
   *  schemas/recomendacoes.py): registros legados anteriores à
   *  obrigatoriedade deste campo no contrato de POST /desconsiderar têm
   *  esse valor NULL no banco. */
  bloquear_novas_recomendacoes: boolean | null;
  data_desconsideracao: string;
  ciclo_recomendacao: string;
  especialidade?: string | null;
  cidade?: string | null;
  uf?: string | null;
  meses_sem_visita?: number | null;
}

export interface ListaDesconsideradasResponse {
  total: number;
  recomendacoes: DesconsideradaItem[];
}

/**
 * Lista o histórico de recomendações desconsideradas do propagandista.
 *
 * Atende `GET /recomendacoes/desconsideradas` — sem LIMIT, diferente de
 * `/entrada` e `/revisao`: devolve o histórico completo, não uma sugestão
 * priorizada.
 */
export function listarDesconsideradas(email: string) {
  const query = email ? `?email=${encodeURIComponent(email)}` : "";
  return request<ListaDesconsideradasResponse>(`/recomendacoes/desconsideradas${query}`);
}

export interface ReverterResponse {
  success: boolean;
  message: string;
  id_recomendacao: string;
  status_recomendacao: string;
}

/**
 * Reverte uma recomendação desconsiderada.
 *
 * Atende `POST /recomendacoes/{id}/reverter` — sem corpo. O novo status já
 * vem pronto na resposta: `PENDENTE` se o ciclo da recomendação ainda é o
 * vigente, `EXPIRADA` se já é de um ciclo anterior.
 */
export function reverter(idRecomendacao: string) {
  return request<ReverterResponse>(`/recomendacoes/${idRecomendacao}/reverter`, {
    method: "POST",
  });
}
