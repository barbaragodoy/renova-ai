"""
Schemas Pydantic para os endpoints da aba Ranking.
Este arquivo é o contrato oficial entre backend e frontend.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class MedicoRanking(BaseModel):
    posicao: int
    nome_medico: str
    ufcrm: str
    pontos: Optional[float]
    no_painel: bool
    especialidade: Optional[str] = None
    cidade: Optional[str] = None
    uf: Optional[str] = None

    # Recomendação pendente para este médico, quando existe. Sai de
    # tb_recomendacoes_painel_historico, e **não** da coluna `recomendacao` da
    # tb_ranking_medicos_validacao: a primeira é o registro sobre o qual se
    # age, a segunda é uma classificação calculada. As duas divergem quando a
    # recomendação já foi aceita, desconsiderada, expirou ou nunca foi gerada,
    # e é a divergência que faria a tela oferecer ação inexistente.
    id_recomendacao_pendente: Optional[str] = None
    tipo_recomendacao_pendente: Optional[str] = None
    # Estado da recomendação do médico neste ciclo, mesmo quando já resolvida.
    # Sai sempre, e é o que permite a linha mostrar o que o propagandista já
    # decidiu em vez de voltar a exibir só o selo de painel.
    status_recomendacao: Optional[str] = None


class ListaRankingResponse(BaseModel):
    ciclo: str
    total_medicos: int
    pontos_lider: Optional[float]
    qtd_painel_setor: Optional[int]
    offset: int
    limite: int
    medicos: list[MedicoRanking]


class CategoriaPrescrita(BaseModel):
    nome: str
    pct: Optional[float] = None


class OpcaoProduto(BaseModel):
    nome: str
    categoria: Optional[str] = None


class ConcorrenteMercado(BaseModel):
    produto: str
    laboratorio: Optional[str] = None
    participacao: Optional[str] = None
    eh_ache: bool = False


class MercadoDetalhe(BaseModel):
    """Documento da KB de um mercado, já em campos.

    O arquivo da KB é markdown feito para o modelo ler. Mandá-lo cru para a
    tela despejava cabeçalho, tabela em pipes e nota metodológica no meio da
    gaveta. Aqui ele vira campo, e a tela mostra só o que serve na visita.
    """

    mercado: str
    area_terapeutica: Optional[str] = None
    concorrentes: list[ConcorrenteMercado] = []
    especialidades: list[str] = []
    usos: list[str] = []
    efeito: Optional[str] = None

    # Vindos da estratégia de ciclo, o material aprovado da Aché. É o único
    # texto que o propagandista pode repetir na frente do médico: descrição de
    # medicamento é área regulada, e nada aqui é gerado por modelo a partir de
    # conhecimento próprio, só recortado do material.
    #
    # Separados dos campos acima de propósito. Os de cima descrevem o mercado
    # observado na auditoria, incluindo concorrente, e o próprio documento da KB
    # avisa que não é indicação clínica. Estes descrevem o produto Aché, e são
    # indicação de verdade. Misturar os dois foi o que colocou "afecções da
    # vagina e da vulva" numa visita a cardiologista.
    indicacao: Optional[str] = None
    beneficio_clinico: Optional[str] = None
    perfil_paciente: Optional[str] = None
    beneficios: list[str] = []
    vantagens: list[str] = []
    ciclos_origem: list[int] = []


class MercadoPrescrito(BaseModel):
    """Um mercado montado em que o médico prescreveu no último ciclo.

    `mercado` é o nome do espaço, que leva o nome do produto Aché. Prescrição
    de concorrente é contabilizada nele de propósito: é para isso que o mercado
    montado existe, e é o que mostra ao propagandista onde ele tem briga.
    """

    mercado: str
    rx: Optional[float] = None
    cod_linha: Optional[str] = None


class DetalheMedicoResponse(BaseModel):
    nome_medico: str
    ufcrm: str
    especialidade: Optional[str] = None
    cidade: Optional[str] = None
    uf: Optional[str] = None

    posicao: Optional[int]
    pontos: Optional[float]
    pontos_lider: Optional[float]

    no_painel: bool
    qtd_painel_setor: Optional[int]
    data_ultima_visita: Optional[str] = None
    meses_sem_visita: Optional[int] = None
    ciclos_no_painel_janela: Optional[int] = None

    # Segmentação do médico, da vw_segmentacao_efetiva. `perfil_origem` diz de
    # onde o valor veio: `propagandista` quando alguém classificou,
    # `salesfarma` quando é o ponto de partida herdado, `a definir` quando não
    # há nenhum dos dois. A tela distingue os três, para o propagandista saber
    # se está olhando a própria leitura ou a da base.
    perfil_comunicacao: Optional[str] = None
    perfil_origem: Optional[str] = None

    # Registro de conduta, o campo "Como Trata". Nulo quando ninguém registrou
    # nada daquele médico neste setor. `conduta_em` e `conduta_por` deixam a
    # tela mostrar quando e por quem, que importa numa carteira visitada por
    # mais de uma pessoa ao longo do tempo.
    # Top 3 mercados do último ciclo, da AuditPharma. `mercados_referencia` é a
    # referência da auditoria, exibida na tela: ela fecha depois que o mês
    # acaba, então fica sempre um mês atrás do ciclo do painel. Sem mostrar a
    # referência, o propagandista compara com o ciclo corrente e conclui que o
    # número está errado.
    mercados: list[MercadoPrescrito] = []
    mercados_referencia: Optional[str] = None

    conduta_texto: Optional[str] = None
    conduta_em: Optional[str] = None
    conduta_por: Optional[str] = None

    recomendacao: str
    # Derivado do motivo narrativo da tb_ranking_medicos_validacao, os mesmos
    # quatro casos que o chat distingue para a frase de saída.
    criterio_saida: Optional[str] = None

    # Prescrição, da tb_perfil_medico_setor. `janela` diz de qual período os
    # números vieram: ciclo, ano ou histórico, na mesma ordem de preferência
    # do chat.
    janela: Optional[str] = None
    categorias: list[CategoriaPrescrita] = []
    produtos: list[str] = []
    pct_ache: Optional[float] = None

    # Produto Aché da linha do setor para a conversa, com até duas opções a
    # mais, decisão de George em 09/08/2026.
    produto_recomendado: Optional[str] = None
    produto_recomendado_categoria: Optional[str] = None
    rec_e_top1: bool = False
    ja_prescreve_o_produto: bool = False
    opcoes_produto: list[OpcaoProduto] = []


# Os quatro perfis de comunicação. Espelham a restrição CHECK
# `perfil_conhecido` da tb_segmentacao_medico, que recusa qualquer outro
# valor no banco. Estão aqui para o 422 sair antes da ida ao warehouse, não
# como barreira: a barreira é a do banco.
#
# "A DEFINIR" não entra: é estado de ausência, resolvido pela view quando não
# há edição nem valor no SalesFarma. Oferecer como opção deixaria o
# propagandista "escolher não saber", que é diferente de ainda não ter
# escolhido.
PERFIS_SEGMENTACAO = ("ANALITICO", "PERFORMANCE", "PESSOAL", "RELACIONAL")


class SegmentacaoUpdateRequest(BaseModel):
    """Corpo do `PUT /ranking/medico/{ufcrm}/segmentacao`.

    Só o perfil entra. Setor e matrícula de quem alterou saem da identidade
    autenticada, nunca do corpo: aceitá-los do cliente deixaria alguém
    classificar médico de outro setor.
    """

    perfil: Literal[PERFIS_SEGMENTACAO]
    observacao: Optional[str] = Field(None, max_length=280)


# Limite do texto de conduta. Espelha a restrição CHECK `texto_no_limite` da
# tb_conduta_medico, que recusa acima disso no banco. Definido por George em
# 20/08: "pode ter 3 mil caracteres".
CONDUTA_TAMANHO_MAXIMO = 3000


class CondutaUpdateRequest(BaseModel):
    """Corpo do `PUT /ranking/medico/{ufcrm}/conduta`.

    Só o texto e a origem entram. Setor e matrícula saem da identidade
    autenticada, nunca do corpo, pelo mesmo princípio do resto do portal.

    `origem` distingue texto digitado de texto ditado. Guardar isso agora, e
    não depois, é o que vai permitir medir a qualidade da transcrição quando a
    entrada por voz entrar, decisão que segue em aberto desde 18/08.
    """

    texto: str = Field(..., min_length=1, max_length=CONDUTA_TAMANHO_MAXIMO)
    origem: Literal["digitado", "ditado"] = "digitado"

    @field_validator("texto")
    @classmethod
    def _limpar(cls, valor: str) -> str:
        limpo = valor.strip()
        if not limpo:
            raise ValueError("Texto vazio.")
        return limpo
