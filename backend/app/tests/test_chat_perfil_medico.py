"""Testes do perfil do médico em cards.

Sem rede e sem credencial: os dicionários abaixo são cópias fiéis do que a
consulta `SQL_PERFIL` devolveu em 09/08/2026, para os seis casos que cobrem
todos os ramos da narrativa. O objetivo é travar comportamento, não medir
integração.
"""

from unittest.mock import patch

import pytest

from backend.app.chat import perfil_medico as pm

# Alguns testes deste arquivo passam por resolver_email_autenticado (via
# TestClient), que agora checa STATUS_ACESSO antes de tudo — não é o que
# este arquivo testa. Fixture compartilhada em conftest.py.
pytestmark = pytest.mark.usefixtures("liberar_acesso_por_padrao")

# --------------------------------------------------------------------------- #
# Casos reais capturados da tabela em 09/08/2026
# --------------------------------------------------------------------------- #

ADICIONAR = {
    "NOME_MEDICO": "ZURISADAY BASABE GARCIA", "UFCRM": "PR0051890", "LINHA_PRODUTO": "3",
    "POSICAO_RANKING_SETOR": 336, "PONTOS": 87.0, "QTD_MEDICOS_PAINEL_SETOR": 375,
    "RECOMENDACAO": "ADICIONAR", "MOTIVO_RECOMENDACAO": "Fora do painel e dentro dos 400 prioritarios",
    "MESES_DESDE_ULTIMA_VISITA": None, "CRITERIO_DA_SAIDA": None,
    "TOP1_CATEGORIA": "Medicamentos para tratar depressão e ansiedade", "TOP1_PCT": 20.8,
    "TOP2_CATEGORIA": "Medicamentos para colesterol alto", "TOP2_PCT": 14.6,
    "TOP3_CATEGORIA": "Medicamentos para controlar açúcar no sangue", "TOP3_PCT": 12.5,
    "TOP1_PRODUTO": "SINVASTATINA LNI", "TOP2_PRODUTO": "CLONAZEPAM LNI", "TOP3_PRODUTO": "FLUOXETINA LNI",
    "JANELA_USADA": "ultimo periodo", "PCT_ACHE": 2.1,
    "PRODUTO_RECOMENDADO": "EXODUS", "CATEGORIA_DO_PRODUTO": "Medicamentos para tratar depressão e ansiedade",
    "POSICAO_DA_CATEGORIA_DO_PRODUTO": "primeira", "REC_E_TOP1": 0,
    "PRODUTO2": None, "PRODUTO2_CATEGORIA": None, "PRODUTO3": None, "PRODUTO3_CATEGORIA": None,
    "ORIGEM_DA_RECOMENDACAO": "MATCH_DIRETO", "JA_PRESCREVE_O_PRODUTO": 0,
    "PRODUTO_ACHE_OUTRA_LINHA": "EXODUS", "LINHA_DO_PRODUTO_ACHE": "3",
}

JA_E_O_TOP1 = dict(
    ADICIONAR,
    NOME_MEDICO="JENE GREYCE OLIVEIRA DA CRUZ", UFCRM="AC0000495", LINHA_PRODUTO="4",
    POSICAO_RANKING_SETOR=93, PONTOS=142.0, PCT_ACHE=36.6,
    TOP1_CATEGORIA="Medicamentos para desinflamar nariz", TOP1_PCT=34.1,
    TOP1_PRODUTO="DECADRON", PRODUTO_RECOMENDADO="DECADRON",
    CATEGORIA_DO_PRODUTO="Medicamentos para desinflamar nariz",
    REC_E_TOP1=1, JA_PRESCREVE_O_PRODUTO=1,
    PRODUTO2="NOVAMOX", PRODUTO2_CATEGORIA="Medicamentos para infecções bacterianas",
    PRODUTO3="CORUS", PRODUTO3_CATEGORIA="Medicamentos para tratar pressão alta",
)

SAIU_DO_CORTE = dict(
    ADICIONAR,
    NOME_MEDICO="LEVI DA COSTA LOPES", UFCRM="AM0013508", LINHA_PRODUTO="2",
    POSICAO_RANKING_SETOR=401, PONTOS=12.0, RECOMENDACAO="REMOVER",
    MOTIVO_RECOMENDACAO="No painel, painel com 465 medicos. Remocao por ranking (posicao 401)",
    CRITERIO_DA_SAIDA="saiu do corte", PCT_ACHE=1.1,
    PRODUTO_RECOMENDADO="REVANGE", CATEGORIA_DO_PRODUTO="Medicamentos para aliviar dor e febre",
    POSICAO_DA_CATEGORIA_DO_PRODUTO="fora das tres", REC_E_TOP1=0, JA_PRESCREVE_O_PRODUTO=0,
)

SEM_VISITA_9M = dict(
    SAIU_DO_CORTE,
    NOME_MEDICO="LIANA DINIZ SANTOS", UFCRM="MA0000777", POSICAO_RANKING_SETOR=1,
    MOTIVO_RECOMENDACAO="No painel. Remocao por visita (ultima ha 9 meses ou mais)",
    CRITERIO_DA_SAIDA="dentro do corte sem visita", MESES_DESDE_ULTIMA_VISITA=9,
    PCT_ACHE=23.1, JA_PRESCREVE_O_PRODUTO=1,
)

SEM_VISITA_REGISTRADA = dict(
    SEM_VISITA_9M,
    NOME_MEDICO="WELINGTON RABELO DA ROCHA", UFCRM="MG0009499",
    CRITERIO_DA_SAIDA="sem visita registrada", MESES_DESDE_ULTIMA_VISITA=0, PCT_ACHE=9.3,
)

SEM_PRODUTO_NA_LINHA = dict(
    ADICIONAR,
    NOME_MEDICO="MARCO ANTONIO SCHNEIDER LIMPIAS", UFCRM="SP0240800", LINHA_PRODUTO="5",
    PCT_ACHE=0.0, PRODUTO_RECOMENDADO=None, CATEGORIA_DO_PRODUTO=None,
    POSICAO_DA_CATEGORIA_DO_PRODUTO=None, REC_E_TOP1=0,
    PRODUTO_ACHE_OUTRA_LINHA="ETIRA", LINHA_DO_PRODUTO_ACHE="3",
)

# Permanência é o maior grupo da tabela, 647.115 linhas, e não tinha caso
# travado até 10/08/2026. Os dois abaixo saíram da consulta real nessa data.
CONTINUAR = {
    "NOME_MEDICO": "CARLOS AUGUSTO BEYRUTH BORGES", "UFCRM": "AC0000099", "LINHA_PRODUTO": "1",
    "POSICAO_RANKING_SETOR": 125, "PONTOS": 1114.24, "QTD_MEDICOS_PAINEL_SETOR": 470,
    "RECOMENDACAO": "CONTINUAR",
    "MOTIVO_RECOMENDACAO": "No painel e mantido. Nao atende aos criterios de remocao de posicao, tamanho do painel ou tempo de visita.",
    "MESES_DESDE_ULTIMA_VISITA": 0, "CRITERIO_DA_SAIDA": None,
    "TOP1_CATEGORIA": "Medicamentos para infecções bacterianas", "TOP1_PCT": 33.1,
    "TOP2_CATEGORIA": "Medicamentos para dor e inflamação", "TOP2_PCT": 12.7,
    "TOP3_CATEGORIA": "Medicamentos para inflamação nos olhos", "TOP3_PCT": 11.0,
    "TOP1_PRODUTO": "CIBEX", "TOP2_PRODUTO": "TERCEN", "TOP3_PRODUTO": "ALEVO",
    "JANELA_USADA": "ultimo periodo", "PCT_ACHE": 15.3,
    "PRODUTO_RECOMENDADO": "CORUS", "CATEGORIA_DO_PRODUTO": "Medicamentos para tratar pressão alta",
    "POSICAO_DA_CATEGORIA_DO_PRODUTO": "fora das tres",
    "CICLOS_NO_PAINEL_JANELA": 3, "DATA_ULTIMA_VISITA": "2026-08-03",
    "ULTIMO_PERIODO_NA_CATEGORIA": 202602, "QTD_CATEGORIAS": 28, "QTD_PRODUTOS": 82,
    "REC_E_TOP1": 0, "ORIGEM_DA_RECOMENDACAO": "MATCH_DIRETO",
    "JA_PRESCREVE_O_PRODUTO": 1, "PRESCREVE_NO_PERIODO": 0,
    "PRODUTO2": "CORUS H", "PRODUTO2_CATEGORIA": "Medicamentos para tratar pressão alta",
    "PRODUTO3": "DIVENA", "PRODUTO3_CATEGORIA": "Medicamentos para tratar úlceras estomacais",
    "PRODUTO_ACHE_OUTRA_LINHA": "MEFEX", "LINHA_DO_PRODUTO_ACHE": "4",
}

