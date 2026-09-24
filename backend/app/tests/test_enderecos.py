"""Testes das regras de endereço do card do médico (app/enderecos.py).

Os casos vêm da amostra real de 18/09/2026: médicos com CRM de Rondônia cujo
SalesFarma, auditoria e CNES foram comparados lado a lado.
"""
from backend.app.enderecos import (
    FONTE_AUDITORIA,
    FONTE_CNES,
    FONTE_PROPAGANDISTA,
    FONTE_SALESFARMA,
    cep8,
    cidades_da_auditoria,
    cidades_do_setor,
    divergem,
    endereco_da_visita,
    escolher_local_cnes,
    normalizar,
)

# ------------------------------------------------------------ normalização --


def test_normalizar_tira_acento_caixa_e_pontuacao():
    assert normalizar("São José do Rio Prêto-SP") == "SAO JOSE DO RIO PRETO SP"


def test_cep8_pega_os_oito_ultimos_digitos():
    """A auditoria grava com zeros à esquerda: 10 dígitos."""
    assert cep8("0038400299") == "38400299"
    assert cep8("76870042") == "76870042"
    assert cep8("123") is None
    assert cep8(None) is None


def test_cidades_da_auditoria_separa_agregados():
    assert cidades_da_auditoria("BETIM-MG + IGARAPE-MG") == {"BETIM", "IGARAPE"}
    assert cidades_da_auditoria("MARISTELA (LARANJAL PAULISTA)-SP + OUTRAS") == {
        "MARISTELA",
        "LARANJAL PAULISTA",
    }
    assert cidades_da_auditoria("PELOTAS-RS") == {"PELOTAS"}


def test_cidades_do_setor_separa_por_virgula():
    assert cidades_do_setor("Pelotas, Rio Grande , CAPÃO DO LEÃO") == {
        "PELOTAS",
        "RIO GRANDE",
        "CAPAO DO LEAO",
    }


# ------------------------------------------------------------- endereço 1 --

SF_ALYNE = [
    {"local": "CONSULTORIO PARTICULAR", "logradouro": "AVENIDA DUQUE DE CAXIAS 250",
     "bairro": "FRAGATA", "cidade": "PELOTAS", "uf": "RS", "cep": "96030000"},
]
AUD_ALYNE = {"logradouro": "ERNANI OSMAR BLAAS 334", "cidade": "PELOTAS-RS", "uf": "RS", "cep": "0096065770"}


def test_endereco_1_prefere_salesfarma():
    lista = endereco_da_visita(SF_ALYNE, AUD_ALYNE)
    assert len(lista) == 1
    assert lista[0].fonte == FONTE_SALESFARMA
    assert lista[0].local == "CONSULTORIO PARTICULAR"
    assert lista[0].cep == "96030000"


def test_endereco_1_cai_na_auditoria_sem_salesfarma():
    lista = endereco_da_visita([], AUD_ALYNE)
    assert len(lista) == 1
    assert lista[0].fonte == FONTE_AUDITORIA
    assert lista[0].cep == "96065770"
    assert lista[0].cidades == {"PELOTAS"}


def test_endereco_1_ignora_salesfarma_sem_logradouro():
    lista = endereco_da_visita([{"logradouro": "  ", "cidade": "PELOTAS"}], AUD_ALYNE)
    assert lista[0].fonte == FONTE_AUDITORIA


def test_endereco_1_vazio_sem_nenhuma_fonte():
    assert endereco_da_visita([], None) == []
    assert endereco_da_visita([], {"logradouro": ""}) == []


def test_correcao_do_propagandista_ganha_de_tudo():
    corrigido = {"logradouro": "Rua Nova", "numero": "10", "complemento": "sala 3", "bairro": "Centro",
                 "cidade": "Pelotas", "uf": "RS", "cep": "96010-000",
                 "registrado_por": "184375", "registrado_em": "2026-09-18 21:00:00"}
    lista = endereco_da_visita(SF_ALYNE, AUD_ALYNE, corrigido)
    assert len(lista) == 1
    assert lista[0].fonte == FONTE_PROPAGANDISTA
    assert lista[0].numero == "10"
    assert lista[0].cep == "96010000"
    assert lista[0].registrado_por == "184375"


