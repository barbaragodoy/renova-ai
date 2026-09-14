"""Testes da Memória de Visitas, sem rede, sem banco e sem modelo real."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.app.agente import memoria_visitas as mv


class ExecutorFalso:
    def __init__(self, linhas=None, erro=None):
        self.linhas = linhas or []
        self.erro = erro
        self.chamadas = []

    def query(self, sql, params=None):
        self.chamadas.append((" ".join(sql.split()), params or {}))
        if self.erro:
            raise self.erro
        return self.linhas


class ModeloFalso:
    def __init__(self, conteudo):
        self.conteudo = conteudo
        self.recebido = []

    def conversar(self, mensagens, ferramentas):
        self.recebido.append(mensagens)
        return {"content": self.conteudo}


OBS = [
    {"DATA_VISITA": "14/08/2026", "VISITA_TIPO": "PRESENCIAL",
     "COMENTARIOS": "PEDIU AMOSTRA DE FUSOR E COMENTOU QUE ESTAVA GRIPADO"},
    {"DATA_VISITA": "10/07/2026", "VISITA_TIPO": "REMOTO",
     "COMENTARIOS": "DISSE QUE USA CONCORRENTE HA ANOS"},
]

ESTRUTURADO = json.dumps({
    "momento_da_relacao": {"classificacao": "conquista",
                           "justificativa": "Em 10/07 usava concorrente; em 14/08 pediu amostra."},
    "voz_do_medico": [{"data": "10/07/2026", "texto": "Usa concorrente há anos."}],
    "momento_clinico": [],
    "toque_pessoal": [{"data": "14/08/2026", "texto": "Estava gripado; vale perguntar como está."}],
})


def _limpar():
    with mv._trava:
        mv._cache.clear()


def test_monta_com_ultima_crua_e_resumo_estruturado():
    _limpar()
    m = mv.montar(ExecutorFalso(OBS), ModeloFalso(ESTRUTURADO), "010101", "RJ1")
    assert m.disponivel and not m.somente_crua
    assert m.ultima.data == "14/08/2026"
    assert "FUSOR" in m.ultima.comentario
    assert m.momento_da_relacao.classificacao == "conquista"
    assert m.toque_pessoal[0].data == "14/08/2026"
    assert m.momento_clinico == []


def test_sem_observacoes_e_primeira_visita_sem_modelo():
    _limpar()
    modelo = ModeloFalso(ESTRUTURADO)
    m = mv.montar(ExecutorFalso([]), modelo, "010101", "RJ2")
    assert m.disponivel
    assert m.momento_da_relacao.classificacao == "primeira_visita"
    assert modelo.recebido == []


def test_classificacao_fora_do_vocabulario_vira_indefinido():
    _limpar()
    torto = json.dumps({"momento_da_relacao": {"classificacao": "fiel", "justificativa": "x"},
                        "voz_do_medico": [], "momento_clinico": [], "toque_pessoal": []})
    m = mv.montar(ExecutorFalso(OBS), ModeloFalso(torto), "010101", "RJ3")
    assert m.momento_da_relacao.classificacao == "indefinido"


def test_falha_do_modelo_degrada_para_a_camada_crua():
    """A degradação entra no cache com validade curta, não com a plena: a
    recuperação do modelo aparece em minutos, e a indisponibilidade não
    cobra uma chamada perdida por abertura."""
    _limpar()
    class ModeloQuebrado:
        def conversar(self, mensagens, ferramentas):
            raise RuntimeError("fora do ar")
    m = mv.montar(ExecutorFalso(OBS), ModeloQuebrado(), "010101", "RJ4")
    assert m.disponivel and m.somente_crua
    assert m.ultima.comentario
    with mv._trava:
        _, ttl, _ = mv._cache[mv._chave("010101", "RJ4")]
    assert ttl == mv.TTL_FALHA_SEGUNDOS


def test_falha_da_consulta_degrada_para_indisponivel():
    _limpar()
    m = mv.montar(ExecutorFalso(erro=RuntimeError("sem grant")), ModeloFalso(ESTRUTURADO),
                  "010101", "RJ5")
    assert not m.disponivel


def test_cache_evita_a_segunda_chamada_de_modelo():
    _limpar()
    modelo = ModeloFalso(ESTRUTURADO)
    executor = ExecutorFalso(OBS)
    mv.montar(executor, modelo, "010101", "RJ6")
    mv.montar(executor, modelo, "010101", "rj6 ")
    assert len(modelo.recebido) == 1
    assert len(executor.chamadas) == 1


def test_json_embrulhado_em_cerca_de_codigo_e_aceito():
    _limpar()
    m = mv.montar(ExecutorFalso(OBS),
                  ModeloFalso(f"```json\n{ESTRUTURADO}\n```"), "010101", "RJ7")
    assert m.momento_da_relacao.classificacao == "conquista"


def test_consulta_le_pela_view_e_filtra_setor_e_medico():
    """Le `vw_visitacao_comentarios`, e nao a tabela de origem.

    Medido em 04/09/2026 com `oauth_service_principal`: o service principal do
    portal nao e membro de nenhum grupo `user-renovai-*` e a leitura direta da
    `dmn_produtividade_dev` falha com `INSUFFICIENT_PERMISSIONS`. Era o que
    derrubava a Memoria em homologacao. A view roda com a permissao do dono, e
    ja filtra `VISITA_EFETIVA`, por isso o filtro saiu daqui.
    """
    _limpar()
    executor = ExecutorFalso(OBS)
    with patch(
        "backend.app.db.sql_dialect.get_settings",
        return_value=type("Settings", (), {"data_source": "local"})(),
    ):
        mv.montar(executor, ModeloFalso(ESTRUTURADO), "010101", "RJ8")
    sql, params = executor.chamadas[0]
    assert "vw_visitacao_comentarios" in sql
    assert "dmn_produtividade_dev" not in sql
    assert "v.SETOR = :setor AND v.UFCRM = :ufcrm" in sql
    assert "VISITA_EFETIVA" not in sql
    assert "ORDER BY v.DATA_VISITA DESC" in sql
    assert "TO_CHAR(v.DATA_VISITA, 'DD/MM/YYYY')" in sql
    assert params == {"setor": "010101", "ufcrm": "RJ8"}


def test_consulta_formata_data_com_sintaxe_do_databricks():
    _limpar()
    executor = ExecutorFalso(OBS)
    with patch(
        "backend.app.db.sql_dialect.get_settings",
        return_value=type("Settings", (), {"data_source": "databricks"})(),
    ):
        mv.montar(executor, ModeloFalso(ESTRUTURADO), "010101", "RJ8-SPARK")

    sql, _ = executor.chamadas[0]
    assert "DATE_FORMAT(v.DATA_VISITA, 'dd/MM/yyyy')" in sql
    assert "TO_CHAR" not in sql


def test_json_valido_com_estrutura_inesperada_degrada_sem_estourar():
    """JSON sintaticamente válido com tipos errados derrubava a rota com 500.
    Achado da revisão independente de 03/09/2026: lista no lugar do objeto,
    número no lugar do texto, string no lugar da lista."""
    _limpar()
    tortos = [
        '{"momento_da_relacao": [1, 2], "voz_do_medico": "texto solto"}',
        '{"momento_da_relacao": {"classificacao": 7}, "voz_do_medico": [{"texto": 5}]}',
        '{"voz_do_medico": [[1]], "momento_clinico": 3, "toque_pessoal": {"a": 1}}',
    ]
    for i, torto in enumerate(tortos):
        m = mv.montar(ExecutorFalso(OBS), ModeloFalso(torto), "010101", f"RJ9{i}")
        assert m.disponivel, torto
        assert m.ultima.comentario, torto


def test_modelo_nao_pode_declarar_primeira_visita():
    """primeira_visita é determinística: com observações presentes, o modelo
    devolvendo essa classificação vira indefinido."""
    _limpar()
    torto = json.dumps({"momento_da_relacao": {"classificacao": "primeira_visita",
                                               "justificativa": "x"},
                        "voz_do_medico": [], "momento_clinico": [], "toque_pessoal": []})
    m = mv.montar(ExecutorFalso(OBS), ModeloFalso(torto), "010101", "RJ10")
    assert m.momento_da_relacao.classificacao == "indefinido"


def test_falha_de_modelo_entra_no_cache_curto():
    """Indisponibilidade não cobra uma chamada perdida por abertura: o
    resultado cru fica em cache por TTL_FALHA_SEGUNDOS."""
    _limpar()
    class ModeloQuebrado:
        def __init__(self):
            self.chamadas = 0
        def conversar(self, mensagens, ferramentas):
            self.chamadas += 1
            raise RuntimeError("fora do ar")
    modelo = ModeloQuebrado()
    executor = ExecutorFalso(OBS)
    m1 = mv.montar(executor, modelo, "010101", "RJ11")
    m2 = mv.montar(executor, modelo, "010101", "RJ11")
    assert m1.somente_crua and m2.somente_crua
    assert modelo.chamadas == 1
    with mv._trava:
        _, ttl, _ = mv._cache[mv._chave("010101", "RJ11")]
    assert ttl == mv.TTL_FALHA_SEGUNDOS


def test_ttl_vencido_refaz_a_montagem():
    _limpar()
    modelo = ModeloFalso(ESTRUTURADO)
    executor = ExecutorFalso(OBS)
    mv.montar(executor, modelo, "010101", "RJ12")
    with mv._trava:
        chave = mv._chave("010101", "RJ12")
        gravado_em, ttl, memoria = mv._cache[chave]
        mv._cache[chave] = (gravado_em - ttl - 1, ttl, memoria)
    mv.montar(executor, modelo, "010101", "RJ12")
    assert len(modelo.recebido) == 2


def test_duas_threads_do_mesmo_medico_pagam_uma_chamada():
    """Efeito manada: duas aberturas simultâneas do mesmo perfil disparavam
    duas chamadas de modelo. A trava por chave com reconferência serializa."""
    import threading as th
    _limpar()

    class ModeloLento:
        def __init__(self):
            self.chamadas = 0
            self.trava = th.Lock()
        def conversar(self, mensagens, ferramentas):
            with self.trava:
                self.chamadas += 1
            import time as t
            t.sleep(0.05)
            return {"content": ESTRUTURADO}

    modelo = ModeloLento()
    executor = ExecutorFalso(OBS)
    threads = [th.Thread(target=mv.montar, args=(executor, modelo, "010101", "RJ13"))
               for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert modelo.chamadas == 1


def test_chave_normaliza_setor_e_ufcrm():
    assert mv._chave(" 010101 ", "RJ1") == mv._chave("010101", "RJ1")


def test_secao_da_chave_readquire_quando_a_trava_foi_trocada():
    """A janela da contenção: a trava pode sair do registro entre a devolução
    e o acquire. A reconferência detecta e a thread fica presa na nova até a
    liberação, nunca entra pela velha. Mesmo padrão revisado na memória de
    conversa."""
    import threading as th
    import time as t
    _limpar()
    velha = th.Lock()
    velha.acquire()
    with mv._trava:
        mv._travas_por_chave["k-troca"] = velha
    resultado = []

    def tenta():
        with mv._secao_da_chave("k-troca"):
            resultado.append("entrou")

    thread = th.Thread(target=tenta)
    thread.start()
    t.sleep(0.05)
    nova = th.Lock()
    nova.acquire()
    with mv._trava:
        mv._travas_por_chave["k-troca"] = nova
    velha.release()
    t.sleep(0.15)
    assert resultado == []
    assert thread.is_alive()
    nova.release()
    thread.join(timeout=5)
    assert resultado == ["entrou"]
    with mv._trava:
        mv._travas_por_chave.pop("k-troca", None)


def test_itens_saem_do_mais_recente_para_o_mais_antigo():
    """O card resumido do Ranking corta em "só o primeiro item", então o
    primeiro precisa ser o mais novo mesmo que o modelo entregue fora de
    ordem. Achado da revisão independente de 03/09/2026."""
    _limpar()
    fora_de_ordem = json.dumps({
        "momento_da_relacao": {"classificacao": "conquista", "justificativa": "x"},
        "voz_do_medico": [
            {"data": "10/07/2026", "texto": "antigo"},
            {"data": "99/99/9999", "texto": "numérica mas inválida ordena por último"},
            {"data": "02/01/2026", "texto": "mais antigo"},
            {"data": "14/08/2026", "texto": "mais novo"},
        ],
        "momento_clinico": [],
        "toque_pessoal": [],
    })
    m = mv.montar(ExecutorFalso(OBS), ModeloFalso(fora_de_ordem), "010101", "RJ9")
    assert [i.texto for i in m.voz_do_medico] == ["mais novo", "antigo", "mais antigo"]


def test_chave_de_data_exige_calendario_real():
    """Trio numérico não basta: "99/99/2026" ordenava como a mais recente.
    Achado da rodada 2 da revisão independente de 03/09/2026."""
    assert mv._chave_de_data("14/08/2026") == (1, 2026, 8, 14)
    for invalida in ("99/99/2026", "14/08/26", "1/2/2026", "31/02/2026", "", "sem data"):
        assert mv._chave_de_data(invalida) == (0,), invalida