# Médico no painel sem uma única prescrição em janela nenhuma. São 14.525
# linhas na tabela, e a resposta afirmava sobre elas duas coisas falsas: que a
# posição vinha do que o médico prescreve, e que quase todo o volume ia para
# outras marcas.
SEM_PRESCRICAO = dict(
    CONTINUAR,
    NOME_MEDICO="JOSEPHC JOSEM RODRIGUEZ BISMARCK", UFCRM="AC0003365", LINHA_PRODUTO="5",
    POSICAO_RANKING_SETOR=314, PONTOS=72.54, QTD_MEDICOS_PAINEL_SETOR=495,
    TOP1_CATEGORIA=None, TOP1_PCT=None, TOP2_CATEGORIA=None, TOP2_PCT=None,
    TOP3_CATEGORIA=None, TOP3_PCT=None,
    TOP1_PRODUTO=None, TOP2_PRODUTO=None, TOP3_PRODUTO=None,
    JANELA_USADA="historico", PCT_ACHE=None,
    PRODUTO_RECOMENDADO=None, CATEGORIA_DO_PRODUTO=None, POSICAO_DA_CATEGORIA_DO_PRODUTO=None,
    CICLOS_NO_PAINEL_JANELA=2, DATA_ULTIMA_VISITA=None,
    ULTIMO_PERIODO_NA_CATEGORIA=None, QTD_CATEGORIAS=None, QTD_PRODUTOS=None,
    ORIGEM_DA_RECOMENDACAO="SEM_RECOMENDACAO_NA_LINHA", JA_PRESCREVE_O_PRODUTO=0,
    PRODUTO2=None, PRODUTO2_CATEGORIA=None, PRODUTO3=None, PRODUTO3_CATEGORIA=None,
    PRODUTO_ACHE_OUTRA_LINHA=None, LINHA_DO_PRODUTO_ACHE=None,
)

TODOS = [ADICIONAR, JA_E_O_TOP1, SAIU_DO_CORTE, SEM_VISITA_9M, SEM_VISITA_REGISTRADA,
         SEM_PRODUTO_NA_LINHA, CONTINUAR, SEM_PRESCRICAO]


# --------------------------------------------------------------------------- #
# Roteador
# --------------------------------------------------------------------------- #

# As 16 formulações medidas em 09/08/2026. O arquivo versionado trazia 11, o
# que reportava cobertura maior do que a travada em teste.
MAPEADAS = [
    ("PR0051890 setor 010101050553", "briefing_medico"),
    ("51890 setor 010101050553", "briefing_medico"),
    ("ZURISADAY BASABE GARCIA setor 010101050553", "briefing_medico"),
    ("Zurisaday Basabe Garcia setor 010101050553", "briefing_medico"),
    ("me fala do medico PR0051890, setor 010101050553", "briefing_medico"),
    ("o que levar para o dr PR0051890 no setor 010101050553", "briefing_medico"),
    ("quais medicos devo incluir no setor 010101050553", "inclusoes"),
    ("quem eu deveria adicionar no painel do setor 010101050553", "inclusoes"),
    ("quais medicos devo retirar do setor 010107030252", "exclusoes"),
    ("quem sai do meu painel, setor 010107030252", "exclusoes"),
    ("quais categorias mais aparecem no setor 010101050553", "categorias"),
    ("quais areas terapeuticas do setor 010101050553", "categorias"),
    ("quais produtos tenho para oferecer no setor 010101050553", "produtos"),
    ("qual o portfolio do setor 010101050553", "produtos"),
    ("como esta o setor 010101050553", "resumo_setor"),
    ("010101050553", "resumo_setor"),
]

CAUDA = [
    "quantos medicos do setor 010101050553 prescrevem antidepressivos e ainda nao usam EXODUS",
    "compare o setor 010101050553 com a media da linha 3",
    "qual a evolucao da participacao Ache no setor 010101050553 nos ultimos meses",
    "quais medicos do setor 010101050553 estao sem visita ha mais de 6 meses",
    "me da os 5 medicos com maior potencial de crescimento no setor 010101050553",
    "qual cidade do setor 010101050553 concentra mais prescricao",
]


def test_roteador_classifica_as_mapeadas():
    for pergunta, esperado in MAPEADAS:
        assert pm.rotear(pergunta).intencao == esperado, pergunta


def test_roteador_manda_a_cauda_para_o_llm():
    """O atalho ingênuo de 'tem setor, logo é resumo' engolia estas seis e
    respondia a coisa errada com confiança. Errar para o lado de chamar o LLM
    é barato; errar para o lado de responder errado, não."""
    for pergunta in CAUDA:
        assert pm.rotear(pergunta).intencao is None, pergunta


def test_roteador_reconhece_nome_capitalizado():
    """A versão anterior só reconhecia caixa alta, como vem da tabela, e perdia
    o nome digitado normalmente pelo propagandista."""
    r = pm.rotear("Zurisaday Basabe Garcia setor 010101050553")
    assert r.intencao == "briefing_medico"
    assert r.nome == "Zurisaday Basabe Garcia"


def test_roteador_nao_confunde_inicio_de_frase_com_nome():
    assert pm.rotear("Quais Medicos devo incluir no setor 010101050553").intencao == "inclusoes"


def test_payload_nao_devolve_a_linha_bruta():
    """A linha da consulta tem coluna interna e motivo em texto de origem. O
    front recebe só o que precisa."""
    p = pm.montar_payload(ADICIONAR)
    assert set(p.identificacao) == {"ufcrm", "nome_medico", "linha_produto"}
    serializado = p.model_dump_json()
    for interno in ("MOTIVO_RECOMENDACAO", "CRITERIO_DA_SAIDA", "ORIGEM_DA_RECOMENDACAO", "PONTOS"):
        assert interno not in serializado, interno


def test_janela_do_ano_nao_traz_produto_do_historico():
    """Produto só existe nas janelas do ciclo e do histórico. Na janela do ano
    a consulta devolve nulo, em vez de misturar períodos."""
    caso = dict(ADICIONAR, JANELA_USADA="ano vigente",
                TOP1_PRODUTO=None, TOP2_PRODUTO=None, TOP3_PRODUTO=None,
                TOP2_PCT=None, TOP3_PCT=None)
    texto = pm.bloco_prescricao(caso)
    assert "mais aparecem nas prescrições" not in texto
    assert "considerando o ano" in texto


def test_roteador_extrai_identificadores():
    r = pm.rotear("PR0051890 setor 010101050553")
    assert r.setor == "010101050553"
    assert r.ufcrm == "PR0051890"


# --------------------------------------------------------------------------- #
# Formato da narrativa
# --------------------------------------------------------------------------- #


def test_nenhum_texto_flexiona_genero():
    """A tabela não informa sexo e a fonte alternativa cobre 39,6%. Nenhuma
    resposta pode assumir masculino ou feminino."""
    proibidos = (" ele ", " ela ", " dele", " dela", "o médico ", "a médica ")
    for caso in TODOS:
        texto = " " + pm.narrativa(caso).lower() + " "
        for termo in proibidos:
            assert termo not in texto, f"{caso['NOME_MEDICO']}: {termo}"


def test_nenhum_valor_cru_de_coluna_vaza():
    for caso in TODOS:
        texto = pm.narrativa(caso)
        for termo in ("ADICIONAR", "CONTINUAR", "REMOVER", "MATCH_DIRETO", "REC_E_TOP1"):
            assert termo not in texto, f"{caso['NOME_MEDICO']}: {termo}"


