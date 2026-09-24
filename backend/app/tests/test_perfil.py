"""
Testes de resolver_perfil.

Diferente de test_context.py, aqui nada depende do Postgres local: a engine é
substituída em todos os casos. O motivo é que o cenário mais importante deste
arquivo, o propagandista com dois setores, não é reprodutível na seed local e
mudaria de resultado conforme o cadastro real fosse corrigido na origem.

O caso de dois setores não é hipotético. Em 04/08/2026 existem 9
propagandistas nessa condição em `tb_propagandistas`, todos surgidos da
reorganização de força de vendas de 30/07. Os dados de ANTONIO VAZ usados
abaixo são um desses casos reais.
"""
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend.app.auth.perfil import resolver_perfil


def _linha(setor: str, linha_produto: str, gd_nome: str) -> dict:
    return {
        "setor": setor,
        "linha_produto": linha_produto,
        "rep_matricula": "184480",
        "rep_nome": "ANTONIO VAZ",
        "rep_email": "antonio.vaz@ache.com.br",
        "rep_login": "avaz",
        "gd_nome": gd_nome,
        "gd_email": f"{gd_nome.split()[0].lower()}@ache.com.br",
        "gr_nome": "PATRICIA REGIONAL",
        "gn_nome": "ROBERTO NACIONAL",
        # Bloco 3, da mesma linha de tb_propagandistas.
        "cargo": "Propagandista",
        "regional": "SUL",
        "uf": "RS",
        "linha_nome": "LINHA 5",
        "cidades_setor": "SANTA MARIA, SANTIAGO, SÃO BORJA, ITAQUI",
        "especialidades_setor": "CLINICO GERAL, CARDIOLOGIA",
        # Vindas do LEFT JOIN com tb_perfil_portal. Nulas é o caso de quem
        # nunca editou nem acessou, que é todo mundo até a aba entrar em uso.
        "nome_exibicao": None,
        "foto_path": None,
        "dt_acesso_anterior": None,
        # Vinda do CROSS JOIN com tb_renovai_parametros (Fase 3.5,
        # 26/08/2026) — fonte única do default, substitui o antigo literal
        # 318 em Python. Linha única real: sempre presente, nunca NULL.
        "limite_painel_padrao": 300,
        "especialidades_predominantes": "CLINICA GERAL,CARDIOLOGIA",
        # Contagens do bloco 2, que passaram a vir na mesma consulta da
        # identidade em 07/08/2026.
        "medicos_no_painel": 392,
        "recomendacoes_pendentes": 134,
    }


class _FakeResult:
    def __init__(self, linhas):
        self._linhas = linhas

    def mappings(self):
        return self

    def fetchall(self):
        return self._linhas

    def first(self):
        return self._linhas[0] if self._linhas else None


class _FakeConn:
    def __init__(self, linhas, engine=None):
        self._linhas = linhas
        self._engine = engine

    def execute(self, *_args, **_kwargs):
        if self._engine is not None:
            self._engine.consultas += 1
        return _FakeResult(self._linhas)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeEngine:
    def __init__(self, linhas):
        self._linhas = linhas
        # Conta idas ao banco: a aba precisa fazer uma consulta só.
        self.consultas = 0

    def connect(self):
        return _FakeConn(self._linhas, self)


class _com_linhas:
    """Substitui a engine e devolve o dublê, para inspecionar as consultas."""

    def __init__(self, linhas):
        self._engine = _FakeEngine(linhas)
        self._patch = patch(
            "backend.app.auth.perfil._get_engine", return_value=self._engine
        )

    def __enter__(self):
        self._patch.start()
        return self._engine

    def __exit__(self, *_a):
        self._patch.stop()
        return False


def test_perfil_com_um_setor():
    with _com_linhas([_linha("010103040755", "5", "EWERTON PAULA")]):
        perfil = resolver_perfil("antonio.vaz@ache.com.br")

    assert perfil.matricula == "184480"
    assert perfil.nome == "ANTONIO VAZ"
    assert perfil.email == "antonio.vaz@ache.com.br"
    assert len(perfil.atribuicoes) == 1
    assert perfil.multiplos_setores is False
    assert perfil.atribuicoes[0].setor == "010103040755"
    assert perfil.atribuicoes[0].gd_nome == "EWERTON PAULA"


