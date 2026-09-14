"""As sete ferramentas da via 1, e o recorte que o modelo não consegue expressar.

O ponto central deste módulo é o que **não** existe nele: nenhuma ferramenta
declara `setor` como parâmetro. O modelo não tem como pedir dado de outro setor
porque não há campo onde escrever isso. O setor entra no SQL a partir do
contexto autenticado, no momento da execução, e a pergunta pode citar o código
de outro setor à vontade que o valor é ignorado.

A especificação da T1.1 pedia `setor` como parâmetro obrigatório das funções.
Retirá-lo do vocabulário do modelo é mais forte: um parâmetro obrigatório
garante que algum setor foi passado, nunca que foi o certo.

Origem dos dados: as três views governadas de `acheinfo_dev.renovai`, criadas
em 19/08/2026. O DDL está em
`databricks-ped-ache/03-genie-consultivo/agente-fase1/views_governadas.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from backend.app.db.sql_dialect import formatar_data_sql


# Limites de linha por ferramenta. Existem para o retorno caber na janela do
# modelo e para o verificador de número ter um conjunto pequeno onde conferir.
LIMITE_BUSCA = 8
LIMITE_VISITAS = 15
LIMITE_PARTICIPACAO = 10
LIMITE_PRODUTOS = 8
LIMITE_OBSERVACOES = 5


@dataclass(frozen=True)
class Contexto:
    """O que o backend sabe sobre quem pergunta. Nada disso vem do texto."""

    email: str
    matricula: str
    setor: str
    linha: Optional[str] = None


@dataclass(frozen=True)
class Ferramenta:
    nome: str
    descricao: str
    parametros: dict[str, Any]
    executar: Callable[..., list[dict[str, Any]]]

    def declaracao(self) -> dict[str, Any]:
        """Formato de tool do endpoint de serving, compatível com OpenAI."""
        return {
            "type": "function",
            "function": {
                "name": self.nome,
                "description": self.descricao,
                "parameters": self.parametros,
            },
        }


# Colunas de percentual, formatadas antes de chegar ao modelo.
COLUNAS_PERCENTUAL = ("PARTICIPACAO_ACHE_PCT", "PARTICIPACAO_PCT")


def _formatar_percentual(linhas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Devolve 3,6% no lugar de 3.6, e o modelo copia em vez de formatar.

    A regra 3 de `chat/como-alterar-a-resposta-do-chat.md` manda percentual com
    vírgula. Pedir isso por instrução falhava: o modelo escrevia "é de 3.6",
    sem vírgula e sem sinal, o que lê como número solto e não como percentual.
    Formatando na origem, a forma certa é a única que existe no retorno, e o
    verificador de número continua enxergando o 3,6 dentro da string.

    Aceita float e string porque os dois executores existem: o do portal usa
    SQLAlchemy e devolve tipo numérico, e a SQL Statement Execution API devolve
    tudo como texto. A primeira versão pulava string, e por isso a formatação
    não acontecia justamente no caminho real.
    """
    for linha in linhas:
        for coluna in COLUNAS_PERCENTUAL:
            valor = linha.get(coluna)
            if valor is None or (isinstance(valor, str) and "%" in valor):
                continue
            linha[coluna] = f"{valor}".replace(".", ",") + "%"
    return linhas


def _sem_acento_maiusculo(termo: str) -> str:
    """Espelha o `NOME_BUSCA` da view, que é `UPPER(TRANSLATE(...))`.

    A normalização acontece dos dois lados: a coluna já vem normalizada da
    view e o termo do propagandista é normalizado aqui. Sem isso, "josé"
    não encontra "JOSE".
    """
    de = "ÁÀÂÃÄáàâãäÉÈÊËéèêëÍÌÎÏíìîïÓÒÔÕÖóòôõöÚÙÛÜúùûüÇç"
    para = "AAAAAAAAAAEEEEEEEEIIIIIIIIOOOOOOOOOOUUUUUUUUCC"
    tabela = str.maketrans(de, para)
    return termo.translate(tabela).upper()