def test_percentual_usa_virgula():
    """O separador decimal é vírgula em todo texto que vai para o cliente.

    O 20,8% que este teste media era da categoria mais prescrita, e a categoria
    saiu do bloco em 20/08/2026 junto com o percentual dela, por decisão de
    George: o bloco passou a listar medicamento, e um percentual sem a classe ao
    lado não teria referente.

    A regra continua valendo, e agora é medida na participação Aché, que é o
    percentual que sobrou na narrativa."""
    assert "2,1%" in pm.narrativa(ADICIONAR)
    assert "2.1%" not in pm.narrativa(ADICIONAR)
    assert "20.8%" not in pm.narrativa(ADICIONAR)


def test_saida_e_deterministica():
    """Três execuções idênticas. É o que o LLM não entregou em nenhum dos sete
    modelos medidos em 09/08/2026."""
    for caso in TODOS:
        assert len({pm.narrativa(caso) for _ in range(3)}) == 1


def test_os_dois_criterios_de_remover_sao_opostos():
    corte = pm.bloco_decisao(SAIU_DO_CORTE)
    visita = pm.bloco_decisao(SEM_VISITA_9M)
    assert "passou do limite" in corte and "dentro do limite" not in corte
    assert "dentro do limite" in visita and "não recebe visita há 9 meses" in visita
    # Quem é primeiro do setor não pode ser descrito como fraco.
    assert "caiu" not in visita


def test_nenhum_texto_cita_o_tamanho_do_corte():
    """Decisão de George em 09 e 10/08/2026, e o número seria falso: só 12 dos
    2.153 setores têm painel de exatamente 400, e os reais vão de 251 a 596."""
    for caso in TODOS:
        assert "400" not in pm.narrativa(caso), caso["NOME_MEDICO"]


def test_nome_do_medico_sai_com_inicial_maiuscula():
    """A tabela guarda em caixa alta, e caixa alta na tela lê como grito."""
    assert pm.montar_payload(ADICIONAR).cards[0].name == "Zurisaday Basabe Garcia"
    # Partícula no meio do nome fica em minúscula.
    assert "Levi da Costa Lopes" in pm.bloco_decisao(SAIU_DO_CORTE)
    assert "Se for visitar Zurisaday Basabe Garcia" in pm.bloco_acao(ADICIONAR)
    # Apóstrofo aparece na tabela de histórico, que alimenta a lista de
    # sugestões, e a letra seguinte também é maiúscula.
    assert pm._nome_proprio("DANIELLE LOPES ALVES D'AMICO") == "Danielle Lopes Alves D'Amico"


def test_sem_visita_registrada_nao_inventa_meses():
    texto = pm.bloco_decisao(SEM_VISITA_REGISTRADA)
    assert "não tem visita registrada" in texto
    assert "meses" not in texto


def test_remover_entrega_a_acao_antes_da_leitura():
    """A decisão é do propagandista. A informação de visita vem completa e a
    leitura da base vem depois, nunca no lugar dela."""
    texto = pm.narrativa(SEM_VISITA_9M)
    assert "Se ainda assim for visitar" in texto
    assert texto.index("Se ainda assim for visitar") < texto.index("O perfil continua forte")


def test_zero_por_cento_nao_repete_a_linha_do_percentual():
    texto = pm.bloco_ache(SEM_PRODUTO_NA_LINHA)
    assert "Os medicamentos da Aché ainda não apareceram nas prescrições" in texto
    assert "representam" not in texto


def test_toda_frase_sobre_ache_diz_o_periodo():
    """A leitura é sempre de uma janela. Sem a marca de período, 1.032.248
    linhas afirmavam que o médico não prescreve Aché quando ele prescreveu no
    ano ou no histórico, medido em 10/08/2026."""
    for caso in TODOS:
        texto = pm.bloco_ache(caso)
        if not caso["TOP1_CATEGORIA"]:
            # Sem prescrição não há janela a datar, e a frase diz isso.
            assert "Não há prescrição registrada" in texto, caso["NOME_MEDICO"]
            continue
        assert any(p in texto for p in ("neste período", "neste ano", "no histórico")), caso["NOME_MEDICO"]


def test_a_frase_do_ache_muda_conforme_a_recomendacao():
    """Mesma informação, três usos. Decisão de George em 10/08/2026."""
    sem_ache = dict(ADICIONAR, PCT_ACHE=0.0)
    assert "Os medicamentos da Aché ainda não apareceram nas prescrições" in pm.bloco_ache(sem_ache)
    assert "Os medicamentos da Aché ainda não apareceram nas prescrições" in pm.bloco_ache(dict(sem_ache, RECOMENDACAO="CONTINUAR"))

    # Em saída a frase é seca, sem o "porém a recomendação vale".
    for caso in (SAIU_DO_CORTE, SEM_VISITA_9M):
        texto = pm.bloco_ache(dict(caso, PCT_ACHE=0.0))
        assert texto.startswith("Os medicamentos da Aché não apareceram nas prescrições neste período")
        assert "vale mesmo assim" not in texto


def test_remocao_nunca_elogia():
    """As quatro faixas de leitura são escritas para animar, de "há bastante
    espaço" a "a Aché já é forte aqui". Elogiar um médico que a resposta manda
    tirar derruba a própria recomendação. Decisão de George em 10/08/2026."""
    animo = ("espaço", "já aparece", "presença relevante", "já é forte", "trabalho é manter")
    for caso in TODOS:
        if caso["RECOMENDACAO"] != "REMOVER":
            continue
        for pct in (0.0, 2.1, 23.1, 40.0):
            texto = pm.bloco_ache(dict(caso, PCT_ACHE=pct))
            for termo in animo:
                assert termo not in texto, f"{caso['NOME_MEDICO']} com {pct}%: {termo}"


def test_ja_prescreveu_nao_contradiz_a_participacao_do_periodo():
    """A marca de já prescrever lê a base inteira, a participação lê a janela.
    Sem o "antes", o card diz que não houve Aché no período e o texto da visita
    diz que já prescreve o produto Aché. Em 218.695 de 2.548.243 linhas."""
    caso = dict(ADICIONAR, PCT_ACHE=0.0, JA_PRESCREVE_O_PRODUTO=1)
    assert "EXODUS já foi prescrito antes" in pm.bloco_acao(caso)
    assert "Os medicamentos da Aché ainda não apareceram nas prescrições" in pm.bloco_ache(caso)


def test_permanencia_justifica_pela_posicao_e_nao_pela_prescricao():
    """As três recomendações passam a dizer por quê, decisão de George em
    20/08/2026, revendo a de 10/08 que deixava a permanência sem causa.

    A ressalva de 10/08 vira redação, não desaparece: a frase cita a posição no
    ranking, que é fato da tabela, e nunca a origem dela. Dizer "sustentado pelo
    que prescreve" continua sendo falso para as 547 linhas de médico sem
    prescrição em janela nenhuma."""
    texto = pm.bloco_decisao(CONTINUAR)
    assert texto == (
        "Carlos Augusto Beyruth Borges deve seguir no seu painel "
        "pela posição no ranking do seu setor."
    )
    assert "sustentado pelo que prescreve" not in pm.bloco_decisao(SEM_PRESCRICAO)
    assert "prescreve" not in pm.bloco_decisao(SEM_PRESCRICAO)


def test_visita_avisa_quando_passa_de_dois_e_de_tres_meses():
    """O corte é de tempo, não de ranking: 17.075 linhas da base saem do painel
    só por ausência de visita, às vezes na posição 1 do setor."""
    from datetime import date, timedelta

    def com_visita(dias):
        caso = dict(CONTINUAR)
        caso["DATA_ULTIMA_VISITA"] = (date.today() - timedelta(days=dias)).isoformat()
        return pm.bloco_visita(caso)

    assert "Passou de dois meses" not in com_visita(30)
    assert "Passou de dois meses" in com_visita(70)
    assert "Passou de três meses" in com_visita(100)
    assert "Passou de dois meses" not in com_visita(100)


def test_nenhuma_abertura_repete_posicao_nem_pontos():
    """Os dois números ficam só no card, que aparece logo abaixo da mensagem.
    Decisão de George em 10/08/2026."""
    for caso in TODOS:
        texto = pm.bloco_decisao(caso)
        # A palavra pode aparecer, como em "chegou a essa posição", que aponta
        # para o card. O número é que não pode.
        assert f"posição {caso['POSICAO_RANKING_SETOR']}" not in texto, caso["NOME_MEDICO"]
        assert "pontos" not in texto, caso["NOME_MEDICO"]