def test_perfil_com_dois_setores_devolve_as_duas_atribuicoes():
    """O perfil não escolhe um setor nem falha: descreve as duas atribuições.

    Este é o comportamento que separa /auth/perfil de /auth/contexto. O
    contexto bloqueia porque precisa de um setor único para filtrar
    recomendação; o perfil só descreve, e omitir a segunda atribuição seria
    esconder do propagandista um setor que o cadastro diz ser dele.
    """
    with _com_linhas(
        [
            _linha("010103030155", "5", "DENISE CAETANO"),
            _linha("010103040755", "5", "EWERTON PAULA"),
        ]
    ):
        perfil = resolver_perfil("antonio.vaz@ache.com.br")

    assert len(perfil.atribuicoes) == 2
    assert perfil.multiplos_setores is True
    assert [a.setor for a in perfil.atribuicoes] == ["010103030155", "010103040755"]
    # Cada atribuição carrega a própria cadeia de gestão: no dado real os dois
    # setores do Antonio respondem a gerentes distritais diferentes.
    assert [a.gd_nome for a in perfil.atribuicoes] == ["DENISE CAETANO", "EWERTON PAULA"]


def test_perfil_aceita_email_gravado_em_maiusculas():
    """Parte dos registros tem REP_EMAIL em maiúsculas na origem.

    O LOWER() dos dois lados é o que garante o match. O e-mail devolvido é o
    da base, não o digitado, para a tela mostrar o cadastro real.
    """
    linha = _linha("010103040755", "5", "EWERTON PAULA")
    linha["rep_email"] = "ANTONIO.VAZ@ACHE.COM.BR"

    with _com_linhas([linha]):
        perfil = resolver_perfil("antonio.vaz@ache.com.br")

    assert perfil.email == "ANTONIO.VAZ@ACHE.COM.BR"


def test_perfil_sem_cadastro_devolve_404():
    with _com_linhas([]):
        with pytest.raises(HTTPException) as excecao:
            resolver_perfil("fulano.naoexiste@ache.com.br")

    assert excecao.value.status_code == 404


def test_perfil_tolera_campos_opcionais_vazios():
    """Cerca de 0,6% dos propagandistas não têm GD e respondem direto ao GR.

    O contrato marca a cadeia de gestão como opcional justamente por isso: um
    None aqui é cadastro legítimo, não erro.
    """
    linha = _linha("010103040755", "5", "EWERTON PAULA")
    linha["gd_nome"] = None
    linha["gd_email"] = None
    linha["linha_produto"] = None
    linha["rep_login"] = None

    with _com_linhas([linha]):
        perfil = resolver_perfil("antonio.vaz@ache.com.br")

    assert perfil.login is None
    assert perfil.atribuicoes[0].gd_nome is None
    assert perfil.atribuicoes[0].linha_produto is None
    assert perfil.atribuicoes[0].gr_nome == "PATRICIA REGIONAL"


# --------------------------------------------------------------- edição do nome


def test_nome_editado_vence_o_da_simv():
    """Item 1.2: mostra o editado quando existe, cai na SIMV quando não existe.

    O COALESCE é resolvido em Python e não no SELECT porque `nome_editado`
    precisa dizer de qual das duas fontes o valor veio, e um COALESCE no SQL
    entregaria só o resultado.
    """
    linha = _linha("010103040755", "5", "EWERTON PAULA")
    linha["nome_exibicao"] = "Antonio"

    with _com_linhas([linha]):
        perfil = resolver_perfil("antonio.vaz@ache.com.br")

    assert perfil.nome == "Antonio"
    assert perfil.nome_editado is True


def test_sem_edicao_o_nome_vem_da_simv():
    with _com_linhas([_linha("010103040755", "5", "EWERTON PAULA")]):
        perfil = resolver_perfil("antonio.vaz@ache.com.br")

    assert perfil.nome == "ANTONIO VAZ"
    assert perfil.nome_editado is False