def test_correcao_sem_logradouro_e_ignorada():
    lista = endereco_da_visita(SF_ALYNE, AUD_ALYNE, {"logradouro": " ", "cidade": "X"})
    assert lista[0].fonte == FONTE_SALESFARMA


def test_correcao_entra_na_regra_do_cnes_pelo_cep():
    corrigido = {"logradouro": "Alameda do Ipê", "numero": "1597", "cidade": "Ariquemes", "uf": "RO", "cep": "76870042"}
    visita = endereco_da_visita([], None, corrigido)
    escolhido = escolher_local_cnes(CNES_RO0001454, visita, cidades_setor=set())
    assert escolhido is not None and escolhido.local == "HOSPITAL SAO FRANCISCO"


def test_endereco_1_traz_todos_do_salesfarma():
    dois = SF_ALYNE + [{"local": "HOSPITAL", "logradouro": "RUA B 10", "cidade": "PELOTAS", "cep": "96010000"}]
    assert len(endereco_da_visita(dois, None)) == 2


# ------------------------------------------------------------- endereço 2 --

CNES_RO0001454 = [
    {"nome_fantasia": "HOSPITAL SAO FRANCISCO", "logradouro": "ALAMEDA DO IPE", "numero": "1597",
     "bairro": "SETOR COMERCIAL 01", "cep": "76870042", "municipio": "ARIQUEMES", "uf": "RO",
     "telefone": "(69)3535-2431"},
    {"nome_fantasia": "HOSPITAL MUNICIPAL DE ARIQUEMES", "logradouro": "AV TANCREDO NEVES", "numero": "1370",
     "bairro": "INSTITUCIONAL", "cep": "76870023", "municipio": "ARIQUEMES", "uf": "RO",
     "telefone": "(69)35352635"},
]


def test_regra_1_mesma_area_do_endereco_1():
    """RO0001454: o SalesFarma tem o Hospital São Francisco, CEP 76870042; o
    CNES tem o mesmo hospital. Casa pelo CEP e ganha do outro hospital."""
    visita = endereco_da_visita(
        [{"logradouro": "ALAMEDA DO IPÊ 1597 HOSPITAL SÃO FRANCISCO", "cidade": "ARIQUEMES", "cep": "76870042"}],
        None,
    )
    escolhido = escolher_local_cnes(CNES_RO0001454, visita, cidades_setor={"PORTO VELHO"})
    assert escolhido is not None
    assert escolhido.fonte == FONTE_CNES
    assert escolhido.local == "HOSPITAL SAO FRANCISCO"
    assert escolhido.telefone == "(69)3535-2431"
    assert escolhido.numero == "1597"


def test_regra_2_cidade_do_setor_quando_o_cep_nao_casa():
    visita = endereco_da_visita([{"logradouro": "RUA X 1", "cidade": "PORTO VELHO", "cep": "76801141"}], None)
    escolhido = escolher_local_cnes(CNES_RO0001454, visita, cidades_setor={"ARIQUEMES", "JARU"})
    assert escolhido is not None
    # o primeiro candidato da cidade do setor, na ordem em que veio
    assert escolhido.local == "HOSPITAL SAO FRANCISCO"


def test_regra_3_cidade_do_endereco_1_quando_setor_nao_casa():
    visita = endereco_da_visita([{"logradouro": "RUA X 1", "cidade": "Ariquemes", "cep": "76999000"}], None)
    escolhido = escolher_local_cnes(CNES_RO0001454, visita, cidades_setor={"PORTO VELHO"})
    assert escolhido is not None
    assert escolhido.cidade == "ARIQUEMES"


def test_sem_regra_devolve_none():
    """RO0007183: posto de saúde em Alto Alegre, SalesFarma em outra cidade,
    setor em outra ainda. Nada casa, e o certo é não mostrar."""
    cnes = [{"nome_fantasia": "POSTO DE SAUDE ALTO ALEGRE", "logradouro": "LINHA C 85", "cep": "76862970",
             "municipio": "ALTO ALEGRE DOS PARECIS", "uf": "RO"}]
    visita = endereco_da_visita([{"logradouro": "RUA Y 2", "cidade": "PORTO VELHO", "cep": "78933000"}], None)
    assert escolher_local_cnes(cnes, visita, cidades_setor={"JI PARANA"}) is None