def test_remocao_por_ranking_e_visita_conta_os_dois_motivos():
    """Quarto critério, 4.110 linhas, que eram lidas só como ranking. A mediana
    delas é de cinco meses sem visita, e esse motivo sumia da resposta."""
    caso = dict(SAIU_DO_CORTE, CRITERIO_DA_SAIDA="ranking e visita", MESES_DESDE_ULTIMA_VISITA=5)
    texto = pm.bloco_decisao(caso)
    assert "caiu no ranking" in texto and "não recebe visita há 5 meses" in texto
    # A leitura da base segue a do ranking, não a de quem sai só por visita.
    assert "retorno é maior com quem está acima no ranking" in pm.bloco_leitura(caso)


def test_remocao_traz_a_saida_e_a_visita_entre_as_respostas():
    """A intenção é que o propagandista pare de visitar. A orientação de visita
    continua existindo, mas só se ele disser que quer manter o médico."""
    p = pm.montar_payload(SAIU_DO_CORTE)
    chips = list(p.respostas.keys())
    assert chips[0] == pm.CHIP_POR_QUE_TIRAR
    assert pm.CHIP_VISITA not in chips
    assert pm.CHIP_MANTER in chips
    assert chips.index(pm.CHIP_MANTER) > chips.index(pm.CHIP_POR_QUE_TIRAR)
    # E a orientação completa continua lá, atrás da escolha.
    assert "leve REVANGE" in p.respostas[pm.CHIP_MANTER]


def test_justificativa_reune_o_que_sustenta_a_saida():
    texto = pm.bloco_justificativa(dict(SEM_VISITA_9M, CICLOS_NO_PAINEL_JANELA=3,
                                        DATA_ULTIMA_VISITA="2025-11-04"))
    assert "Não recebe visita há 9 meses" in texto
    assert "Ocupa uma vaga do seu painel há 3 ciclos" in texto
    assert "Última visita em 04/11/2025" in texto
    assert "O perfil continua forte" in texto
    # Fora de remoção ela não existe.
    assert pm.bloco_justificativa(CONTINUAR) == ""
    # Na saída por ranking a data da última visita não entra: ela apareceu numa
    # lista de "por que tirar" seis dias depois de o médico ter sido visitado.
    so_ranking = pm.bloco_justificativa(dict(SAIU_DO_CORTE, DATA_ULTIMA_VISITA="2026-08-04"))
    assert "Última visita" not in so_ranking


def test_bloco_de_relacao_so_existe_na_permanencia():
    assert pm.bloco_relacao(CONTINUAR)
    for caso in (ADICIONAR, SAIU_DO_CORTE, SEM_VISITA_9M):
        assert pm.bloco_relacao(caso) == "", caso["NOME_MEDICO"]


def test_bloco_de_relacao_traz_o_que_nao_existe_em_outro_lugar():
    texto = pm.bloco_relacao(CONTINUAR)
    assert "No seu painel há 3 ciclos, a janela inteira que a base cobre" in texto
    # A data absoluta saiu em 03/09/2026: a resposta já a traz na Memória de
    # Visitas, e o tempo relativo fica no bloco "Tempo sem visita".
    assert "Última visita" not in texto
    assert "Prescreveu em 28 categorias diferentes, com 82 produtos" in texto
    # A linha mais útil: quando o médico parou de prescrever na categoria do
    # produto que o propagandista vai levar.
    assert "Última prescrição em anti-hipertensivos, a categoria do CORUS, em fevereiro de 2026" in texto


def test_bloco_de_relacao_omite_linha_sem_dado():
    texto = pm.bloco_relacao(SEM_PRESCRICAO)
    assert "No seu painel há 2 ciclos" in texto
    assert "a janela inteira" not in texto
    assert "Sem visita registrada" in texto
    assert "categorias diferentes" not in texto
    assert "Última prescrição em" not in texto


def test_sem_prescricao_nenhuma_nao_promete_espaco():
    """Duas frases eram falsas para esses médicos: a causa da posição e o
    "quase todo o volume vai para outras marcas", sobre quem não tem volume."""
    texto = pm.bloco_ache(SEM_PRESCRICAO)
    assert texto.startswith("Não há prescrição registrada para Josephc Josem Rodriguez Bismarck")
    assert "espaço" not in texto


def test_cada_estado_do_produto_sugere_uma_visita_diferente():
    """Três estados, três conversas. Decisão de George em 10/08/2026: a resposta
    tem que dizer o que fazer, não repetir a mesma frase."""
    nunca = dict(ADICIONAR, JA_PRESCREVE_O_PRODUTO=0)
    assert "primeira apresentação" in pm.bloco_acao(nunca)

    agora = dict(ADICIONAR, JA_PRESCREVE_O_PRODUTO=1, PRESCREVE_NO_PERIODO=1)
    assert "visita é de manutenção" in pm.bloco_acao(agora)

    parou = dict(ADICIONAR, JA_PRESCREVE_O_PRODUTO=1, PRESCREVE_NO_PERIODO=0)
    assert "parou" in pm.bloco_acao(parou) and "o que mudou" in pm.bloco_acao(parou)

    # Sem a coluna de período a tabela não separa os dois, e a resposta assume
    # a limitação em vez de escolher no chute.
    hoje = dict(ADICIONAR, JA_PRESCREVE_O_PRODUTO=1)
    assert "a base não diz se ainda é" in pm.bloco_acao(hoje)


def test_oferece_produto_de_outra_linha_quando_e_mesmo_outra():
    """Dois tipos sempre, um da linha do propagandista e um de outra, os dois
    Aché. Decisão de George em 10/08/2026."""
    caso = dict(ADICIONAR, PRODUTO_ACHE_OUTRA_LINHA="NOVAMOX", LINHA_DO_PRODUTO_ACHE="4")
    assert "De outra linha, existe NOVAMOX, da linha 4." in pm.bloco_acao(caso)
    # O campo de origem é o melhor Aché de qualquer linha, então às vezes
    # repete o da linha do propagandista. Aí ele não entra.
    assert "De outra linha" not in pm.bloco_acao(ADICIONAR)


def test_rec_e_top1_comunica_resultado_e_abre_categoria_nova():
    texto = pm.bloco_acao(JA_E_O_TOP1)
    assert "já deu certo" in texto
    assert "NOVAMOX" in texto


def test_oferece_ate_tres_produtos_com_a_finalidade_de_cada():
    """Os produtos 2 e 3 vêm da aderência ao que o médico prescreve, não das
    categorias exibidas, então cada um precisa dizer para que serve."""
    caso = dict(ADICIONAR, PRODUTO2="TREZOR", PRODUTO2_CATEGORIA="Medicamentos para colesterol alto",
                PRODUTO3="CORUS", PRODUTO3_CATEGORIA="Medicamentos para tratar pressão alta")
    texto = pm.bloco_acao(caso)
    assert "EXODUS" in texto
    assert "Ainda na sua linha, você tem TREZOR, para colesterol alto, e CORUS, para tratar pressão alta." in texto


def test_produto_da_mesma_categoria_do_recomendado_sai_marcado():
    """Sem a marca, a lista parecia abrir uma alternativa nova quando estava
    repetindo a categoria da linha de cima. Acontece em 478.039 das 2.437.460
    linhas com segundo produto, medido em 10/08/2026."""
    caso = dict(ADICIONAR, PRODUTO2="LEXAPRO",
                PRODUTO2_CATEGORIA=ADICIONAR["CATEGORIA_DO_PRODUTO"], PRODUTO3=None)
    assert "LEXAPRO, também um antidepressivo" in pm.bloco_acao(caso)


def test_a_categoria_e_dita_no_singular_quando_descreve_um_produto():
    """Um produto não é "anti-hipertensivos", é "um anti-hipertensivo". As 109
    categorias da tabela são todas plurais, então sem a flexão o erro aparecia
    em toda resposta. Apontado por George em 10/08/2026."""
    caso = dict(ADICIONAR, CATEGORIA_DO_PRODUTO="Medicamentos para tratar pressão alta")
    assert "leve EXODUS, um anti-hipertensivo da linha 3." in pm.bloco_acao(caso)
    # Quando o texto da categoria não abre com substantivo no plural seguido de
    # "para", a flexão pegaria a expressão inteira e a frase nomeia a categoria.
    outra = dict(ADICIONAR, CATEGORIA_DO_PRODUTO="Medicamentos tônicos e revigorantes")
    assert "leve EXODUS, da categoria medicamentos tônicos e revigorantes" in pm.bloco_acao(outra)