class _ConnGravacao:
    """Conexão falsa que separa o SELECT do cadastro do MERGE de gravação.

    Guarda os SQLs e os parâmetros recebidos para os testes verificarem o que
    foi de fato enviado ao banco, principalmente que a matrícula gravada veio
    da consulta e não do corpo da requisição.
    """

    def __init__(self, cadastro, linhas_finais):
        self._cadastro = cadastro
        self._linhas_finais = linhas_finais
        self.sqls = []
        self.parametros = []
        self.commits = 0

    def execute(self, sql, parametros=None):
        texto = str(sql)
        self.sqls.append(texto)
        self.parametros.append(parametros or {})
        if "MERGE" in texto:
            return _FakeResult([])
        if "FROM tb_propagandistas p" in texto:
            return _FakeResult(self._linhas_finais)
        return _FakeResult([self._cadastro] if self._cadastro else [])

    def commit(self):
        self.commits += 1

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _EngineGravacao:
    def __init__(self, conn):
        self._conn = conn

    def connect(self):
        return self._conn


def test_gravar_nome_usa_a_matricula_do_cadastro_e_nao_do_corpo():
    """A matrícula nunca vem do cliente.

    Aceitar identificador do corpo permitiria que uma pessoa editasse o perfil
    de outra. Pré-requisito 3 do item 1.3.
    """
    from backend.app.auth.perfil import gravar_nome

    cadastro = {"rep_matricula": "184480", "rep_nome": "ANTONIO VAZ"}
    linha = _linha("010103040755", "5", "EWERTON PAULA")
    linha["nome_exibicao"] = "Antonio"
    conn = _ConnGravacao(cadastro, [linha])

    with patch(
        "backend.app.auth.perfil._get_engine",
        return_value=_EngineGravacao(conn),
    ):
        perfil = gravar_nome("antonio.vaz@ache.com.br", "Antonio")

    merge = next(p for s, p in zip(conn.sqls, conn.parametros) if "MERGE" in s)
    assert merge["matricula"] == "184480"
    # NOME_ORIGEM_NA_EDICAO guarda o que a SIMV dizia na hora da edição, para
    # dar para descobrir depois que o nome oficial mudou.
    assert merge["origem_nome"] == "ANTONIO VAZ"
    assert conn.commits == 1
    assert perfil.nome == "Antonio"


def test_gravar_nome_sem_cadastro_devolve_404():
    from backend.app.auth.perfil import gravar_nome

    conn = _ConnGravacao(None, [])

    with patch(
        "backend.app.auth.perfil._get_engine",
        return_value=_EngineGravacao(conn),
    ):
        with pytest.raises(HTTPException) as excecao:
            gravar_nome("fulano.naoexiste@ache.com.br", "Fulano")

    assert excecao.value.status_code == 404
    # Nada pode ser gravado para um e-mail sem cadastro.
    assert not any("MERGE" in sql for sql in conn.sqls)


def test_nome_em_branco_e_tratado_como_desfazer_edicao():
    """A interface manda string vazia quando a pessoa apaga o campo e salva.

    Vazio, espaço e nulo significam a mesma coisa: voltar ao nome da SIMV. Sem
    a normalização, um nome em branco seria gravado e a tela ficaria sem nome.
    """
    from backend.app.schemas.perfil import PerfilUpdateRequest

    assert PerfilUpdateRequest(nome="").nome is None
    assert PerfilUpdateRequest(nome="   ").nome is None
    assert PerfilUpdateRequest(nome=None).nome is None
    assert PerfilUpdateRequest(nome="  Antonio  ").nome == "Antonio"


def test_nome_acima_do_limite_e_rejeitado():
    """Limite de 60 caracteres.

    O maior REP_NOME real tem 22 caracteres e a média é 13,7 (2.153 registros,
    medidos em 07/08/2026). O limite dá folga sem deixar o campo virar texto
    livre.
    """
    from pydantic import ValidationError

    from backend.app.schemas.perfil import PerfilUpdateRequest

    with pytest.raises(ValidationError):
        PerfilUpdateRequest(nome="A" * 61)


# ------------------------------------------------------------------- bloco 3