class Ferramentas:
    """Fábrica das ferramentas já amarradas a um contexto e a um executor.

    O executor é a mesma interface mínima de `chat/executor.py`, `query(sql,
    params)`, para o módulo continuar testável com um executor falso.
    """

    def __init__(self, contexto: Contexto, executor, conhecimento=None, schema: str = ""):
        self.ctx = contexto
        self.executor = executor
        self.conhecimento = conhecimento
        self.schema = schema

    def _qualificar(self, tabela: str) -> str:
        """Nome de tabela pronto para SQL, qualificado só quando `schema` for informado.

        Default vazio (não `acheinfo_dev.renovai`) porque nomes sem catálogo já
        resolvem certo nos dois lados de `DATA_SOURCE`: no Postgres local via
        `search_path`, no Databricks via `catalog`/`schema` de `connect_args`
        (confirmado por teste direto em 26/08/2026). O parâmetro continua
        aceitando um valor explícito para não fechar a porta a um cenário
        futuro (ex.: apontar para outro catálogo em debug).
        """
        return f"{self.schema}.{tabela}" if self.schema else tabela

    # ---------------------------------------------------------------- 1

    def buscar_medico(self, termo_busca: str) -> list[dict[str, Any]]:
        termo = _sem_acento_maiusculo((termo_busca or "").strip())
        if not termo:
            return []
        return self.executor.query(
            f"""
            SELECT UFCRM, NOME_MEDICO, ESPECIALIDADE, CIDADE,
                   POSICAO_RANKING, NO_PAINEL, MESES_DESDE_ULTIMA_VISITA,
                   CICLO_REFERENCIA
            FROM {self._qualificar('vw_agente_medico')}
            WHERE SETOR = :setor
              AND (NOME_BUSCA LIKE :padrao OR UPPER(UFCRM) LIKE :padrao)
            ORDER BY NO_PAINEL DESC, POSICAO_RANKING
            LIMIT {LIMITE_BUSCA}
            """,
            {"setor": self.ctx.setor, "padrao": f"%{termo}%"},
        )

    # ---------------------------------------------------------------- 2

    def perfil_do_medico(self, ufcrm: str) -> list[dict[str, Any]]:
        linhas = self.executor.query(
            f"""
            SELECT UFCRM, NOME_MEDICO, ESPECIALIDADE, CIDADE, LINHA_PRODUTO,
                   POSICAO_RANKING, NO_PAINEL, MESES_DESDE_ULTIMA_VISITA,
                   CATEGORIA_1, CATEGORIA_2, CATEGORIA_3,
                   PARTICIPACAO_ACHE_PCT, CICLO_REFERENCIA
            FROM {self._qualificar('vw_agente_medico')}
            WHERE SETOR = :setor AND UFCRM = :ufcrm
            """,
            {"setor": self.ctx.setor, "ufcrm": (ufcrm or "").strip().upper()},
        )
        return _formatar_percentual(linhas)

    # ---------------------------------------------------------------- 3

    def visitas_pendentes(self, meses: int = 3) -> list[dict[str, Any]]:
        try:
            n = int(meses)
        except (TypeError, ValueError):
            n = 3
        n = max(1, min(n, 24))
        return self.executor.query(
            f"""
            SELECT UFCRM, NOME_MEDICO, ESPECIALIDADE, CIDADE,
                   MESES_DESDE_ULTIMA_VISITA, POSICAO_RANKING, CICLO_REFERENCIA
            FROM {self._qualificar('vw_agente_medico')}
            WHERE SETOR = :setor AND NO_PAINEL
              AND MESES_DESDE_ULTIMA_VISITA >= :meses
            ORDER BY MESES_DESDE_ULTIMA_VISITA DESC, POSICAO_RANKING
            LIMIT {LIMITE_VISITAS}
            """,
            {"setor": self.ctx.setor, "meses": n},
        )

    # ---------------------------------------------------------------- 4

    def participacao_no_agrupamento(self, agrupamento: str) -> list[dict[str, Any]]:
        """Participação no território do propagandista, não no país.

        A view não expõe volume de prescrição, só percentual. A política por
        classe de número da T1.2 é cumprida pela superfície de dados, e não
        por instrução ao modelo: não há número absoluto de prescrição para o
        modelo exibir mesmo que queira.
        """
        linhas = self.executor.query(
            f"""
            SELECT AGRUPAMENTO, PRODUTO, LABORATORIO, E_ACHE,
                   PARTICIPACAO_PCT, REFERENCIA
            FROM {self._qualificar('vw_agente_participacao')}
            WHERE SETOR = :setor AND UPPER(AGRUPAMENTO) = UPPER(:agrupamento)
            ORDER BY PARTICIPACAO_PCT DESC
            LIMIT {LIMITE_PARTICIPACAO}
            """,
            {"setor": self.ctx.setor, "agrupamento": (agrupamento or "").strip()},
        )
        return _formatar_percentual(linhas)

    # ---------------------------------------------------------------- 5

    def produtos_para_medico(self, ufcrm: str) -> list[dict[str, Any]]:
        """Duas consultas: a linha e a especialidade saem do próprio painel.

        O modelo não informa linha nem especialidade. Ele dá o UFCRM e o
        backend resolve o resto, pelo mesmo motivo do setor: um valor que o
        modelo escolhe é um valor que ele pode errar.
        """
        base = self.executor.query(
            f"""
            SELECT LINHA_PRODUTO, COALESCE(ESPECIALIDADE, 'NAO INFORMADA') AS ESPECIALIDADE
            FROM {self._qualificar('vw_agente_medico')}
            WHERE SETOR = :setor AND UFCRM = :ufcrm
            """,
            {"setor": self.ctx.setor, "ufcrm": (ufcrm or "").strip().upper()},
        )
        if not base:
            return []
        return self.executor.query(
            f"""
            SELECT ORDEM_SUGERIDA, PRODUTO, CATEGORIA_ATC,
                   AREA_TERAPEUTICA, PRIORIDADE, MOTIVO
            FROM {self._qualificar('vw_agente_produtos')}
            WHERE LINHA_PRODUTO = :linha AND ESPECIALIDADE = :esp
            ORDER BY ORDEM_SUGERIDA
            LIMIT {LIMITE_PRODUTOS}
            """,
            {"linha": base[0]["LINHA_PRODUTO"], "esp": base[0]["ESPECIALIDADE"]},
        )

    # ---------------------------------------------------------------- 6

    def observacoes_do_medico(self, ufcrm: str) -> list[dict[str, Any]]:
        """As últimas observações escritas pelo propagandista sobre o médico.

        Fonte: `vw_visitacao_comentarios`, view em `acheinfo_dev.renovai`
        sobre a `propagandistas_visitacao_medica` do domínio SalesFarma.

        **Não lê a tabela direto, e o motivo não é estilo.** O service
        principal do portal não tem `USE CATALOG` em `dmn_produtividade_dev`:
        medido em 04/09/2026 autenticando com `oauth_service_principal`, ele
        não é membro de nenhum grupo `user-renovai-*` e a leitura direta falha
        com `INSUFFICIENT_PERMISSIONS`. A view tem o grupo
        `user-renovai-engineering` como dono e já filtra `VISITA_EFETIVA`;
        view do Unity Catalog roda com a permissão do dono, então o service
        principal lê por ela o que não lê direto. Mesmo mecanismo de
        `vw_gold_auditpharma` e `vw_segmentacao_efetiva`.

        **É contorno.** Quando o service principal entrar no grupo de
        engenharia, pedido do Orlando ao Flávio em 04/09/2026, a leitura pode
        voltar a ser direta.

        Medido em 01/09/2026: 581 mil visitas com comentário por
        ciclo, 74% com texto único, média de 190 caracteres, e o médico
        mediano com 35 visitas comentadas de histórico. É o registro do que
        foi conversado, prometido e pedido, incluindo o aspecto pessoal que o
        propagandista anotou e que é decisão de produto priorizar, não
        esconder.

        O filtro `VISITA_EFETIVA = 'S'` continua valendo, e é obrigatório: a
        tabela mistura visita realizada e não realizada, e as não realizadas
        carregam texto automático de fechamento. Ele saiu daqui porque agora
        mora na definição da view, aplicado uma vez para todos os leitores.

        O setor vem do contexto autenticado, como em todas as ferramentas:
        observação de um propagandista não vaza para outro.
        """
        # O ORDER BY qualifica a coluna original: o alias DATA_VISITA da
        # projeção é texto dd/MM/yyyy, e ordenar o texto colocaria 31/01/2025
        # acima de 01/12/2026. Achado da revisão independente de 02/09/2026.
        return self.executor.query(
            """
            SELECT {data_visita} AS DATA_VISITA,
                   v.VISITA_TIPO, v.COMENTARIOS
            FROM vw_visitacao_comentarios AS v
            WHERE v.SETOR = :setor AND v.UFCRM = :ufcrm
            ORDER BY v.DATA_VISITA DESC
            LIMIT {limite}
            """.format(
                data_visita=formatar_data_sql("v.DATA_VISITA"),
                limite=LIMITE_OBSERVACOES,
            ),
            {"setor": self.ctx.setor, "ufcrm": (ufcrm or "").strip().upper()},
        )

    # ---------------------------------------------------------------- 7

    def buscar_conhecimento(self, pergunta: str) -> list[dict[str, Any]]:
        """Knowledge Assistant do piloto. Falha degrada, não estoura.

        Sem KA configurado ou com o endpoint fora do ar, a ferramenta devolve
        um aviso de indisponibilidade em vez de erro, para o agente responder
        com honestidade em vez de quebrar a conversa inteira.
        """
        if self.conhecimento is None:
            return [{"indisponivel": "a base de conhecimento não está configurada nesta instalação"}]
        try:
            return self.conhecimento.buscar(pergunta)
        except Exception:  # noqa: BLE001 - degradar é o comportamento pedido
            return [{"indisponivel": "a base de conhecimento não respondeu agora"}]

    # ----------------------------------------------------------------

    def catalogo(self) -> list[Ferramenta]:
        def obj(props: dict, req: list[str]) -> dict:
            return {"type": "object", "properties": props, "required": req}

        return [
            Ferramenta(
                "buscar_medico",
                "Resolve um profissional pelo nome parcial, pelo CRM ou pelo UFCRM. "
                "Use sempre esta ferramenta primeiro quando a pergunta cita um nome, "
                "porque as outras precisam do UFCRM. Aceita nome incompleto, "
                "sem acento e em qualquer caixa.",
                obj({"termo_busca": {"type": "string", "description": "Nome parcial, CRM ou UFCRM"}},
                    ["termo_busca"]),
                self.buscar_medico,
            ),
            Ferramenta(
                "perfil_do_medico",
                "Perfil do profissional: especialidade, cidade, posição no ranking, se está "
                "no painel, meses desde a última visita, as três categorias que ele mais "
                "prescreve e a participação Aché. Precisa do UFCRM devolvido por buscar_medico.",
                obj({"ufcrm": {"type": "string", "description": "UFCRM exato"}}, ["ufcrm"]),
                self.perfil_do_medico,
            ),
            Ferramenta(
                "visitas_pendentes",
                "Profissionais do painel sem visita há pelo menos N meses, do mais atrasado "
                "para o menos. Use quando a pergunta for sobre quem está sem visita, quem "
                "priorizar ou o que está atrasado.",
                obj({"meses": {"type": "integer", "description": "Mínimo de meses sem visita. Padrão 3"}},
                    []),
                self.visitas_pendentes,
            ),
            Ferramenta(
                "participacao_no_agrupamento",
                "Participação percentual dos produtos dentro de um agrupamento terapêutico, "
                "no território do propagandista. Use o nome do agrupamento como aparece nas "
                "categorias devolvidas por perfil_do_medico.",
                obj({"agrupamento": {"type": "string", "description": "Nome do agrupamento"}},
                    ["agrupamento"]),
                self.participacao_no_agrupamento,
            ),
            Ferramenta(
                "produtos_para_medico",
                "Produtos da linha do propagandista ordenados para este profissional, com o "
                "motivo da ordem. PRIORIDADE 1 é o que combina com a especialidade dele. "
                "A lista nunca esconde produto: ela ordena.",
                obj({"ufcrm": {"type": "string", "description": "UFCRM exato"}}, ["ufcrm"]),
                self.produtos_para_medico,
            ),
            Ferramenta(
                "observacoes_do_medico",
                "As últimas observações que o propagandista escreveu sobre este "
                "profissional nas visitas anteriores: o que foi conversado, o que ele "
                "pediu, compromissos e anotações pessoais. Use quando a pergunta for "
                "sobre visitas passadas, sobre o que foi combinado, ou para preparar a "
                "próxima visita. Cite a data da observação ao usar o conteúdo. "
                "Precisa do UFCRM devolvido por buscar_medico.",
                obj({"ufcrm": {"type": "string", "description": "UFCRM exato"}}, ["ufcrm"]),
                self.observacoes_do_medico,
            ),
            Ferramenta(
                "buscar_conhecimento",
                "Busca na base de conhecimento do projeto: material de estratégia de ciclo, "
                "guias de segmentação, perfis de comunicação e conteúdo de apoio. Use para "
                "pergunta conceitual ou de abordagem que não é respondida por dado do painel. "
                "A base recupera por significado e por termo completo, então REESCREVA a "
                "pergunta antes de buscar: complete nome de produto abreviado ou truncado, "
                "expanda sigla e transforme o fragmento em uma pergunta inteira. "
                "Se a busca não achar nada, tente de novo com o termo corrigido antes de "
                "responder que não existe.",
                obj({"pergunta": {"type": "string",
                                  "description": "A pergunta reescrita e completa, não o "
                                                 "fragmento que o propagandista digitou"}},
                    ["pergunta"]),
                self.buscar_conhecimento,
            ),
        ]