def test_cada_frase_da_visita_tem_sujeito_e_ligacao_com_a_anterior():
    """A resposta era uma lista de frases soltas: "Está entre as três categorias
    de maior volume" não dizia o que estava. Apontado por George em 10/08/2026.
    Agora a categoria é sujeito, o produto é sujeito, e as duas se ligam."""
    texto = pm.bloco_acao(dict(ADICIONAR, JA_PRESCREVE_O_PRODUTO=1, PRESCREVE_NO_PERIODO=0))
    assert "Os antidepressivos são a categoria de maior volume" in texto
    assert "Dentro dessa categoria, EXODUS já foi prescrito antes e parou, então" in texto
    for linha in texto.split("\n"):
        assert not linha.startswith("Está "), linha


def test_a_posicao_da_categoria_diz_de_qual_periodo_fala():
    """A janela pode ser ciclo, ano ou histórico, e a frase muda junto. Sem a
    marca, a afirmação valeria para a vida toda do médico."""
    assert "nas prescrições deste período." in pm.bloco_acao(ADICIONAR)
    assert "nas prescrições deste ano." in pm.bloco_acao(dict(ADICIONAR, JANELA_USADA="ano vigente"))
    assert "nas prescrições do histórico." in pm.bloco_acao(dict(ADICIONAR, JANELA_USADA="historico"))


def test_lista_de_categorias_nao_mistura_com_e_sem_percentual():
    """Fora da janela do ciclo só a primeira tem percentual. Um item numerado e
    dois sem parece erro de sistema, então o percentual sai de todos."""
    caso = dict(ADICIONAR, JANELA_USADA="ano vigente", TOP2_PCT=None, TOP3_PCT=None)
    cats = pm._categorias(caso)
    assert len(cats) == 3
    assert all(c["pct"] is None for c in cats)
    texto = pm.bloco_prescricao(caso)
    assert "%" not in texto
    assert "considerando o ano" in texto


def test_resgate_de_outra_linha_e_declarado():
    texto = pm.bloco_acao(SEM_PRODUTO_NA_LINHA)
    assert "Não há produto da sua linha" in texto
    assert "ETIRA" in texto and "de outra linha" in texto


# --------------------------------------------------------------------------- #
# Payload de cards
# --------------------------------------------------------------------------- #


def test_payload_tem_os_tipos_do_prototipo():
    p = pm.montar_payload(ADICIONAR)
    tipos = [c.type for c in p.cards]
    assert tipos[0] == "doctor"
    assert "insight" in tipos
    # Sem card de sugestões desde 20/08/2026: a resposta vem inteira em blocos,
    # então o chip repetia o que a pessoa acabou de ler.
    assert "suggestions" not in tipos


def test_card_do_medico_traz_pontos_e_posicao():
    card = pm.montar_payload(ADICIONAR).cards[0]
    assert card.rank == "#336 no setor"
    assert card.score == 87.0
    assert card.status == "Recomendado para inclusão"


def test_card_traz_a_razao_curta_visivel():
    """Sem razão no card, o propagandista age sobre número sem critério, que é
    exatamente do que ele desconfia nas entrevistas."""
    card = pm.montar_payload(ADICIONAR).cards[0]
    assert "Prescreve principalmente" in card.summary
    assert "20,8%" in card.summary


def test_cada_chip_ja_vem_com_a_resposta_pronta():
    """O toque no chip não dispara consulta nem modelo: o texto viaja no mesmo
    payload, então é instantâneo e não pode contradizer o card."""
    p = pm.montar_payload(ADICIONAR)
    chips = list(p.respostas.keys())
    for chip in chips:
        assert p.respostas.get(chip), chip
    # E nada além do que é oferecido: resposta de chip que não aparece é peso
    # no payload e convite a exibir texto que a tela decidiu não mostrar.
    assert set(p.respostas) == set(chips)


def test_nao_existe_chip_de_por_que_esse_medico():
    """Removido em 10/08/2026, decisão de George: o card e os dois chips já
    explicam tudo, e a narrativa que ele devolvia continha os dois por dentro,
    então quem tocasse nele primeiro lia a mesma coisa três vezes."""
    for caso in TODOS:
        chips = list(pm.montar_payload(caso).respostas.keys())
        assert "Por que esse médico?" not in chips, caso["NOME_MEDICO"]


def test_sem_produto_nenhum_nao_oferece_chip_de_visita():
    caso = dict(SEM_PRODUTO_NA_LINHA, PRODUTO_ACHE_OUTRA_LINHA=None, LINHA_DO_PRODUTO_ACHE=None)
    p = pm.montar_payload(caso)
    chips = list(p.respostas.keys())
    assert pm.CHIP_VISITA not in chips
    assert any(c.type == "info-banner" for c in p.cards)


def test_payload_e_deterministico():
    for caso in TODOS:
        saidas = {pm.montar_payload(caso).model_dump_json() for _ in range(3)}
        assert len(saidas) == 1


# --------------------------------------------------------------------------- #
# Resolvedor do endpoint, com mock do executor
# --------------------------------------------------------------------------- #

SETOR = "010101050553"


class FakeExecutor:
    """Devolve linhas canonizadas e registra a ordem das consultas.

    Sem rede e sem credencial.
    """

    def __init__(self, localiza=None, perfil=None):
        self.localiza = localiza if localiza is not None else [
            {"UFCRM": ADICIONAR["UFCRM"], "NOME_MEDICO": ADICIONAR["NOME_MEDICO"]}
        ]
        self.perfil = perfil if perfil is not None else [ADICIONAR]
        self.chamadas = []

    def query(self, sql, params=None):
        self.chamadas.append((sql, params or {}))
        return self.perfil if sql is pm.SQL_PERFIL else self.localiza


def test_resolver_usa_o_setor_da_identidade_e_nao_o_do_texto():
    """O texto pode citar um setor que não é do propagandista."""
    executor = FakeExecutor()
    pm.resolver_perfil(f"PR0051890 setor 999999999999", executor, setor_autenticado=SETOR)
    assert executor.chamadas[0][1]["setor"] == SETOR


def test_resolver_sem_setor_nenhum_nao_consulta():
    executor = FakeExecutor()
    r = pm.resolver_perfil("PR0051890", executor)
    assert r.status == "PRECISA_SETOR"
    assert executor.chamadas == []


def test_resolver_manda_a_cauda_para_o_llm():
    executor = FakeExecutor()
    r = pm.resolver_perfil(CAUDA[0], executor, setor_autenticado=SETOR)
    assert r.status == "FORA_DO_ESCOPO"
    assert executor.chamadas == []


def test_resolver_assume_o_que_ainda_nao_responde():
    executor = FakeExecutor()
    r = pm.resolver_perfil("quais medicos devo incluir", executor, setor_autenticado=SETOR)
    assert r.status == "NAO_IMPLEMENTADO"
    assert executor.chamadas == []


def test_resolver_nao_escolhe_medico_em_silencio():
    """856 CRMs sem UF e 2.394 nomes apontam para mais de um médico dentro do
    mesmo setor, medido em 10/08/2026."""
    executor = FakeExecutor(localiza=[
        {"UFCRM": "PR0051890", "NOME_MEDICO": "ZURISADAY BASABE GARCIA"},
        {"UFCRM": "PR0051891", "NOME_MEDICO": "OUTRO MEDICO QUALQUER"},
    ])
    r = pm.resolver_perfil("51890", executor, setor_autenticado=SETOR)
    assert r.status == "MEDICO_AMBIGUO"
    # O rótulo carrega o UFCRM: sem ele, dois homônimos viram dois chips iguais
    # e tocar num deles repete a mesma pergunta ambígua para sempre.
    assert r.cards[0].items == [
        "Zurisaday Basabe Garcia (PR0051890)",
        "Outro Medico Qualquer (PR0051891)",
    ]
    # E o rótulo volta identificando a pessoa, não repetindo a busca ambígua.
    assert pm.rotear(r.cards[0].items[0]).ufcrm == "PR0051890"