def test_bloco_3_vem_da_mesma_linha_do_perfil():
    """Cargo, regional, UF e linha saem do mesmo SELECT, sem consulta extra.

    Foi o que tornou o bloco 3 barato: os quatro campos já estavam na linha
    que `resolver_perfil` buscava para montar a identidade.
    """
    with _com_linhas([_linha("010103040755", "5", "EWERTON PAULA")]):
        perfil = resolver_perfil("antonio.vaz@ache.com.br")

    assert perfil.cargo == "Propagandista"
    assert perfil.regional == "SUL"
    assert perfil.uf == "RS"
    assert perfil.linha_nome == "LINHA 5"
    # Supervisor é o gerente distrital, confirmado por George em 07/08/2026.
    assert perfil.atribuicoes[0].gd_nome == "EWERTON PAULA"


def test_cidades_e_especialidades_viram_lista_preservando_a_ordem():
    """A ordem é a da origem, por número de médicos decrescente.

    Ela define quais entram nas três que a tela mostra, então inverter ou
    ordenar alfabeticamente aqui mudaria o que o propagandista vê.
    """
    with _com_linhas([_linha("010103040755", "5", "EWERTON PAULA")]):
        perfil = resolver_perfil("antonio.vaz@ache.com.br")

    assert perfil.cidades == ["SANTA MARIA", "SANTIAGO", "SÃO BORJA", "ITAQUI"]
    assert perfil.especialidades == ["CLINICO GERAL", "CARDIOLOGIA"]


def test_setor_sem_correspondencia_no_salesfarma_devolve_listas_vazias():
    """Um setor de 2.153 não tem correspondência e fica com as colunas nulas.

    Lista vazia é o resultado correto, e a interface mostra não disponível. O
    caso real é a matrícula 181657, registrado como P15.
    """
    linha = _linha("010101010054", "4", "EWERTON PAULA")
    linha["cidades_setor"] = None
    linha["especialidades_setor"] = None

    with _com_linhas([linha]):
        perfil = resolver_perfil("antonio.vaz@ache.com.br")

    assert perfil.cidades == []
    assert perfil.especialidades == []


def test_primeiro_acesso_nao_tem_data_anterior():
    with _com_linhas([_linha("010103040755", "5", "EWERTON PAULA")]):
        perfil = resolver_perfil("antonio.vaz@ache.com.br")

    assert perfil.dt_acesso_anterior is None


def test_registrar_acesso_desloca_o_atual_para_o_anterior():
    """O MERGE move DT_ACESSO_ATUAL para DT_ACESSO_ANTERIOR antes de carimbar.

    É isso que faz a tela mostrar o login anterior e não o em curso, que
    apareceria sempre como "agora".
    """
    from backend.app.auth.perfil import registrar_acesso

    conn = _ConnGravacao(None, [])

    with patch(
        "backend.app.auth.perfil._get_engine",
        return_value=_EngineGravacao(conn),
    ):
        registrar_acesso("antonio.vaz@ache.com.br")

    merge = next(sql for sql in conn.sqls if "MERGE" in sql)
    # Alvo do UPDATE SET sem qualificação (Postgres MERGE não aceita
    # `destino.coluna =` no lado esquerdo, só no direito, ao contrário do
    # Databricks — achado em teste de fumaça real em 26/08/2026, ver
    # docs/context/decisions-log.md).
    assert "dt_acesso_anterior = destino.dt_acesso_atual" in merge
    # A matrícula do INSERT sai do próprio USING, não de parâmetro: a
    # Identidade montada no login não carrega matrícula.
    assert "MAX(rep_matricula)" in merge
    assert conn.commits == 1


def test_falha_ao_registrar_acesso_nao_derruba_o_login():
    """Registrar acesso é conveniência de tela, não parte da autenticação.

    Impedir alguém de entrar no portal por causa de uma escrita de perfil
    seria trocar um problema pequeno por um grande.
    """
    from backend.app.auth.perfil import registrar_acesso

    with patch(
        "backend.app.auth.perfil._get_engine",
        side_effect=RuntimeError("banco fora do ar"),
    ):
        registrar_acesso("antonio.vaz@ache.com.br")  # não levanta


# ------------------------------------------------------------------- bloco 2


