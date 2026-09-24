"""
Contrato do perfil do propagandista, consumido pela aba Usuário do portal.

Regra que orientou este schema: só entra campo que a fonte sustenta hoje. Em
vez de devolver valor inventado ou string vazia, campo sem fonte fica fora do
contrato: a interface mostra "não disponível" e o cliente enxerga a lacuna em
vez de um dado falso.

A nota anterior deste módulo dizia que cargo, regional, cidade/estado, último
acesso e status da conta não existiam em `tb_propagandistas` (verificação de
04/08/2026). Isso mudou em parte: a tabela foi ampliada em 05 e 06/08/2026 e
hoje tem `CARGO`, `REGIONAL`, `UF`, `CIDADES_SETOR` e `ESPECIALIDADES_SETOR`.
Esses campos pertencem aos blocos 2 e 3 da aba, que ainda não foram
implementados, então continuam fora deste contrato por escopo, não por falta de
fonte. `STATUS_CONTA` foi removida da tabela por decisão de George em
05/08/2026: o status passa a ser derivado da existência de setor. Último acesso
segue sem fonte.

Ponto de modelagem que difere de `/auth/contexto`: aqui o perfil devolve uma
LISTA de atribuições, não um setor único. O grão real de `tb_propagandistas` é
SETOR, e uma matrícula pode aparecer em mais de uma linha. Em 07/08/2026 são
2.153 linhas para 2.148 matrículas, ou seja, 5 pessoas em 2 setores cada.
Modelar como lista evita ter que reescrever o contrato quando o cadastro voltar
a ter mais desses casos.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# Franquias de cada linha comercial, por extenso.
#
# Fonte: material "Organização Portfólio e Equipe 2026", enviado por George em
# 20/08/2026, e o glossário de siglas registrado em
# `05-Simbiox-e-Ache/ped-1.0-painel-consultivo/docs/task-franquias-perfil-prescritivo.md`,
# que traz a mesma composição de linhas produto a produto.
#
# Fica como constante, e não em tabela, porque não existe de-para de linha
# para franquia no catálogo hoje: a tb_atc4_produto_ache liga linha a classe
# terapêutica, e cada linha cobre de 15 a 27 classes distintas (medido em
# 20/08/2026). Quando esse de-para existir como dado, esta constante sai.
#
# "Linha" não é sinônimo de franquia: é a combinação de franquias atribuída a
# um time. A mesma franquia aparece em mais de uma linha, como SNC nas linhas
# 2 e 3.
#
# Gastro, Osteo e Oftalmo aparecem sem forma expandida porque o glossário
# registrado também não a define ("Gastro = Gastro", "Ofta = Oftalmo",
# "Osteo = Osteo/ósseo"). Escrever "Gastroenterologia" ou "Osteoarticular"
# aqui seria inventar vocabulário que a Aché não registrou.
FRANQUIAS_POR_LINHA = {
    "1": ["Cardiologia", "Gastro"],
    "2": ["Sistema Nervoso Central", "Osteo"],
    "3": ["Sistema Nervoso Central", "Cardiologia"],
    "4": ["Gastro", "Respiratório"],
    "5": ["Osteo", "Respiratório", "Oftalmo"],
    "6": ["Saúde Feminina", "Dermatológico"],
}


# Recuo do limite do painel quando tb_renovai_parametros não responder. A
# fonte é a tabela, coluna LIMITE_PAINEL_PADRAO; este literal só evita a tela
# ficar sem valor num caminho de erro.
#
# Desde 18/09/2026 o limite é único, não personalizável: George decidiu, ao
# alinhar o portal ao protótipo, que a personalização por propagandista sai
# e o padrão passa a 300. A coluna LIMITE_PAINEL de tb_perfil_portal deixou de
# ser lida em todos os pontos do backend. O notebook de geração das
# recomendações (nb_dev_criacao_renovai_tb_recomendacoes_painel_hist) ainda
# tem o 318 em COALESCE e precisa ser alinhado pelo Hugo; ver a pendência em
# docs/context/known-issues.md.
LIMITE_PAINEL_PADRAO = 300


class AtribuicaoSetor(BaseModel):
    """Uma linha de `tb_propagandistas`: o setor e a cadeia de gestão dele.

    A hierarquia é resolvida por papel na origem (GD = gerente distrital,
    GR = regional, GN = divisão/nacional), então cada atribuição carrega a sua
    própria cadeia. Quando um propagandista cobre dois setores, os gestores
    podem ser diferentes em cada um, e é por isso que estes campos moram aqui e
    não no nível do perfil.
    """

    setor: str
    linha_produto: Optional[str] = None
    gd_nome: Optional[str] = None
    gd_email: Optional[str] = None
    gr_nome: Optional[str] = None
    gn_nome: Optional[str] = None


class PerfilResponse(BaseModel):
    """Identidade do propagandista mais as suas atribuições de setor.

    `nome` é o valor final que a tela exibe: o nome editado pela pessoa quando
    existe, e o nome de guerra da SIMV (`SBNM_NAME_WAR`) quando não existe.
    Decisão de George em 05/08/2026, item 1.2 da aba Usuário.

    `nome_editado` diz de onde o valor veio. A interface usa isso para oferecer
    "voltar ao nome original" só para quem de fato editou, em vez de mostrar a
    opção para todo mundo.

    A tela pede "nome completo". A fonte não tem essa informação: `REP_NOME` é
    nome de guerra e a coluna `REP_NOME_COMPLETO`, criada em 05/08/2026, foi
    removida em 06/08/2026 por decisão de George no item 1.1. O campo é
    entregue como é, e a interface não promete mais do que isso.
    """

    matricula: str
    nome: str
    nome_editado: bool = False
    email: str
    login: Optional[str] = None
    foto_path: Optional[str] = None

    # "Status da conta" (bloco 1, decisão de George em 05/08/2026). Até a
    # task de bloqueio de acesso, era derivado no frontend da existência de
    # setor ("Ativo"/"Sem setor") — não existia coluna própria ainda. Agora
    # vem de tb_perfil_portal.STATUS_ACESSO ("ATIVO"/"BLOQUEADO"), a mesma
    # fonte que decide se a pessoa consegue entrar no portal. `None` quando
    # não há linha em tb_perfil_portal — a interface trata como bloqueado,
    # mesmo deny-by-default da checagem de acesso.
    status_acesso: Optional[str] = None

    # Bloco 3 da aba, alinhado com George em 07/08/2026. Todos saem da mesma
    # linha de `tb_propagandistas` que o resto do perfil, sem consulta extra.
    cargo: Optional[str] = None
    regional: Optional[str] = None
    uf: Optional[str] = None
    linha_nome: Optional[str] = None

    # Listas completas, ordenadas por número de médicos decrescente na origem.
    # A tela exibe as três primeiras e oferece "veja mais", decisão de George
    # em 06/08/2026. O corte fica na interface e não aqui para o "veja mais"
    # não precisar de uma segunda chamada.
    cidades: List[str] = []
    especialidades: List[str] = []

    # Franquias da linha de produtos da pessoa, por extenso. Vazio quando a
    # linha não está no de-para, o que só acontece se a Aché criar uma linha
    # nova sem esta constante ser atualizada. A tela mostra não disponível em
    # vez de esconder o campo, para a lacuna aparecer.
    franquias_linha: List[str] = []

    # Penúltimo login. O login em curso não entra: mostrar o acesso atual
    # daria sempre "agora". Nulo no primeiro acesso da pessoa. Decisão de
    # George em 07/08/2026.
    dt_acesso_anterior: Optional[datetime] = None

    # Cards 2.3 e 2.5 do bloco 2. Somados quando a pessoa atende mais de um
    # setor, porque o resumo descreve a carteira inteira dela. Nulos quando a
    # consulta de resumo falha, e a interface mostra não disponível sem
    # derrubar o resto do perfil.
    medicos_no_painel: Optional[int] = None
    recomendacoes_pendentes: Optional[int] = None

    # Limite do painel em vigor, único para todos, lido de
    # tb_renovai_parametros. Fica na resposta por ser dado do motor que a
    # tela pode citar; a edição por propagandista saiu em 18/09/2026.
    limite_painel: int = LIMITE_PAINEL_PADRAO

    # As duas especialidades com mais médicos distintos visitados nos últimos
    # doze meses, somando os setores da pessoa. É o campo "Especialidades
    # predominantes" do protótipo, decisão de George em 18/09/2026.
    #
    # Por médicos distintos e não por número de visitas: é a regra que ele
    # fechou em 05/08/2026 para a ordenação de especialidades, e resiste a um
    # médico visitado dez vezes puxar a especialidade dele para o topo. Medido
    # em 18/09/2026: as duas definições coincidem em 78,4% dos 2.634 setores
    # com visita, então a escolha muda o que aparece em um a cada cinco.
    #
    # Vazio quando não há visita no período ou quando a consulta de resumo
    # falha; a tela mostra não disponível.
    especialidades_predominantes: List[str] = []

    atribuicoes: List[AtribuicaoSetor]

    @property
    def multiplos_setores(self) -> bool:
        return len(self.atribuicoes) > 1


class PerfilUpdateRequest(BaseModel):
    """Corpo do `PUT /auth/perfil`.

    Só o nome entra. Matrícula, e-mail e o valor de origem da SIMV são
    resolvidos no servidor a partir da sessão autenticada, nunca do corpo:
    aceitar identificador do cliente permitiria que uma pessoa editasse o
    perfil de outra. Pré-requisito 3 do item 1.3, registrado em
    `DECISOES_ABA_USUARIO_PORTAL_2026-08-05`.

    `nome` nulo é a forma de desfazer a edição. Nesse caso a gravação limpa
    `NOME_EXIBICAO` e a leitura volta sozinha para o nome da SIMV pelo mesmo
    COALESCE, sem precisar de rota de exclusão.

    Limite de 60 caracteres: o maior `REP_NOME` em `tb_propagandistas` tem 22
    caracteres e a média é 13,7 (medido em 07/08/2026, 2.153 registros). O
    cartão de identificação da tela é dimensionado para uma linha. Quase o
    triplo do maior valor real dá folga sem deixar o campo virar texto livre.
    """

    nome: Optional[str] = Field(None, max_length=60)

    @field_validator("nome")
    @classmethod
    def _normalizar(cls, valor: Optional[str]) -> Optional[str]:
        # String vazia e string só de espaço chegam da interface quando a
        # pessoa apaga o campo e salva. As duas significam "desfazer a
        # edição", o mesmo que enviar nulo, então são normalizadas aqui em vez
        # de virarem um nome em branco gravado na tabela.
        if valor is None:
            return None
        limpo = valor.strip()
        return limpo or None