def test_resolver_devolve_o_perfil_pronto():
    executor = FakeExecutor()
    r = pm.resolver_perfil("PR0051890", executor, setor_autenticado=SETOR)
    assert r.status == "PERFIL_PRONTO"
    assert r.cards[0].name == "Zurisaday Basabe Garcia"
    # Cinco consultas desde 20/08/2026: localiza e perfil prescritivo em série,
    # e três de enriquecimento em paralelo. A ordem das três não é garantida,
    # porque rodam em threads, então o teste compara conjunto e não sequência.
    chamadas = [c[0] for c in executor.chamadas]
    assert chamadas[:2] == [pm.SQL_LOCALIZA, pm.SQL_PERFIL]
    assert set(chamadas[2:]) == {
        pm.SQL_SEGMENTACAO, pm.SQL_MERCADOS_DO_MEDICO, pm.SQL_OPORTUNIDADE
    }


def test_resolver_avisa_quando_o_medico_nao_e_do_setor():
    executor = FakeExecutor(localiza=[])
    r = pm.resolver_perfil("PR0051890", executor, setor_autenticado=SETOR)
    assert r.status == "MEDICO_NAO_ENCONTRADO"


def test_fora_do_escopo_nao_mostra_texto_de_depuracao():
    """O `motivo` do roteador é interno, do tipo "termo analitico". Ele serve
    para diagnóstico e não pode aparecer na tela do propagandista."""
    executor = FakeExecutor()
    r = pm.resolver_perfil(CAUDA[0], executor, setor_autenticado=SETOR)
    assert r.status == "FORA_DO_ESCOPO"
    assert r.mensagem == "Essa pergunta eu ainda não sei responder sozinho. Vou procurar nos dados."
    assert r.identificacao["motivo"] == "termo analitico"


# --------------------------------------------------------------------------- #
# Correções da revisão independente de 10/08/2026
# --------------------------------------------------------------------------- #


def test_identidade_com_setor_vazio_nao_cai_para_o_setor_do_texto():
    """Falha em modo aberto: com o `or`, sessão sem setor deixava o texto da
    pergunta escolher de qual setor os dados saem."""
    executor = FakeExecutor()
    r = pm.resolver_perfil(f"PR0051890 setor {SETOR}", executor, setor_autenticado="   ")
    assert r.status == "PRECISA_SETOR"
    assert executor.chamadas == []


def test_crm_digitado_sem_zeros_a_esquerda_e_comparavel():
    """O propagandista digita 51890 e a coluna guarda PR0051890. Conferido
    contra o banco em 10/08/2026: a comparação antiga devolvia zero linhas."""
    executor = FakeExecutor()
    pm.resolver_perfil("51890", executor, setor_autenticado=SETOR)
    assert executor.chamadas[0][1]["crm"] == "51890"
    assert "'^0+'" in pm.SQL_LOCALIZA


def test_desambiguacao_tem_ordem_estavel():
    """Sem desempate unico, os chips saem em ordem diferente a cada consulta.

    A ordenacao mudou em 20/08/2026, junto com a busca parcial: painel primeiro,
    depois melhor colocado, e o UFCRM continua como criterio final porque e o
    unico que nao empata. O teste passou a conferir a garantia e nao a letra do
    SQL, que era `ORDER BY p.UFCRM` quando a consulta lia a tabela direto.
    """
    assert "ORDER BY" in pm.SQL_LOCALIZA
    assert pm.SQL_LOCALIZA.rstrip().split("ORDER BY")[-1].strip().startswith(
        ("MAX(", "v.UFCRM", "p.UFCRM"))
    assert "UFCRM LIMIT" in pm.SQL_LOCALIZA


def test_os_blocos_saem_na_ordem_definida_por_george():
    """Ordem de 20/08/2026: decisao, ranking, oferecer, oportunidade, visita.

    Os antigos "prescreve" e "oferecer" viraram um so, e a leitura de volume
    virou "oportunidade" junto com o que a especialidade prescreve. Os dois
    primeiros liam a mesma coisa com dois blocos de distancia, e o "prescreve"
    ainda usava a tb_perfil_medico_setor, que ignora a linha de quem olha.

    O perfil de comunicacao nao sai daqui: vem de `POST /agente/enriquecer` e a
    tela acrescenta quando responde.
    """
    for caso in TODOS:
        blocos = pm.montar_blocos(caso)
        assert [b.ordem for b in blocos] == list(range(1, len(blocos) + 1))
        tipos = [b.tipo for b in blocos]
        esperada = ["decisao", "ranking", "oferecer", "oportunidade", "visita"]
        assert tipos == [x for x in esperada if x in tipos], (caso["NOME_MEDICO"], tipos)


def test_bloco_vazio_nao_entra_na_sequencia():
    """Cabecalho seguido de nada e pior que bloco ausente."""
    for caso in TODOS:
        for b in pm.montar_blocos(caso):
            assert b.texto.strip(), (caso["NOME_MEDICO"], b.tipo)


def test_sem_data_de_visita_nunca_vira_zero():
    """`MESES_DESDE_ULTIMA_VISITA` vale zero em 1.793.364 linhas sem visita.

    Exibir esse zero diria "visitado neste mes" para quem nunca foi visitado.
    Medido em 20/08/2026, e confirmado por `FLAG_SEM_VISITA_REGISTRADA` na
    `tb_ranking_medicos_validacao`, que em 1 cobre exatamente as mesmas linhas.
    """
    texto = pm.tempo_de_visita({"DATA_ULTIMA_VISITA": None, "MESES_DESDE_ULTIMA_VISITA": 0})
    assert texto == "sem registro"
    assert "0" not in texto


def test_o_tempo_sem_visita_e_contado_contra_hoje():
    """A coluna de meses esta ancorada na geracao da tabela, nao em hoje.

    Medido: ela diverge da conta real em exatamente um mes para 303.976 das
    771.811 linhas com data, porque a tabela foi gerada em 10/08 e o ciclo
    envelhece. Quem esta na porta do consultorio precisa do numero de hoje.
    """
    from datetime import date, timedelta
    hoje = date.today()
    assert pm.tempo_de_visita({"DATA_ULTIMA_VISITA": hoje}) == "hoje"
    assert pm.tempo_de_visita({"DATA_ULTIMA_VISITA": hoje - timedelta(days=1)}) == "ontem"
    assert pm.tempo_de_visita({"DATA_ULTIMA_VISITA": hoje - timedelta(days=17)}) == "há 17 dias"
    assert "meses" in pm.tempo_de_visita({"DATA_ULTIMA_VISITA": hoje - timedelta(days=200)})


def test_o_tempo_de_visita_mora_no_card_e_o_bloco_so_avisa_risco():
    """Pedido de George em 03/09/2026: a última visita entra no card do
    médico, e o bloco "Tempo sem visita" só existe com aviso de risco."""
    from datetime import date, timedelta
    recente = dict(CONTINUAR)
    recente["DATA_ULTIMA_VISITA"] = (date.today() - timedelta(days=17)).isoformat()
    assert pm.bloco_visita(recente) == ""
    assert pm.montar_payload(recente).cards[0].last_visit == "há 17 dias"
    sem_data = dict(CONTINUAR, DATA_ULTIMA_VISITA=None)
    assert pm.bloco_visita(sem_data) == ""
    assert pm.montar_payload(sem_data).cards[0].last_visit == "sem registro"


def test_o_ranking_nao_cita_o_numero_do_painel():
    """Regra 6 de como-alterar-a-resposta-do-chat.md, e um defeito de leitura.

    A posicao e sobre o setor inteiro e nao sobre o painel: escrever "posicao
    401 entre 375 do seu painel" e contraditorio, e isso acontece em 1.691.886
    das 2.565.175 linhas.
    """
    for caso in TODOS:
        texto = pm.bloco_ranking(caso)
        if not texto:
            continue
        total = caso.get("QTD_MEDICOS_PAINEL_SETOR")
        if total:
            assert str(total) not in texto, (caso["NOME_MEDICO"], texto)


def test_a_busca_nunca_sai_do_setor():
    """Exigencia de George em 20/08/2026, e ela ficou mais critica com a busca
    parcial.

    Com igualdade no nome inteiro, um termo achava no maximo os homonimos. Com
    `LIKE`, "nelson" casa com 3.961 medicos no pais e 3 no setor do
    propagandista, medido em 20/08. Se o recorte de setor cair, a desambiguacao
    passa a oferecer medico de outro territorio como se fosse dele.
    """
    assert "v.SETOR = :setor" in pm.SQL_LOCALIZA
    # o filtro de setor precisa estar no WHERE, e nao dentro do bloco OR das
    # formas de busca: dentro do OR ele deixaria de restringir
    onde = pm.SQL_LOCALIZA.split("WHERE", 1)[1]
    assert onde.strip().startswith("v.SETOR = :setor AND"), onde[:80]


