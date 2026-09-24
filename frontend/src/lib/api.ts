/**
 * Cliente HTTP do Ped.AI.
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

/** Avisa a aplicação de que a sessão morreu, para ela devolver a pessoa ao
 *  login. Fica aqui, e não em cada chamada, porque qualquer rota de negócio
 *  pode ser a primeira a receber o 401 depois dos 60 minutos. */
let aoExpirar: () => void = () => {};

export function configurarAoExpirarSessao(callback: () => void) {
  aoExpirar = callback;
}

/** Em AUTH_MODE=entra_id não há Bearer token — a autoridade é o cookie do
 *  Easy Auth, que o navegador manda sozinho. Sem isto, um 401 depois do
 *  cookie expirar (sessão viva, mas vencida no meio do uso) não tinha como
 *  se distinguir de um 401 na primeira consulta anônima de `/auth/contexto`
 *  (essa é tratada dentro de `resolverEntrada()`, antes de chegar aqui, e
 *  não deve soar como "sessão expirou" para quem nunca teve sessão). App.tsx
 *  alimenta isto com `!USA_SENHA && sessaoAtual !== null`. */
let sessaoEntraIdAtiva: () => boolean = () => false;

export function configurarSessaoEntraIdAtiva(provedor: () => boolean) {
  sessaoEntraIdAtiva = provedor;
}

/** Setor que um administrador escolheu visualizar. Vai no header
 *  `X-Ver-Como` de toda chamada; o backend troca a identidade efetiva pela
 *  do propagandista daquele setor e recusa qualquer escrita enquanto o header
 *  estiver presente (ver `backend/app/auth/administrativo.py`). Quem não
 *  está na lista administrativa manda o header e é ignorado. */
let setorVerComo: string | null = null;