def test_contagens_vem_na_mesma_consulta_da_identidade():
    """Uma ida só ao warehouse, e não duas.

    Cada consulta custa perto de 0,7s mesmo com a engine aberta, medido em
    07/08/2026. Juntar levou o carregamento da aba de 1,53s para 0,88s.
    """
    with _com_linhas([_linha("010103040755", "5", "EWERTON PAULA")]) as engine:
        perfil = resolver_perfil("antonio.vaz@ache.com.br")

    assert perfil.medicos_no_painel == 392
    assert perfil.recomendacoes_pendentes == 134
    assert engine.consultas == 1, "a aba deve fazer uma consulta só"


def test_consulta_filtra_status_e_ciclo():
    """Os filtros que hoje não mudam resultado, e é por isso que têm teste.

    Só existe o ciclo 202608 e tudo está PENDENTE, então uma remoção acidental
    passaria despercebida até a primeira carga de setembro, aparecendo como
    número inflado que ninguém saberia explicar.
    """
    from backend.app.auth.perfil import _SQL_COM_RESUMO

    consulta = " ".join(_SQL_COM_RESUMO.split())
    assert "STATUS_RECOMENDACAO = 'PENDENTE'" in consulta
    assert (
        "CICLO_RECOMENDACAO = ( SELECT MAX(CICLO_RECOMENDACAO) "
        "FROM tb_recomendacoes_painel_historico )" in consulta
    )
    assert (
        "CICLO_REFERENCIA = ( SELECT MAX(CICLO_REFERENCIA) "
        "FROM tb_ranking_medicos_validacao )" in consulta
    )
    # Os setores saem da própria consulta, e é isso que permite juntar as
    # três contagens: painel, pendentes e especialidades predominantes.
    assert consulta.count("SETOR IN (SELECT setor FROM pessoa)") == 3
    # Atributo do setor, repetido em todas as linhas dele: o MAX agrupado
    # devolve o valor, não um máximo de verdade.
    assert "MAX(QTD_MEDICOS_PAINEL_SETOR)" in consulta


def test_soma_cobre_quem_atende_mais_de_um_setor():
    """O resumo descreve a carteira inteira, não a de um setor escolhido por nós.

    A soma acontece no SQL, pelo `IN` com os dois setores da pessoa. São 5
    casos assim em 07/08/2026.
    """
    with _com_linhas(
        [
            _linha("010103030155", "5", "DENISE CAETANO"),
            _linha("010103040755", "5", "EWERTON PAULA"),
        ]
    ):
        perfil = resolver_perfil("antonio.vaz@ache.com.br")

    assert len(perfil.atribuicoes) == 2
    # O CROSS JOIN repete a contagem em cada linha; o valor é o da soma, não o
    # dobro dela.
    assert perfil.medicos_no_painel == 392


def test_falha_no_resumo_nao_derruba_o_perfil():
    """Juntar as consultas amarra o perfil às tabelas de ranking e recomendação.

    Elas são reescritas por job. Sem o caminho de recuo, um problema nelas
    deixaria a pessoa sem ver nem o próprio nome.
    """
    linha_sem_resumo = _linha("010103040755", "5", "EWERTON PAULA")
    del linha_sem_resumo["medicos_no_painel"]
    del linha_sem_resumo["recomendacoes_pendentes"]

    class _EngineQueFalhaNaPrimeira:
        """Erra na consulta com resumo e responde na consulta sem resumo."""

        def __init__(self):
            self.consultas = 0

        def connect(self):
            engine = self

            class _Conn:
                def execute(self, sql, *_a, **_k):
                    engine.consultas += 1
                    # Marca só a query COM resumo (painel/pendentes), não o
                    # `CROSS JOIN tb_renovai_parametros` que existe nas duas
                    # variantes desde a Fase 3.5 (26/08/2026) — ver
                    # _CAMPOS_PESSOA, compartilhado por _SQL_COM_RESUMO e
                    # _SQL_SEM_RESUMO.
                    if "tb_ranking_medicos_validacao" in str(sql):
                        raise RuntimeError("tabela de ranking indisponível")
                    return _FakeResult([linha_sem_resumo])

                def __enter__(self):
                    return self

                def __exit__(self, *_a):
                    return False

            return _Conn()

    engine = _EngineQueFalhaNaPrimeira()

    with patch("backend.app.auth.perfil._get_engine", return_value=engine):
        perfil = resolver_perfil("antonio.vaz@ache.com.br")

    assert perfil.nome == "ANTONIO VAZ"
    assert perfil.medicos_no_painel is None
    assert perfil.recomendacoes_pendentes is None
    assert engine.consultas == 2, "tentou com resumo e recuou para sem resumo"