def test_a_desambiguacao_traz_o_do_painel_primeiro():
    """O propagandista quase sempre quer alguem do proprio painel.

    Medido em 20/08: "nelson" no setor de teste devolve um do painel na posicao
    2 e dois fora, nas posicoes 370 e 768. Sem esta ordenacao, o corte de 20
    ordenava por UFCRM, que nao quer dizer nada para ele.
    """
    ordem = pm.SQL_LOCALIZA.split("ORDER BY", 1)[1]
    assert "NO_PAINEL" in ordem
    assert ordem.index("NO_PAINEL") < ordem.index("POSICAO_RANKING")


def test_a_busca_por_nome_e_parcial():
    """Defeito numero 1 da rota de campo de 11/08.

    Medido em 20/08/2026 contra o banco: com igualdade, "LOESTER" devolvia zero
    e so o nome inteiro achava. A busca passou a ser parcial, pela mesma view
    que o agente usa, para as duas rotas acharem o mesmo medico com o mesmo
    texto.
    """
    assert "upper(p.NOME_MEDICO) = :nome" not in pm.SQL_LOCALIZA
    assert "NOME_BUSCA LIKE :padrao" in pm.SQL_LOCALIZA
    assert "vw_agente_medico" in pm.SQL_LOCALIZA


def test_o_padrao_de_busca_vem_do_nome_ou_do_termo():
    """Usa a `Rota` de verdade, e nao um objeto falso: o padrao passou a olhar
    tambem `ufcrm` e `crm_numero` para dar precedencia ao identificador exato,
    e um falso sem esses campos escondia a mudanca."""
    assert pm._padrao_de_busca(pm.Rota(nome="Loester Da Silva")) == "%LOESTER DA SILVA%"
    assert pm._padrao_de_busca(pm.Rota(termo="loester")) == "%LOESTER%"
    assert pm._padrao_de_busca(pm.Rota()) == ""


def test_o_toque_no_chip_nao_volta_ambiguo():
    """Lacto infinito reproduzido em 20/08/2026 com o print da tela.

    O chip leva o UFCRM junto com o nome para o toque identificar a pessoa. Como
    as formas de busca sao ligadas por OR, tocar em "Ricardo Mendonca Costa
    (SP0040164)" casava o UFCRM certo e o nome parcial, que tambem pega
    "Ricardo Mendonca Costa Junior". Voltavam os mesmos dois chips, para sempre.
    """
    rota = pm.rotear("Ricardo Mendonca Costa (SP0040164)")
    assert rota.ufcrm == "SP0040164"
    # com identificador exato, o padrao parcial nao pode entrar no OR
    assert pm._padrao_de_busca(rota) == ""


def test_crm_solto_tambem_tem_precedencia_sobre_o_nome():
    rota = pm.rotear("Ricardo Mendonca Costa 40164")
    assert rota.crm_numero == "40164"
    assert pm._padrao_de_busca(rota) == ""


def test_sem_identificador_a_busca_parcial_continua_valendo():
    """A precedencia nao pode desligar a busca parcial, que e o ponto da mudanca."""
    assert pm._padrao_de_busca(pm.rotear("Ricardo Mendonca Costa")) == "%RICARDO MENDONCA COSTA%"
    assert pm._padrao_de_busca(pm.rotear("loester")) == "%LOESTER%"


def test_frase_de_visita_e_reconhecida():
    """E a frase que a aba Ranking gera ao tocar num medico.

    Reproduzido em 20/08/2026 com o print da tela: "Vou visitar CARLOS ALBERTO
    FONZAR LOPES" caia em "essa pergunta eu ainda nao sei responder sozinho", e
    o propagandista tinha que redigitar o nome.
    """
    for pergunta in ("Vou visitar CARLOS ALBERTO FONZAR LOPES",
                     "Vou visitar o Dr. Loester",
                     "vou ver a dra silva hoje",
                     "estou indo visitar o Loester"):
        assert pm.rotear(pergunta).intencao == "briefing_medico", pergunta


def test_nome_de_uma_palavra_vira_termo_de_busca():
    assert pm.rotear("loester").termo == "loester"
    assert pm.rotear("silva neiva").termo == "silva neiva"
    # advérbio de tempo nao entra no termo
    assert pm.rotear("vou ver a dra silva hoje").termo == "silva"


def test_pergunta_analitica_continua_indo_para_o_modelo():
    """A busca solta nao pode virar porta para responder o que nao sabemos."""
    for pergunta in ("qual o clima hoje?",
                     "quantos medicos prescrevem antidepressivos",
                     "compare meu setor com o do lado",
                     "me explique por que ele saiu do painel",
                     "qual o faturamento da empresa no trimestre"):
        assert pm.rotear(pergunta).intencao is None, pergunta


def test_status_desconhecido_nao_vai_cru_para_a_tela():
    caso = dict(ADICIONAR, RECOMENDACAO="ALGUM_VALOR_NOVO")
    assert pm.montar_payload(caso).cards[0].status == "Sem classificação"


def test_participacao_ache_segue_a_janela_das_categorias():
    """Com COALESCE, categorias do ano e percentual do ciclo apareciam na mesma
    resposta. O SQL passa a escolher a janela uma vez só."""
    assert "COALESCE(p.CICLO_PCT_ACHE" not in pm.SQL_PERFIL
    assert "THEN p.CICLO_PCT_ACHE" in pm.SQL_PERFIL


def test_posicao_da_categoria_compara_dentro_da_mesma_janela():
    assert "COALESCE(p.CICLO_TOP2_CATEGORIA" not in pm.SQL_PERFIL


def test_nenhuma_frase_exibida_usa_esse_medico():
    """A decisão de 09/08/2026 diz nome ou sujeito oculto. "Esse médico" é
    masculino e não é nenhum dos dois."""
    for caso in TODOS:
        p = pm.montar_payload(caso)
        textos = [p.mensagem, *p.respostas.values(), *[c.text or "" for c in p.cards]]
        for texto in textos:
            assert "esse médico" not in texto, caso["NOME_MEDICO"]


def test_cadastro_sem_setor_e_recusado_na_porta():
    """`resolver_contexto` devolve SETOR_RESOLVIDO com o setor direto da coluna,
    que aceita nulo. Sem a guarda no roteador, esse caso chegava ao resolvedor
    como se não houvesse identidade, e o setor citado na pergunta escolhia de
    quais dados a resposta sai. Apontado na segunda revisão de 10/08/2026."""
    from fastapi.testclient import TestClient

    from backend.app.auth.context import ContextoResponse, StatusContexto
    from backend.app.main import app
    from backend.app.routers import chat as router_chat
    from backend.app.tests.apoio_sessao import CABECALHO

    sem_setor = ContextoResponse(status=StatusContexto.SETOR_RESOLVIDO, setor=None, nome="Ana")
    app.dependency_overrides[router_chat.get_executor] = lambda: FakeExecutor()
    try:
        with patch("backend.app.routers.chat.resolver_contexto", return_value=sem_setor):
            resp = TestClient(app).post(
                "/chat/perfil-medico",
                json={"pergunta": f"PR0051890 setor {SETOR}"},
                headers=CABECALHO,
            )
        assert resp.status_code == 403
        assert resp.json()["detail"]["status"] == "SETOR_AUSENTE"
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Continuidade da conversa, correções do teste de campo de 30/08/2026
# --------------------------------------------------------------------------- #


def test_sobra_de_palavras_sem_medico_vira_fora_do_escopo():
    """"Quero a lista de pendências" virava busca por um médico chamado "lista
    pendências" e morria em "não encontrei ninguém". Continuação de conversa
    desce para o agente, que tem o histórico e as ferramentas."""
    executor = FakeExecutor(localiza=[])
    r = pm.resolver_perfil("quero a lista de pendências", executor, setor_autenticado=SETOR)
    assert r.status == "FORA_DO_ESCOPO"
    assert "termo sem correspondencia" in r.identificacao["motivo"]