def test_regra_2_funciona_sem_endereco_1():
    """Médico sem SalesFarma nem auditoria ainda pode ter endereço 2 pelo setor."""
    escolhido = escolher_local_cnes(CNES_RO0001454, [], cidades_setor={"ARIQUEMES"})
    assert escolhido is not None


def test_cidade_agregada_da_auditoria_entra_na_regra_3():
    visita = endereco_da_visita([], {"logradouro": "R A 1", "cidade": "ARIQUEMES-RO + JARU-RO", "cep": "0076999000"})
    escolhido = escolher_local_cnes(CNES_RO0001454, visita, cidades_setor=set())
    assert escolhido is not None


def test_candidato_sem_logradouro_e_ignorado():
    cnes = [{"nome_fantasia": "X", "logradouro": "", "cep": "76870042", "municipio": "ARIQUEMES"}]
    visita = endereco_da_visita([{"logradouro": "RUA X 1", "cep": "76870042"}], None)
    assert escolher_local_cnes(cnes, visita, cidades_setor=set()) is None


# ------------------------------------------------------------- divergência --


def test_divergem_quando_cidades_nao_coincidem():
    visita = endereco_da_visita([{"logradouro": "RUA X 1", "cidade": "PORTO VELHO", "cep": "76801141"}], None)
    local = escolher_local_cnes(CNES_RO0001454, visita, cidades_setor={"ARIQUEMES"})
    assert divergem(visita, local) is True


def test_nao_divergem_na_mesma_cidade():
    visita = endereco_da_visita([{"logradouro": "RUA X 1", "cidade": "Ariquemes", "cep": "76870042"}], None)
    local = escolher_local_cnes(CNES_RO0001454, visita, cidades_setor=set())
    assert divergem(visita, local) is False


def test_nao_divergem_quando_salesfarma_grava_cidade_com_uf():
    """RS0025000, prova real de 18/09/2026: SalesFarma "PELOTAS-RS" e CNES
    "PELOTAS", mesmo prédio, mesmo CEP. Marcava divergente."""
    visita = endereco_da_visita(
        [{"logradouro": "PROFESSOR DOUTOR ARAUJO 538 538", "cidade": "PELOTAS-RS", "cep": "96020360"}], None
    )
    cnes = [{"nome_fantasia": "HOSPITAL ESCOLA DA UFPEL", "logradouro": "PROFESSOR DOUTOR ARAUJO",
             "numero": "538", "cep": "96020360", "municipio": "PELOTAS", "uf": "RS"}]
    local = escolher_local_cnes(cnes, visita, cidades_setor=set())
    assert local is not None
    assert divergem(visita, local) is False


def test_nao_divergem_sem_um_dos_dois():
    assert divergem([], None) is False
    visita = endereco_da_visita(SF_ALYNE, None)
    assert divergem(visita, None) is False


# ------------------------------------------------- agrupamento SalesFarma ----
# Pedido de George em 20/09/2026: o card mostrava sete cartões para o mesmo
# prédio. Casos reais da base, medidos no mesmo dia.

from backend.app.enderecos import Endereco, agrupar_salesfarma, chave_do_logradouro, decompor_logradouro, rua_para_exibir


def _sf(logradouro, cep="25010009", local="Consultorio Particular"):
    return {"local": local, "logradouro": logradouro, "bairro": "Centro",
            "cidade": "Duque de Caxias", "uf": "RJ", "cep": cep}


def test_decompor_separa_rua_numero_e_complemento():
    assert decompor_logradouro("Avenida Governador Leonel de Moura Brizola 1699 Sala 106") == (
        "Avenida Governador Leonel de Moura Brizola", "1699", "Sala 106")
    assert decompor_logradouro("RUA SÃO JORGE, 89") == ("RUA SÃO JORGE", "89", None)
    assert decompor_logradouro("RUA FRANCISCO MANOEL 00 POL JAGUARIBE") == (
        "RUA FRANCISCO MANOEL", None, "POL JAGUARIBE")
    assert decompor_logradouro("SEM NUMERO NENHUM") == ("SEM NUMERO NENHUM", None, None)