# --- Franquias da linha e limite do painel ---------------------------------


def test_franquias_saem_da_linha_de_produtos_e_nao_do_setor():
    """A linha 5 é Osteo, Respiratório e Oftalmo.

    O campo antigo, `especialidades`, descrevia o setor e continua existindo.
    O novo descreve a linha, que é outra coisa: a mesma franquia aparece em
    mais de uma linha e o setor não determina nenhuma delas.
    """
    with _com_linhas([_linha("010103040755", "5", "EWERTON PAULA")]):
        perfil = resolver_perfil("antonio.vaz@ache.com.br")

    assert perfil.franquias_linha == ["Osteo", "Respiratório", "Oftalmo"]
    # O campo de setor segue intacto, com o conteúdo da mock.
    assert perfil.especialidades == ["CLINICO GERAL", "CARDIOLOGIA"]


def test_linha_desconhecida_devolve_lista_vazia_e_nao_derruba_o_perfil():
    """Uma linha 7 criada pela Aché sem atualizar o de-para não pode dar erro.

    A tela mostra não disponível, e o resto do perfil continua carregando.
    """
    linha = _linha("010103040755", "7", "EWERTON PAULA")
    with _com_linhas([linha]):
        perfil = resolver_perfil("antonio.vaz@ache.com.br")

    assert perfil.franquias_linha == []
    assert perfil.matricula == "184480"


def test_limite_do_painel_e_o_padrao_unico_da_tabela_de_parametros():
    """Desde 18/09/2026 não existe limite por propagandista.

    O valor vem só de tb_renovai_parametros. Uma coluna LIMITE_PAINEL que ainda
    exista na linha, por dado antigo, não pode influenciar: é o que este teste
    garante ao colocá-la no mock e esperar que seja ignorada.
    """
    linha = _linha("010103040755", "5", "EWERTON PAULA")
    linha["limite_painel"] = 450  # resto de dado antigo, deve ser ignorado
    with _com_linhas([linha]):
        perfil = resolver_perfil("antonio.vaz@ache.com.br")

    assert perfil.limite_painel == 300
    assert not hasattr(perfil, "limite_painel_personalizado")


def test_limite_cai_no_literal_quando_a_tabela_de_parametros_nao_responde():
    linha = _linha("010103040755", "5", "EWERTON PAULA")
    linha["limite_painel_padrao"] = None
    with _com_linhas([linha]):
        perfil = resolver_perfil("antonio.vaz@ache.com.br")

    assert perfil.limite_painel == 300


def test_especialidades_predominantes_vem_da_consulta_de_resumo():
    with _com_linhas([_linha("010103040755", "5", "EWERTON PAULA")]):
        perfil = resolver_perfil("antonio.vaz@ache.com.br")

    assert perfil.especialidades_predominantes == ["CLINICA GERAL", "CARDIOLOGIA"]


def test_especialidades_predominantes_vazia_sem_visita_no_periodo():
    linha = _linha("010103040755", "5", "EWERTON PAULA")
    linha["especialidades_predominantes"] = None
    with _com_linhas([linha]):
        perfil = resolver_perfil("antonio.vaz@ache.com.br")

    assert perfil.especialidades_predominantes == []


def test_consulta_de_predominantes_exclui_medico_sem_especialidade_e_limita_a_duas():
    """Medido em 18/09/2026: em 4,3% dos setores "(sem especialidade)" ficaria
    entre as duas primeiras. Não é informação para o propagandista."""
    from backend.app.auth.perfil import _SQL_COM_RESUMO

    consulta = " ".join(_SQL_COM_RESUMO.split())
    assert "COUNT(DISTINCT vc.UFCRM)" in consulta
    assert "m.ESPECIALIDADE IS NOT NULL AND m.ESPECIALIDADE <> ''" in consulta
    assert "DATE_SUB(CURRENT_DATE(), 365)" in consulta
    assert "ORDER BY medicos DESC, especialidade LIMIT 2" in consulta