def test_escolha_de_opcao_tambem_desce_para_o_agente():
    executor = FakeExecutor(localiza=[])
    r = pm.resolver_perfil("quero a segunda opção", executor, setor_autenticado=SETOR)
    assert r.status == "FORA_DO_ESCOPO"


def test_crm_explicito_inexistente_continua_nao_encontrado_e_com_saida():
    """Identificador explícito que não existe é "não encontrado" na hora, sem
    gastar modelo. Mas nunca em beco sem saída: a resposta orienta e sugere."""
    executor = FakeExecutor(localiza=[])
    r = pm.resolver_perfil("34827", executor, setor_autenticado=SETOR)
    assert r.status == "MEDICO_NAO_ENCONTRADO"
    assert "outras formas" in r.mensagem
    sugestoes = [c for c in r.cards if c.type == "suggestions"]
    assert sugestoes and len(sugestoes[0].items) >= 2


# --------------------------------------------------------------------------- #
# Saudação, teste de campo de 02/09/2026
# --------------------------------------------------------------------------- #


def test_saudacao_nao_vira_busca_de_medico():
    """"Olá" virava busca por substring e encontrava PAOLA. Saudação responde
    na hora, com chips, sem tocar o banco e sem gastar modelo. As formas com
    aspas tipográficas e emoji entraram pela revisão de 02/09/2026, que
    reproduziu o defeito original com elas na primeira versão do léxico."""
    executor = FakeExecutor()
    formas = ("Olá", "olá!", "Oi", "bom dia", "Boa tarde!", "tudo bem?",
              "valeu", "\u201cOl\u00e1\u201d", "Ol\u00e1 \U0001f44b", "ol\u00e1!!!", "OLA...",
              "Ol\u00e1\u2026")
    for mensagem in formas:
        r = pm.resolver_perfil(mensagem, executor, setor_autenticado=SETOR)
        assert r.status == "SAUDACAO", mensagem
        assert executor.chamadas == [], mensagem
        chips = [c for c in r.cards if c.type == "suggestions"]
        assert chips and len(chips[0].items) >= 2, mensagem


def test_saudacao_seguida_de_nome_vira_busca_limpa():
    """"Bom dia paola" buscava por %BOM DIA PAOLA% e não encontrava ninguém.
    O prefixo de cumprimento sai do termo e a busca vira %PAOLA%."""
    r = pm.rotear("bom dia paola")
    assert r.intencao == "briefing_medico"
    assert r.motivo == "identificador seco"
    assert r.termo == "paola"


def test_saudacao_com_crm_junto_continua_sendo_busca():
    """"Oi 34827" descartava o dígito na normalização por letras e devolvia
    boas-vindas sem consultar o médico. A saudação só vence sem identificador.
    Achado da revisão independente de 02/09/2026."""
    r = pm.rotear("oi 34827")
    assert r.intencao == "briefing_medico"
    assert r.crm_numero == "34827"
    r = pm.rotear("bom dia 34827")
    assert r.intencao == "briefing_medico"
    assert r.crm_numero == "34827"
    r = pm.rotear("olá SP0462552")
    assert r.intencao == "briefing_medico"
    assert r.ufcrm == "SP0462552"


def test_saudacao_com_setor_junto_vira_resumo_do_setor():
    """"Oi 010101050553" engolia o código do setor. Com a guarda incluindo o
    setor, o fluxo segue para o resumo, como no código seco, e o termo de
    busca calculado com o cumprimento dentro é anulado."""
    r = pm.rotear("oi 010101050553")
    assert r.intencao == "resumo_setor"
    assert r.setor == "010101050553"
    assert r.termo is None


def test_saudacao_com_identificador_rotulado_nao_vaza():
    """"Oi setor 010101050553" gerava termo "oi" e virava busca de médico; "oi
    crm 34827" caía no agente. O rótulo estrutural sai pela sobra e o prefixo
    de cumprimento sai pelo laço, então cada identificador segue seu fluxo."""
    r = pm.rotear("oi setor 010101050553")
    assert r.intencao == "resumo_setor"
    assert r.setor == "010101050553"
    assert r.termo is None
    r = pm.rotear("oi codigo 010101050553")
    assert r.intencao == "resumo_setor"
    r = pm.rotear("oi crm 34827")
    assert r.intencao == "briefing_medico"
    assert r.crm_numero == "34827"
    assert r.termo is None


def test_saudacoes_encadeadas_continuam_saudacao():
    r = pm.rotear("oi bom dia")
    assert r.intencao == "saudacao"


def test_saudacao_capitalizada_antes_de_nome_nao_vira_nome():
    """"Oi Paola" casava com a regex de nome capitalizado e buscava por
    %OI PAOLA%. O prefixo agora é consumido antes de qualquer extração."""
    r = pm.rotear("Oi Paola")
    assert r.intencao == "briefing_medico"
    assert r.nome is None
    assert r.termo == "paola"
    r = pm.rotear("Olá Paola Silva")
    assert r.intencao == "briefing_medico"
    assert r.nome == "Paola Silva"


def test_saudacoes_encadeadas_seguidas_de_nome_viram_busca():
    """"Oi bom dia paola" tinha quatro palavras na sobra, nunca ganhava termo
    e caía no agente. Com o consumo antecipado, sobra só o nome."""
    r = pm.rotear("oi bom dia paola")
    assert r.intencao == "briefing_medico"
    assert r.termo == "paola"


def test_palavra_repetida_fora_do_prefixo_sobrevive():
    """O corte é posicional: em "bom dia dia", só o cumprimento sai, e o
    segundo "dia" permanece como termo de busca."""
    r = pm.rotear("bom dia dia")
    assert r.termo == "dia"


def test_busca_curta_e_crm_sobrevivem_ao_lexico():
    """"Leo" com três letras é busca legítima, e "34827" continua CRM: a
    normalização por letra derruba o dígito para vazio, e vazio não é
    saudação."""
    r = pm.rotear("Leo")
    assert r.intencao == "briefing_medico"
    assert r.termo == "leo"
    r = pm.rotear("34827")
    assert r.intencao == "briefing_medico"
    assert r.crm_numero == "34827"


def test_sobrenome_igual_a_cortesia_continua_sendo_busca():
    """Medido na vw_agente_medico em 02/09/2026 por palavra exata do nome:
    Beleza 49 médicos, Perfeito 46, Salve 24, Legal 10, Opa 7. Esses termos ficaram
    fora do léxico e a mensagem inteira igual a eles segue como busca de
    nome, com o termo preservado."""
    for termo in ("Salve", "Show", "Legal", "Beleza", "Perfeito", "Ótimo", "Opa"):
        r = pm.rotear(termo)
        assert r.intencao == "briefing_medico", termo
        assert r.termo == pm._sem_acento(termo), termo


def test_pontuacao_interna_nao_quebra_a_saudacao():
    """"Oi,bom dia" tem duas palavras dentro do mesmo token. A sexta rodada
    da revisão de 02/09/2026 mostrou a regressão de comparar o token inteiro:
    a comparação agora é palavra a palavra, com mapa de volta ao token."""
    for mensagem in ("oi,bom dia", "bom-dia", "tudo-bem?"):
        assert pm.rotear(mensagem).intencao == "saudacao", mensagem
    r = pm.rotear("oi,bom dia paola")
    assert r.intencao == "briefing_medico"
    assert r.termo == "paola"


def test_palavra_com_digito_nunca_e_cumprimento():
    """"Oi2" normalizava para "oi" e era consumido. Palavra de token com
    dígito não é consumível, então segue como busca."""
    r = pm.rotear("oi2")
    assert r.intencao != "saudacao"


def test_ruido_puro_ganha_boas_vindas_em_vez_de_agente():
    """Mensagem só de emoji ou pontuação não tem o que rotear nem o que
    perguntar ao modelo: boas-vindas com chips custam zero e orientam."""
    for mensagem in ("\U0001f44b", "...", "???"):
        assert pm.rotear(mensagem).intencao == "saudacao", mensagem


def test_consumo_no_meio_do_token_nao_corta_nada():
    """"Oi,paola" pararia no meio do token. Sem corte limpo, nada é cortado e
    a mensagem segue o fluxo normal de busca."""
    r = pm.rotear("oi,paola")
    assert r.intencao == "briefing_medico"