def test_chave_ignora_tipo_de_via_abreviacao_e_acento():
    assert chave_do_logradouro("R CEL FONTE BOA 186") == chave_do_logradouro("RUA CORONEL FONTE BOA 186 HOSPITAL PIO XII")
    assert chave_do_logradouro("RUA R CEL FONTE BOA 186 PIO XII") == chave_do_logradouro("R CEL FONTE BOA 186")
    assert chave_do_logradouro("SÃO JORGE 89") == chave_do_logradouro("RUA SÃO JORGE 89")
    assert chave_do_logradouro("10ª RUA RUA MARQUÊS DE PARANÁ, 303 303 PROFESSOR HUAP") == chave_do_logradouro("RUA MARQUES DE PARANA 303")


def test_chave_separa_numero_diferente():
    assert chave_do_logradouro("Avenida Governador Leonel de Moura Brizola 1669") != chave_do_logradouro(
        "Avenida Governador Leonel de Moura Brizola 1699")


def test_rua_para_exibir_tira_ruido_do_comeco():
    assert rua_para_exibir("RUA RUA MARQUÊS DE PARANÁ") == "RUA MARQUÊS DE PARANÁ"
    assert rua_para_exibir("10ª RUA RUA MARQUÊS DE PARANÁ") == "RUA MARQUÊS DE PARANÁ"
    assert rua_para_exibir("RUA R CEL FONTE BOA") == "R CEL FONTE BOA"
    assert rua_para_exibir("RUA SÃO JORGE") == "RUA SÃO JORGE"


def test_agrupa_o_caso_do_card_de_20_09():
    """Sete cartões viram dois: 1669 e 1699. O 1699 sai limpo, sem sala nem
    referência, com o CEP que mais se repete."""
    brutos = [
        _sf("Avenida Governador Leonel de Moura Brizola 1669"),
        _sf("Avenida Governador Leonel de Moura Brizola 1699", cep="25020002"),
        _sf("Avenida Governador Leonel de Moura Brizola 1699 **consultório"),
        _sf("Avenida Governador Leonel de Moura Brizola 1699 Consultorio"),
        _sf("Avenida Governador Leonel de Moura Brizola 1699 Esquina Calçadão"),
        _sf("Avenida Governador Leonel de Moura Brizola 1699 Ricardo Eletro", cep="25020002"),
        _sf("Avenida Governador Leonel de Moura Brizola 1699 Sala 106"),
    ]
    lista = endereco_da_visita(brutos, None)
    assert [(e.logradouro, e.numero, e.complemento, e.cep) for e in lista] == [
        ("Avenida Governador Leonel de Moura Brizola", "1669", None, "25010009"),
        ("Avenida Governador Leonel de Moura Brizola", "1699", None, "25010009"),
    ]
    assert all(e.fonte == FONTE_SALESFARMA for e in lista)


def test_representante_prefere_sem_complemento_e_com_tipo_de_via():
    lista = agrupar_salesfarma([
        Endereco(fonte=FONTE_SALESFARMA, logradouro="SÃO JORGE 89", cep="03087000"),
        Endereco(fonte=FONTE_SALESFARMA, logradouro="RUA SÃO JORGE 89 CLINICA X", cep="03087000"),
        Endereco(fonte=FONTE_SALESFARMA, logradouro="RUA SÃO JORGE 89", cep="03087000"),
    ])
    assert len(lista) == 1
    assert (lista[0].logradouro, lista[0].numero, lista[0].complemento) == ("RUA SÃO JORGE", "89", None)


def test_sem_numero_agrupa_pela_rua():
    lista = agrupar_salesfarma([
        Endereco(fonte=FONTE_SALESFARMA, logradouro="RUA FRANCISCO MANOEL 00 POL JAGUARIBE"),
        Endereco(fonte=FONTE_SALESFARMA, logradouro="FRANCISCO MANOEL 0"),
    ])
    assert len(lista) == 1 and lista[0].numero is None