export function configurarVerComo(setor: string | null) {
  setorVerComo = setor;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    /** Código estruturado do erro (ex.: "ACESSO_BLOQUEADO"), quando o
     *  backend devolve `detail` como objeto `{codigo, detail}` em vez de
     *  string — ver `backend/app/auth/status_acesso.py`. Detecção por
     *  código, não por texto da mensagem, que pode mudar. */
    readonly codigo?: string,
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
  if (setorVerComo) headers.set("X-Ver-Como", setorVerComo);

  let resposta: Response;
  try {
    resposta = await fetch(`${BASE}${caminho}`, { ...init, headers });
  } catch {
    throw new ApiError(
      "Não foi possível falar com o servidor. Verifique sua conexão.",
      0,
    );
  }

  // 401 numa chamada que levou token (modo senha) ou numa chamada feita com
  // sessão entra_id já ativa é sessão vencida ou revogada, e não credencial
  // errada: o login por senha não manda token, e a consulta inicial de
  // /auth/contexto em entra_id (antes de qualquer sessão existir) não conta
  // como "ativa" — então nenhuma das duas cai aqui indevidamente.
  if (resposta.status === 401 && (token || sessaoEntraIdAtiva())) {
    aoExpirar();
    throw new ApiError("Sua sessão expirou. Entre novamente.", 401);
  }

  if (!resposta.ok) {
    // O FastAPI devolve o erro em `detail`, que pode ser texto, lista de
    // erros de validação do Pydantic, ou objeto estruturado `{codigo,
    // detail}` — formato padronizado de auth/status_acesso.py para
    // ACESSO_BLOQUEADO, único hoje que usa esse formato.
    let detalhe = `Erro ${resposta.status} ao consultar o servidor.`;
    let codigo: string | undefined;
    try {
      const corpo = await resposta.json();
      if (typeof corpo?.detail === "string") {
        detalhe = corpo.detail;
      } else if (corpo?.detail && typeof corpo.detail === "object") {
        if (typeof corpo.detail.detail === "string") detalhe = corpo.detail.detail;
        if (typeof corpo.detail.codigo === "string") codigo = corpo.detail.codigo;
      }
    } catch {
      /* resposta sem corpo JSON: mantém a mensagem padrão */
    }
    throw new ApiError(detalhe, resposta.status, codigo);
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
  /** E-mail corporativo real (tb_propagandistas.rep_email). Único jeito da
   *  interface aprender o e-mail de quem entrou no modo entra_id, que não
   *  tem formulário — ver backend/app/auth/context.py e src/auth/entraId.ts. */
  email?: string | null;
}

/**
 * Resolve matrícula, setor e nome do propagandista.
 *
 * Em DEV/HMG (`AUTH_REQUIRE_JWT=false`) o e-mail vai por query string. Em
 * `AUTH_MODE=entra_id` o backend ignora este parâmetro e extrai a identidade
 * dos headers do Easy Auth (`X-MS-CLIENT-PRINCIPAL-NAME`) — por isso `email`
 * é opcional aqui: `src/auth/entraId.ts` chama sem argumento nenhum, a
 * identidade nunca é conhecida no cliente antes desta resposta.
 */
export function obterContexto(email?: string) {
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

/* --------------------------------------------------------- administrativo */

export interface SessaoAdminResponse {
  administrador: boolean;
  identidade: string;
  vendo_setor?: string | null;
}

export interface OpcoesAdminResponse {
  linhas: string[];
  regionais: string[];
  ufs: string[];
}

export interface PropagandistaAdmin {
  setor: string;
  nome?: string | null;
  linha?: string | null;
  regional?: string | null;
  uf?: string | null;
  cidades?: string | null;
}

export interface ListaPropagandistasAdmin {
  total: number;
  itens: PropagandistaAdmin[];
}

/** Diz se quem entrou pode abrir o portal no lugar de um propagandista. Não é
 *  decisão de segurança, que fica no servidor a cada chamada; só evita
 *  desenhar um seletor que a pessoa não pode usar. */
/**
 * `email` é opcional pelo mesmo motivo de `obterContexto`: em
 * `AUTH_MODE=entra_id` o parâmetro é ignorado, a identidade vem dos headers
 * do Easy Auth. `src/auth/entraId.ts` chama sem argumento — é o único jeito
 * de confirmar se uma conta corporativa sem propagandista vinculado é
 * administradora, antes de existir qualquer `Sessao`.
 */
export function obterSessaoAdmin(email?: string) {
  const query = email ? `?email=${encodeURIComponent(email)}` : "";
  return request<SessaoAdminResponse>(`/admin/sessao${query}`);
}

export function listarOpcoesAdmin(email: string) {
  const query = email ? `?email=${encodeURIComponent(email)}` : "";
  return request<OpcoesAdminResponse>(`/admin/opcoes${query}`);
}

export function listarPropagandistasAdmin(
  email: string,
  filtros: { linha?: string; regional?: string; uf?: string; busca?: string },
) {
  const params = new URLSearchParams();
  if (email) params.set("email", email);
  for (const [chave, valor] of Object.entries(filtros)) {
    if (valor) params.set(chave, valor);
  }
  return request<ListaPropagandistasAdmin>(`/admin/propagandistas?${params.toString()}`);
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

  /** "Status da conta" (bloco 1) — "ATIVO" ou "BLOQUEADO", de
   *  tb_perfil_portal.STATUS_ACESSO. `null`/ausente quando não há linha:
   *  tratar como bloqueado, mesmo critério deny-by-default do backend. */
  status_acesso?: string | null;

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

  /** Franquias da linha de produtos, por extenso. Resolvido no backend a
   *  partir de LINHA_PRODUTO; a tela só exibe. */
  franquias_linha: string[];

  /** Penúltimo login, em ISO. O acesso em curso não entra, senão mostraria
   *  sempre "agora". Nulo no primeiro acesso. */
  dt_acesso_anterior?: string | null;

  /** Cards 2.3 e 2.5. Somados quando a pessoa atende mais de um setor. */
  medicos_no_painel?: number | null;
  recomendacoes_pendentes?: number | null;

  /** Limite do painel em vigor, único para todos, lido de
   *  tb_renovai_parametros. A edição por propagandista saiu em 18/09/2026
   *  quando a aba foi alinhada ao protótipo; a tela não exibe mais o valor. */
  limite_painel: number;

  /** As duas especialidades com mais médicos distintos visitados nos últimos
   *  doze meses, somando os setores da pessoa. Vazio quando não há visita no
   *  período ou quando a consulta de resumo falhou; a tela mostra não
   *  disponível. Campo "Especialidades predominantes" do protótipo. */
  especialidades_predominantes: string[];

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

/**
 * Envia ou troca a foto de perfil.
 *
 * Vai como multipart, não como JSON com base64: base64 cresce o corpo em um
 * terço e obriga o servidor a decodificar antes de saber o tamanho.
 *
 * Não passa por `request()` porque aquele helper fixa Content-Type JSON; aqui
 * o navegador precisa montar o boundary do multipart sozinho.
 */
export async function enviarFotoPerfil(email: string, arquivo: File) {
  const query = email ? `?email=${encodeURIComponent(email)}` : "";
  const corpo = new FormData();
  corpo.append("arquivo", arquivo);

  const token = obterToken();
  const resposta = await fetch(`${BASE}/auth/perfil/foto${query}`, {
    method: "PUT",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: corpo,
  });

  // Esta chamada não passa por `request` porque envia FormData, e definir
  // Content-Type na mão quebraria o boundary do multipart. O tratamento de
  // sessão vencida precisa ser repetido aqui, senão o upload seria a única
  // rota de negócio que falha sem devolver a pessoa ao login. Achado da
  // revisão independente de 03/09/2026.
  if (resposta.status === 401 && token) {
    aoExpirar();
    throw new ApiError("Sua sessão expirou. Entre novamente.", 401);
  }

  if (!resposta.ok) {
    const detalhe = await resposta.json().catch(() => null);
    throw new ApiError(
      detalhe?.detail ?? "Não foi possível enviar a foto.",
      resposta.status,
    );
  }
  return (await resposta.json()) as { foto_path: string };
}

/** URL da foto da pessoa autenticada. O `v` quebra o cache do navegador
 *  depois de uma troca: sem ele o <img> continuaria mostrando a anterior. */
export function urlFotoPerfil(email: string, versao: number) {
  const sep = email ? `?email=${encodeURIComponent(email)}&` : "?";
  return `${BASE}/auth/perfil/foto${sep}v=${versao}`;
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
  /** Quantas pendências existem no ciclo, e não quantas vieram nesta página. */
  total: number;
  /** Uma página, já ordenada pelo backend: entrada da melhor para a pior
   *  posição no ranking, exclusão da pior para a melhor. Até 04/09/2026 a
   *  lista era cortada em 5 e o resto ficava invisível. */
  recomendacoes: RecomendacaoItem[];
  /** Quantas ficam destacadas como prioridade da semana. Vem do backend para
   *  a regra viver num lugar só. */
  destaques: number;
}

const RECOMENDACOES_POR_PAGINA = 50;

function queryDaLista(email: string, offset: number) {
  const partes = [];
  if (email) partes.push(`email=${encodeURIComponent(email)}`);
  if (offset) partes.push(`offset=${offset}`);
  return partes.length ? `?${partes.join("&")}` : "";
}

export function listarEntrada(email: string, offset = 0) {
  return request<ListaRecomendacoesResponse>(
    `/recomendacoes/entrada${queryDaLista(email, offset)}`,
  );
}

export function listarRevisao(email: string, offset = 0) {
  return request<ListaRecomendacoesResponse>(
    `/recomendacoes/revisao${queryDaLista(email, offset)}`,
  );
}

export { RECOMENDACOES_POR_PAGINA };

/** Lista fixa de motivos de desconsideração — espelha
 *  MOTIVOS_DESCONSIDERACAO em backend/app/schemas/recomendacoes.py.
 *  "OUTROS" exige motivo_outros_texto; os demais não aceitam texto livre.
 *
 *  Vocabulário do protótipo do Figma Make, adotado por decisão de George em
 *  04/09/2026: fala da decisão de quem desconsidera, e não de um fato
 *  cadastral do médico. */
export const MOTIVOS_DESCONSIDERACAO = [
  "SEM_PERFIL_PARA_O_PAINEL",
  "TRABALHADO_POR_OUTRO_CANAL",
  "AGUARDAR_PROXIMO_CICLO",
  "DADOS_DESATUALIZADOS",
  "FORA_DO_PLANEJAMENTO",
  "OUTROS",
] as const;

export type MotivoDesconsideracao = (typeof MOTIVOS_DESCONSIDERACAO)[number];

/** Códigos aceitos até 04/09/2026. Não são mais oferecidos, mas as linhas já
 *  gravadas os guardam, e a aba Arquivadas precisa exibi-los em português. */
export const MOTIVOS_DESCONSIDERACAO_HISTORICOS = [
  "MEDICO_NAO_ATUA_MAIS",
  "MEDICO_APOSENTADO",
  "MEDICO_FALECIDO",
  "SEM_INTERESSE_COMERCIAL",
] as const;

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

export interface AceitarResponse {
  success: boolean;
  message: string;
  id_recomendacao: string;
  status_recomendacao: string;
  data_aceite: string;
}

/**
 * Aceita uma recomendação.
 *
 * Atende `POST /recomendacoes/{id}/aceitar`. Sem corpo: aceitar não tem
 * parâmetro. **Isto grava intenção, não fato:** quem confirma que o médico
 * entrou ou saiu do painel continua sendo o job diário que compara contra o
 * painel real. Por isso a tela nunca diz que o médico já está no painel.
 */
export function aceitarRecomendacao(idRecomendacao: string) {
  return request<AceitarResponse>(`/recomendacoes/${idRecomendacao}/aceitar`, {
    method: "POST",
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
  /** Nulo quando a decisão foi aceite. */
  motivo_desconsideracao?: string | null;
  /** Optional no backend (Optional[bool] em DesconsideradaItem, ver
   *  schemas/recomendacoes.py): registros legados anteriores à
   *  obrigatoriedade deste campo no contrato de POST /desconsiderar têm
   *  esse valor NULL no banco. */
  bloquear_novas_recomendacoes: boolean | null;
  /** Qual foi a decisão: `DESCONSIDERADA` ou `ACEITA`. A aba Histórico passou
   *  a mostrar as duas em 04/09/2026. */
  status_recomendacao?: string | null;
  /** Data da decisão, seja ela qual for. Aceita não tem
   *  `data_desconsideracao`. */
  data_decisao?: string | null;
  /** Quando o aceite foi enviado ao SalesFarma; nulo até a exportação existir. */
  data_exportacao?: string | null;
  /** Se o botão Desfazer aparece. Regra do backend: desconsiderada sempre;
   *  aceita só antes do envio ao SalesFarma. */
  pode_desfazer?: boolean;
  /** Nulo quando a decisão foi aceite. */
  data_desconsideracao?: string | null;
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

/* ---------------------------------------------------------------- ranking */

export interface MedicoRanking {
  posicao: number;
  nome_medico: string;
  ufcrm: string;
  pontos?: number | null;
  no_painel: boolean;
  /** Última visita registrada, para o card de busca da Home. */
  data_ultima_visita?: string | null;
  especialidade?: string | null;
  cidade?: string | null;
  uf?: string | null;
  /** Recomendação pendente deste médico, quando existe. Nulo significa que
   *  não há o que aceitar nem o que desconsiderar, e a lista não oferece ação.
   *  Sai da tabela de recomendações, e não da classificação do ranking: as
   *  duas divergem quando a recomendação já foi resolvida ou expirou. */
  id_recomendacao_pendente?: string | null;
  tipo_recomendacao_pendente?: "ENTRADA_PAINEL" | "REVISAO_PAINEL" | null;
  /** Estado da recomendação deste médico no ciclo, mesmo já resolvida. É o que
   *  permite a linha mostrar o que o propagandista decidiu, em vez de voltar
   *  ao selo de painel como se nada tivesse acontecido. */
  status_recomendacao?: string | null;
}

export interface ListaRankingResponse {
  ciclo: string;
  /** Última carga do histórico de recomendações, para a coluna "Atualizado"
   *  do cabeçalho. Nulo quando o backend não conseguiu ler. */
  atualizado_em?: string | null;
  total_medicos: number;
  pontos_lider?: number | null;
  qtd_painel_setor?: number | null;
  offset: number;
  limite: number;
  medicos: MedicoRanking[];
}

export interface CategoriaPrescrita {
  nome: string;
  pct?: number | null;
}

export interface OpcaoProduto {
  nome: string;
  categoria?: string | null;
}

export interface ConcorrenteMercado {
  produto: string;
  laboratorio?: string | null;
  participacao?: string | null;
  eh_ache: boolean;
}

/** Documento da KB já em campos. O backend interpreta o markdown e descarta
 *  cabeçalho, referência dos dados e nota metodológica: nada disso ajuda quem
 *  está na porta do consultório. */
export interface MercadoDetalhe {
  mercado: string;
  area_terapeutica?: string | null;
  concorrentes: ConcorrenteMercado[];
  especialidades: string[];
  usos: string[];
  efeito?: string | null;

  /** Da estratégia de ciclo, material aprovado da Aché. Separado dos campos
   *  acima: aqueles descrevem o mercado observado na auditoria, incluindo
   *  concorrente, e estes descrevem o produto Aché. */
  indicacao?: string | null;
  beneficio_clinico?: string | null;
  perfil_paciente?: string | null;
  beneficios: string[];
  vantagens: string[];
  ciclos_origem: number[];
}

export interface EnderecoAtendimento {
  /** `salesfarma`, `auditoria` ou `cnes`. Decide a etiqueta do card. */
  fonte: "salesfarma" | "auditoria" | "cnes" | string;
  local?: string | null;
  logradouro?: string | null;
  /** Só o CNES separa número e complemento; no SalesFarma vêm no logradouro. */
  numero?: string | null;
  complemento?: string | null;
  bairro?: string | null;
  cidade?: string | null;
  uf?: string | null;
  cep?: string | null;
  telefone?: string | null;
  /** Só quando `fonte` é `propagandista`: quem corrigiu e quando. */
  registrado_por?: string | null;
  registrado_em?: string | null;
}

export interface EnderecoCorrecao {
  logradouro: string;
  numero?: string | null;
  complemento?: string | null;
  bairro?: string | null;
  cidade: string;
  uf: string;
  cep?: string | null;
  observacao?: string | null;
}

export interface DetalheMedicoResponse {
  nome_medico: string;
  ufcrm: string;
  especialidade?: string | null;
  cidade?: string | null;
  uf?: string | null;
  posicao?: number | null;
  pontos?: number | null;
  pontos_lider?: number | null;
  no_painel: boolean;
  qtd_painel_setor?: number | null;
  data_ultima_visita?: string | null;
  meses_sem_visita?: number | null;
  ciclos_no_painel_janela?: number | null;
  /** Está no painel há toda a janela de ciclos, hoje 3, e nunca foi visitado.
   *  Nulo quando o médico não está no ranking do ciclo. */
  nunca_visitado_na_janela?: boolean | null;
  /** Endereço 1, o da visita: SalesFarma, ou auditoria quando não há. */
  enderecos: EnderecoAtendimento[];
  /** Endereço 2, "também atende em", do CNES. Zero ou um item. */
  outros_locais: EnderecoAtendimento[];
  /** Endereço 1 e 2 em cidades diferentes: o card pede para conferir. */
  endereco_divergente: boolean;

  /** Segmentação do médico. `perfil_origem` diz de onde veio: propagandista,
   *  salesfarma ou a definir. */
  perfil_comunicacao?: string | null;
  perfil_origem?: string | null;

  /** Registro de conduta, o "Como Trata". Nulo quando ninguém registrou nada
   *  daquele médico neste setor. */
  conduta_texto?: string | null;
  conduta_em?: string | null;
  conduta_por?: string | null;
  recomendacao: string;
  criterio_saida?: string | null;
  janela?: string | null;
  categorias: CategoriaPrescrita[];
  produtos: string[];
  pct_ache?: number | null;
  produto_recomendado?: string | null;
  produto_recomendado_categoria?: string | null;
  rec_e_top1: boolean;
  ja_prescreve_o_produto: boolean;
  opcoes_produto: OpcaoProduto[];
}

/** Lista paginada do ranking do setor. `q` busca por nome no warehouse. */
export function listarRanking(email: string, q?: string, offset = 0) {
  const partes = [`offset=${offset}`];
  if (email) partes.push(`email=${encodeURIComponent(email)}`);
  if (q) partes.push(`q=${encodeURIComponent(q)}`);
  return request<ListaRankingResponse>(`/ranking?${partes.join("&")}`);
}

export function detalharMedico(email: string, ufcrm: string) {
  const query = email ? `?email=${encodeURIComponent(email)}` : "";
  return request<DetalheMedicoResponse>(`/ranking/medico/${encodeURIComponent(ufcrm)}${query}`);
}

/* ------------------------------------------------------------------ chat */

/** O canal só encaminha `FORA_DO_ESCOPO` para o motor de linguagem natural.
 *  Os demais já trazem a mensagem escrita, pronta para exibir. */
export type StatusChat =
  | "PERFIL_PRONTO"
  | "PRECISA_SETOR"
  | "MEDICO_AMBIGUO"
  | "MEDICO_NAO_ENCONTRADO"
  | "NAO_IMPLEMENTADO"
  | "FORA_DO_ESCOPO"
  | "RESPOSTA_DO_AGENTE"
  | "SAUDACAO";

/** Os quatro tipos do contrato `Message` do protótipo. */
export interface CardChat {
  type: "doctor" | "insight" | "suggestions" | "info-banner";
  name?: string | null;
  /** Já vem formatado como "#336 no setor". */
  rank?: string | null;
  /** Pontuação em valor bruto, decisão de George em 10/08/2026. */
  score?: number | null;
  status?: string | null;
  summary?: string | null;
  text?: string | null;
  items?: string[] | null;
  /** Tempo relativo da última visita ("há 17 dias", "sem registro"). No card,
   *  e não num bloco da mensagem, por pedido de George em 03/09/2026. */
  last_visit?: string | null;
}

/** Um pedaço da resposta, na ordem em que a tela deve revelar.
 *
 *  A ordem vem do backend e é de leitura, não de cálculo: decisão de incluir ou
 *  excluir, ranking e pontuação, o que ele mais prescreve, o que oferecer e
 *  tempo sem visita. O sexto, o perfil de comunicação, não vem aqui: ele chega
 *  por `enriquecerPerfil`, que demora mais e não pode segurar os cinco. */
export interface BlocoChat {
  ordem: number;
  tipo: "decisao" | "ranking" | "prescreve" | "oferecer" | "visita" | string;
  texto: string;
}

export interface RespostaChat {
  status: StatusChat;
  mensagem: string;
  cards: CardChat[];
  /** Cada chip já vem com o texto correspondente. Tocar num chip não dispara
   *  requisição nem chamada de modelo: é instantâneo e não pode contradizer o
   *  card acima dele. */
  respostas: Record<string, string>;
  /** Vazio quando o backend ainda é anterior a 20/08/2026. A tela cai para os
   *  `cards`, e o portal não fica sem resposta entre um deploy e outro. */
  blocos?: BlocoChat[];
  identificacao: Record<string, unknown>;
}

/**
 * Pergunta do propagandista no chat.
 *
 * Sem estado: o setor vem da sessão, no backend, e nunca do texto. Uma
 * pergunta que cite outro setor é respondida com o setor de quem perguntou.
 */
/** Um item do resumo estruturado da Memória de Visitas, com a data da
 *  observação de origem. */
export interface ItemDeVisita {
  data: string;
  texto: string;
}

/** A Memória de Visitas: a última observação crua mais o resumo estruturado
 *  nas dimensões da proposta de captura, e a classificação automática do
 *  momento da relação. `somente_crua` indica que o resumo não pôde ser
 *  gerado e só a última observação está presente. */
export interface MemoriaDeVisitas {
  disponivel: boolean;
  ultima?: { data: string; tipo: string; comentario: string } | null;
  momento_da_relacao?: { classificacao: string; justificativa: string } | null;
  voz_do_medico: ItemDeVisita[];
  momento_clinico: ItemDeVisita[];
  toque_pessoal: ItemDeVisita[];
  somente_crua: boolean;
}

export interface EnriquecimentoChat {
  texto: string;
  documentos: string[];
  perfil: string;
  disponivel: boolean;
  /** Ausente quando o backend é anterior à Memória de Visitas. */
  visitas?: MemoriaDeVisitas | null;
}

/** O sexto bloco: como conduzir a visita conforme o perfil de comunicação.
 *
 *  Rota separada de propósito. Os cinco primeiros blocos saem de uma consulta e
 *  chegam juntos; este lê o perfil gravado e o texto pronto da base, e a tela o
 *  acrescenta quando ele responde, em vez de segurar o resto esperando.
 *
 *  `disponivel: false` é resposta normal, não erro: acontece para quem ainda
 *  não foi segmentado, que são 225.439 profissionais. A tela simplesmente não
 *  mostra a seção. */
export function enriquecerPerfil(ufcrm: string) {
  return request<EnriquecimentoChat>("/agente/enriquecer", {
    method: "POST",
    body: JSON.stringify({ ufcrm }),
  });
}

export function perguntarAoChat(
  pergunta: string,
  idConversa?: string,
  turno?: number,
) {
  // O id_conversa é a chave da memória do agente no backend. Sem ele, cada
  // pergunta é uma conversa nova e "quero a segunda opção" não aponta para
  // nada. Quem gera e guarda o id é a tela do chat, um por sessão de conversa.
  //
  // O turno cresce a cada envio porque ele compõe o identificador da
  // interação no log do agente. Sem ele, repetir a mesma pergunta na mesma
  // conversa gerava o mesmo identificador e a segunda interação não era
  // registrada: sumiam a resposta, os tokens e o custo da repetição.
  return request<RespostaChat>("/chat/perfil-medico", {
    method: "POST",
    body: JSON.stringify(
      idConversa
        ? { pergunta, id_conversa: idConversa, turno: turno ?? 1 }
        : { pergunta },
    ),
  });
}


/** Os quatro perfis de comunicação, espelhando PERFIS_SEGMENTACAO no backend
 *  e a restrição CHECK da tb_segmentacao_medico. "A DEFINIR" não entra: é
 *  ausência de classificação, não uma escolha. */
export const PERFIS_SEGMENTACAO = [
  "ANALITICO",
  "PERFORMANCE",
  "PESSOAL",
  "RELACIONAL",
] as const;

export type PerfilSegmentacao = (typeof PERFIS_SEGMENTACAO)[number];

/**
 * Grava a leitura do propagandista sobre o perfil do médico.
 *
 * Atende `PUT /ranking/medico/{ufcrm}/segmentacao`. Devolve o detalhe inteiro
 * relido da view, então a tela usa a resposta em vez de assumir que gravou o
 * que mandou.
 */
export function classificarMedico(
  email: string,
  ufcrm: string,
  perfil: PerfilSegmentacao,
) {
  const query = email ? `?email=${encodeURIComponent(email)}` : "";
  return request<DetalheMedicoResponse>(
    `/ranking/medico/${encodeURIComponent(ufcrm)}/segmentacao${query}`,
    { method: "PUT", body: JSON.stringify({ perfil }) },
  );
}


/** Limite do texto de conduta, espelhando CONDUTA_TAMANHO_MAXIMO no backend e
 *  a restrição CHECK da tb_conduta_medico. */
export const CONDUTA_TAMANHO_MAXIMO = 3000;

/**
 * Registra como o médico vem tratando os pacientes.
 *
 * Atende `PUT /ranking/medico/{ufcrm}/conduta`. Cada chamada insere uma linha
 * nova: o histórico é o próprio dado. Devolve o detalhe relido, então a tela
 * usa a resposta em vez de assumir o que mandou.
 */
/**
 * Registra a correção do endereço de atendimento do médico.
 *
 * Atende `PUT /ranking/medico/{ufcrm}/endereco`. Insere, nunca atualiza; a
 * correção mais recente passa a ser o endereço 1 do card. Devolve o detalhe
 * recarregado, como a conduta.
 */
export function corrigirEndereco(email: string, ufcrm: string, corpo: EnderecoCorrecao) {
  const query = email ? `?email=${encodeURIComponent(email)}` : "";
  return request<DetalheMedicoResponse>(
    `/ranking/medico/${encodeURIComponent(ufcrm)}/endereco${query}`,
    { method: "PUT", body: JSON.stringify(corpo) },
  );
}

export function registrarConduta(
  email: string,
  ufcrm: string,
  texto: string,
  origem: "digitado" | "ditado" = "digitado",
) {
  const query = email ? `?email=${encodeURIComponent(email)}` : "";
  return request<DetalheMedicoResponse>(
    `/ranking/medico/${encodeURIComponent(ufcrm)}/conduta${query}`,
    { method: "PUT", body: JSON.stringify({ texto, origem }) },
  );
}


/** Documento da KB de um mercado montado. Atende
 *  `GET /ranking/mercado/{mercado}/kb`. Devolve 404 quando o mercado não tem
 *  material, que é caso normal e não erro. */
export function textoDoMercado(email: string, mercado: string, codLinha: string) {
  const params = new URLSearchParams({ cod_linha: codLinha });
  if (email) params.set("email", email);
  return request<MercadoDetalhe>(
    `/ranking/mercado/${encodeURIComponent(mercado)}/kb?${params}`,
  );
}
