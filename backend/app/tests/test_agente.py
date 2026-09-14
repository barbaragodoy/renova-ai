"""Testes do agente da via 1, sem rede e sem Databricks.

Executor falso e modelo falso. O que se testa aqui é o que precisa valer
mesmo quando o modelo colabora e mesmo quando ele não colabora: o setor
injetado, o número verificado e a degradação.

Roda com pytest ou direto: `python3 backend/app/tests/test_agente.py`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.app.agente import composicao
from backend.app.agente.ferramentas import Contexto, Ferramentas
from backend.app.agente.conhecimento import ConhecimentoKA
from backend.app.agente.orquestrador import Orquestrador
from backend.app.agente import contrato_log, intencao, registro


CTX = Contexto(email="rep@ache.com.br", matricula="12345", setor="010105010351", linha="1")


class ExecutorFalso:
    """Guarda o SQL e os parâmetros, e devolve o que o teste mandar."""

    def __init__(self, respostas=None):
        self.chamadas: list[tuple[str, dict]] = []
        self.respostas = list(respostas or [])

    def query(self, sql, params=None):
        self.chamadas.append((" ".join(sql.split()), params or {}))
        return self.respostas.pop(0) if self.respostas else []


class ModeloFalso:
    """Devolve as mensagens combinadas, uma por volta."""

    def __init__(self, roteiro):
        self.roteiro = list(roteiro)
        self.recebido: list[list[dict]] = []

    def conversar(self, mensagens, ferramentas):
        self.recebido.append(list(mensagens))
        return self.roteiro.pop(0) if self.roteiro else {"content": ""}


def _chamada(nome, argumentos, ident="c1"):
    return {"id": ident, "type": "function",
            "function": {"name": nome, "arguments": json.dumps(argumentos)}}


# ---------------------------------------------------------------- setor

def test_toda_consulta_de_medico_carrega_o_setor_do_contexto():
    ex = ExecutorFalso()
    f = Ferramentas(CTX, ex)
    f.buscar_medico("silva")
    f.perfil_do_medico("MG0027247")
    f.visitas_pendentes(3)
    f.participacao_no_agrupamento("TREZETE")
    assert len(ex.chamadas) == 4
    for sql, params in ex.chamadas:
        assert "SETOR = :setor" in sql, sql
        assert params["setor"] == CTX.setor


def test_o_modelo_nao_tem_onde_escrever_um_setor():
    """Nenhuma ferramenta declara setor. É o recorte que ele não consegue expressar."""
    for ferramenta in Ferramentas(CTX, ExecutorFalso()).catalogo():
        propriedades = ferramenta.parametros.get("properties", {})
        assert "setor" not in propriedades, ferramenta.nome
        assert not any("setor" in k.lower() for k in propriedades), ferramenta.nome


def test_setor_citado_na_pergunta_nao_muda_a_consulta():
    ex = ExecutorFalso()
    Ferramentas(CTX, ex).buscar_medico("médico do setor 010103030154")
    _, params = ex.chamadas[0]
    assert params["setor"] == CTX.setor


def test_busca_normaliza_acento_e_caixa_dos_dois_lados():
    ex = ExecutorFalso()
    Ferramentas(CTX, ex).buscar_medico("josé")
    assert ex.chamadas[0][1]["padrao"] == "%JOSE%"


def test_meses_fora_da_faixa_e_contido():
    ex = ExecutorFalso()
    f = Ferramentas(CTX, ex)
    f.visitas_pendentes(999)
    f.visitas_pendentes(-4)
    f.visitas_pendentes("tres")
    assert [c[1]["meses"] for c in ex.chamadas] == [24, 1, 3]


def test_percentual_chega_ao_modelo_ja_formatado():
    """3,6% e nao 3.6: a forma certa e a unica que existe no retorno."""
    ex = ExecutorFalso([[{"UFCRM": "MG1", "PARTICIPACAO_ACHE_PCT": 3.6}],
                        [{"AGRUPAMENTO": "TREZETE", "PARTICIPACAO_PCT": 34.5}]])
    f = Ferramentas(CTX, ex)
    assert f.perfil_do_medico("MG1")[0]["PARTICIPACAO_ACHE_PCT"] == "3,6%"
    assert f.participacao_no_agrupamento("TREZETE")[0]["PARTICIPACAO_PCT"] == "34,5%"


def test_percentual_formata_tambem_quando_o_executor_devolve_texto():
    """A SQL Statement Execution API devolve tudo como string.

    A primeira versao pulava string e por isso nao formatava nada no caminho
    real, so no teste, que alimentava float.
    """
    ex = ExecutorFalso([[{"UFCRM": "MG1", "PARTICIPACAO_ACHE_PCT": "3.6"}]])
    assert Ferramentas(CTX, ex).perfil_do_medico("MG1")[0]["PARTICIPACAO_ACHE_PCT"] == "3,6%"


def test_percentual_ja_formatado_nao_e_formatado_de_novo():
    ex = ExecutorFalso([[{"UFCRM": "MG1", "PARTICIPACAO_ACHE_PCT": "3,6%"}]])
    assert Ferramentas(CTX, ex).perfil_do_medico("MG1")[0]["PARTICIPACAO_ACHE_PCT"] == "3,6%"


def test_o_verificador_enxerga_numero_dentro_do_percentual_formatado():
    retornos = [("perfil_do_medico", [{"PARTICIPACAO_ACHE_PCT": "3,6%"}])]
    assert composicao.conferir_numeros("A participação está em 3,6%.", retornos).aprovado


# ---------------------------------------------------------------- número

def test_numero_que_veio_de_ferramenta_passa():
    retornos = [("perfil_do_medico", [{"PARTICIPACAO_ACHE_PCT": 3.6, "POSICAO_RANKING": 36}])]
    v = composicao.conferir_numeros("A participação está em 3,6% e ele é o 36 do ranking.", retornos)
    assert v.aprovado, v.motivo


def test_arredondamento_e_invencao_e_barrado():
    retornos = [("perfil_do_medico", [{"PARTICIPACAO_ACHE_PCT": 3.6}])]
    v = composicao.conferir_numeros("A participação está em 4%.", retornos)
    assert not v.aprovado
    assert "4" in v.numeros_sem_origem


def test_contar_a_lista_devolvida_e_permitido():
    retornos = [("buscar_medico", [{"UFCRM": "MG1"}, {"UFCRM": "MG2"}, {"UFCRM": "MG3"}])]
    v = composicao.conferir_numeros("Encontrei 3 profissionais com esse nome.", retornos)
    assert v.aprovado, v.motivo


def test_ufcrm_e_codigo_de_setor_nao_sao_lidos_como_numero():
    v = composicao.conferir_numeros("O UFCRM é MG0027247 no setor 010105010351.", [])
    assert v.aprovado, v.motivo


def test_a_palavra_mercado_e_barrada():
    v = composicao.conferir_numeros("A Aché lidera esse mercado.", [])
    assert not v.aprovado
    assert "mercado" in v.palavras_proibidas


def test_lista_numerada_nao_e_confundida_com_afirmacao():
    """O caso que apagou dois medicos da resposta em 19/08.

    Seis itens numerados: 1 e 2 sao livres, 6 casava com a contagem de linhas,
    e 3, 4 e 5 eram acusados de invencao. A degradacao removia esses itens e a
    lista saia menor sem ninguem perceber.
    """
    linhas = [{"NOME_MEDICO": f"M{i}", "MESES_DESDE_ULTIMA_VISITA": 4} for i in range(6)]
    texto = "\n".join(f"{i}. Profissional M{i} - 4 meses" for i in range(1, 7))
    v = composicao.conferir_numeros(texto, [("visitas_pendentes", linhas)])
    assert v.aprovado, v.motivo
    assert composicao.degradar(texto, v) == texto


def test_marcador_de_lista_nao_esconde_numero_inventado_no_corpo():
    """Tirar o marcador nao pode virar porta de entrada para invencao."""
    v = composicao.conferir_numeros("1. A participação chegou a 47%.", [])
    assert not v.aprovado
    assert "47" in v.numeros_sem_origem


def test_degradar_remove_a_frase_e_preserva_o_resto():
    texto = "Ele é cardiologista. A participação chegou a 47%. Vale falar de adesão."
    v = composicao.conferir_numeros(texto, [])
    limpo = composicao.degradar(texto, v)
    assert "47" not in limpo
    assert "cardiologista" in limpo
    assert "adesão" in limpo


# ---------------------------------------------------------------- laço

def test_o_laco_executa_a_ferramenta_e_devolve_o_texto():
    ex = ExecutorFalso([[{"UFCRM": "MG0027247", "NOME_MEDICO": "LOESTER", "POSICAO_RANKING": 36}]])
    modelo = ModeloFalso([
        {"tool_calls": [_chamada("buscar_medico", {"termo_busca": "loester"})]},
        {"content": "Encontrei o profissional, posição 36 no seu ranking."},
    ])
    r = Orquestrador(CTX, ex, modelo).responder("quem é o loester?")
    assert r.ferramentas_usadas == ["buscar_medico"]
    assert not r.degradada
    assert "36" in r.texto


def test_ferramenta_inexistente_volta_como_erro_e_nao_estoura():
    modelo = ModeloFalso([
        {"tool_calls": [_chamada("consultar_faturamento", {})]},
        {"content": "Isso está fora do que eu respondo."},
    ])
    r = Orquestrador(CTX, ExecutorFalso(), modelo).responder("qual o faturamento?")
    assert not r.degradada
    assert "fora" in r.texto.lower()


def test_modelo_teimoso_tem_a_frase_removida():
    """Duas respostas com número inventado: reescreve uma vez, depois degrada."""
    ex = ExecutorFalso([[{"UFCRM": "MG1", "PARTICIPACAO_ACHE_PCT": 3.6}]])
    modelo = ModeloFalso([
        {"tool_calls": [_chamada("perfil_do_medico", {"ufcrm": "MG1"})]},
        {"content": "Boa abordagem pela adesão. A participação está em 47%."},
        {"content": "Boa abordagem pela adesão. A participação está em 47%."},
    ])
    r = Orquestrador(CTX, ex, modelo).responder("como abordar?")
    assert r.degradada
    assert "47" not in r.texto
    assert "adesão" in r.texto


def test_modelo_se_corrige_na_reescrita():
    ex = ExecutorFalso([[{"UFCRM": "MG1", "PARTICIPACAO_ACHE_PCT": 3.6}]])
    modelo = ModeloFalso([
        {"tool_calls": [_chamada("perfil_do_medico", {"ufcrm": "MG1"})]},
        {"content": "A participação está em 47%."},
        {"content": "A participação está em 3,6%."},
    ])
    r = Orquestrador(CTX, ex, modelo).responder("qual a participação?")
    assert not r.degradada
    assert "3,6" in r.texto


def test_conhecimento_indisponivel_degrada_em_vez_de_quebrar():
    class KaQuebrado:
        def buscar(self, pergunta):
            raise RuntimeError("502")

    r = Ferramentas(CTX, ExecutorFalso(), conhecimento=KaQuebrado()).buscar_conhecimento("x")
    assert "indisponivel" in r[0]


def test_resposta_vazia_do_modelo_vira_recusa_honesta():
    r = Orquestrador(CTX, ExecutorFalso(), ModeloFalso([{"content": ""}])).responder("oi")
    assert r.degradada
    assert "confiável" in r.texto


def test_log_nao_carrega_texto_de_pergunta_nem_de_resposta():
    ex = ExecutorFalso([[{"UFCRM": "MG1"}]])
    modelo = ModeloFalso([
        {"tool_calls": [_chamada("perfil_do_medico", {"ufcrm": "MG1"})]},
        {"content": "Pronto."},
    ])
    r = Orquestrador(CTX, ex, modelo).responder("dado sensível do propagandista")
    serializado = json.dumps(r.resumo_para_log(), ensure_ascii=False)
    assert "sensível" not in serializado
    assert "Pronto" not in serializado
    assert r.resumo_para_log()["qtd_ferramentas"] == 1


# ---------------------------------------------------------------- conhecimento

_URL_KA = (
    "https://adb-3551324376903721.1.azuredatabricks.net/ajax-api/2.0/fs/files/Volumes/"
    "acheinfo_dev/renovai/volume_renovai_dev/kb-personas/medicos/PERFORMANCE.md"
    "#:~:text=%23%20Perfil%20Performance%0A%0A%2A%2AFonte%3A%2A%2A%20Guia"
)


def _resposta_ka(blocos, sources_used=True):
    return {"output": [{"type": "message", "content": blocos}],
            "custom_outputs": {"sources_used": sources_used}}


def test_o_documento_sai_da_url_sem_o_trecho_citado():
    """So o nome do arquivo vai para o log.

    A URL do KA carrega o trecho da KB embutido no fragmento `#:~:text=`.
    Guardar a URL inteira colocaria conteudo da base dentro da tabela de log.
    """
    assert ConhecimentoKA._documento(_URL_KA) == "PERFORMANCE.md"
    assert ConhecimentoKA._documento("https://x/sem/arquivo") == ""


def test_a_resposta_do_ka_vem_quebrada_em_blocos_e_e_remontada():
    r = ConhecimentoKA._montar(_resposta_ka([
        {"type": "output_text", "text": "Os perfis são: ", "annotations": [{"url": _URL_KA}]},
        {"type": "output_text", "text": "Performance e Analítico.", "annotations": []},
    ]))
    assert r["resposta"] == "Os perfis são: Performance e Analítico."
    assert r["documentos"] == ["PERFORMANCE.md"]
    assert r["apoiado_em_documento"] is True


def test_documento_repetido_entra_uma_vez_so():
    r = ConhecimentoKA._montar(_resposta_ka([
        {"type": "output_text", "text": "a", "annotations": [{"url": _URL_KA}]},
        {"type": "output_text", "text": "b", "annotations": [{"url": _URL_KA}]},
    ]))
    assert r["documentos"] == ["PERFORMANCE.md"]


def test_ka_sem_conteudo_devolve_indisponivel():
    assert "indisponivel" in ConhecimentoKA._montar(_resposta_ka([]))


def test_passagens_diferentes_do_mesmo_arquivo_nao_se_perdem():
    """Achado do julgamento de 20/08: so o primeiro hash sobrevivia."""
    r = ConhecimentoKA._montar(_resposta_ka([
        {"type": "output_text", "text": "a", "annotations": [{"url": _URL_KA}]},
        {"type": "output_text", "text": "b",
         "annotations": [{"url": _URL_KA.split("#")[0] + "#:~:text=outro%20trecho"}]},
    ]))
    assert r["documentos"] == ["PERFORMANCE.md"]
    assert len(r["trechos"]["PERFORMANCE.md"]) == 2


def test_citacao_sem_passagem_nao_finge_ter_hash():
    """Marcador declarado, nao hash do nome: evidencia nao pode mentir."""
    class KaSemTrecho:
        def buscar(self, pergunta):
            return [{"resposta": "texto", "documentos": ["X.md"], "trechos": {},
                     "apoiado_em_documento": True}]

    modelo = ModeloComUso([
        {"tool_calls": [_chamada("buscar_conhecimento", {"pergunta": "x"})]},
        {"content": "Pronto."},
    ])
    r = _interacao(modelo, ExecutorFalso(), conhecimento=KaSemTrecho())
    linha = registro.montar(r, CTX, id_conversa="c1", turno=1,
                            ts_inicio=__import__("datetime").datetime.now(
                                __import__("datetime").timezone.utc))
    assert registro.SEM_TRECHO in linha["documentos_citados"]
    assert "documento:" not in linha["documentos_citados"]


def test_o_documento_citado_chega_ao_log_do_orquestrador():
    """Criterio de aceite da T1.3."""
    class KaFalso:
        def buscar(self, pergunta):
            return [{"resposta": "texto da base", "documentos": ["ANALITICO.md"],
                     "trechos": {"ANALITICO.md": ["h1"]}, "apoiado_em_documento": True}]

    modelo = ModeloFalso([
        {"tool_calls": [_chamada("buscar_conhecimento", {"pergunta": "perfil analítico"})]},
        {"content": "Segundo o material, esse perfil valoriza processo."},
    ])
    orq = Orquestrador(CTX, ExecutorFalso(), modelo, conhecimento=KaFalso())
    r = orq.responder("como abordar um médico analítico?")
    assert r.documentos_citados == ["ANALITICO.md"]
    assert r.resumo_para_log()["documentos"] == "ANALITICO.md"


def test_o_log_nao_leva_o_texto_da_base_de_conhecimento():
    class KaFalso:
        def buscar(self, pergunta):
            return [{"resposta": "conteúdo confidencial da KB", "documentos": ["X.md"],
                     "apoiado_em_documento": True}]

    modelo = ModeloFalso([
        {"tool_calls": [_chamada("buscar_conhecimento", {"pergunta": "x"})]},
        {"content": "Pronto."},
    ])
    r = Orquestrador(CTX, ExecutorFalso(), modelo, conhecimento=KaFalso()).responder("x")
    assert "confidencial" not in json.dumps(r.resumo_para_log(), ensure_ascii=False)


# ---------------------------------------------------------------- registro

class ModeloComUso(ModeloFalso):
    """Igual ao falso, mas devolvendo `Volta`, como o endpoint real."""

    def conversar(self, mensagens, ferramentas):
        from backend.app.agente.modelo import Volta
        return Volta(mensagem=super().conversar(mensagens, ferramentas),
                     endpoint="endpoint-de-teste", modelo="modelo-de-teste",
                     tokens_entrada=100, tokens_saida=20)


def _interacao(modelo, executor, pergunta="quem e o loester?", conhecimento=None):
    return Orquestrador(CTX, executor, modelo, conhecimento=conhecimento).responder(pergunta)


def test_a_linha_do_log_passa_no_contrato():
    ex = ExecutorFalso([[{"UFCRM": "MG1", "NOME_MEDICO": "LOESTER", "POSICAO_RANKING": 36,
                          "CICLO_REFERENCIA": "202608"}]])
    modelo = ModeloComUso([
        {"tool_calls": [_chamada("buscar_medico", {"termo_busca": "loester"})]},
        {"content": "Encontrei o profissional, posição 36. Dados de 202608."},
    ])
    r = _interacao(modelo, ex)
    linha = registro.montar(r, CTX, id_conversa="c1", turno=1,
                            ts_inicio=__import__("datetime").datetime.now(
                                __import__("datetime").timezone.utc))
    assert set(linha) == set(registro.COLUNAS)
    assert linha["via"] == "via_1"
    assert linha["versao_esquema"] == 2
    assert linha["tokens_entrada"] == 200   # duas voltas ao modelo
    assert linha["sucesso"] is True


def test_todo_numero_exibido_tem_proveniencia():
    """O contrato recusa numero sem linha de verificacao. Aqui isso e verdade por construcao."""
    ex = ExecutorFalso([[{"UFCRM": "MG1", "NOME_MEDICO": "LOESTER", "POSICAO_RANKING": 36,
                          "CICLO_REFERENCIA": "202608"}]])
    modelo = ModeloComUso([
        {"tool_calls": [_chamada("buscar_medico", {"termo_busca": "loester"})]},
        {"content": "Posição 36 no ranking. Dados de 202608."},
    ])
    r = _interacao(modelo, ex)
    itens = r.veredito.itens
    assert {i["numero"] for i in itens} == {"36", "202608"}
    por_numero = {i["numero"]: i for i in itens}
    assert por_numero["36"]["campo"] == "POSICAO_RANKING"
    assert por_numero["202608"]["campo"] == "CICLO_REFERENCIA"
    assert all(i["chamada_id"] == r.chamadas[0].chamada_id for i in itens)
    assert all(i["resultado_hash"] == r.chamadas[0].resultado_hash for i in itens)


def test_o_argumento_da_ferramenta_e_origem_legitima():
    """Regressao pega no julgamento independente de 20/08.

    "sem visita ha mais de 4 meses" e fiel quando 4 foi o filtro pedido, mesmo
    que nenhuma linha devolvida tenha exatamente 4. Ao trocar as tuplas de
    retorno pelos registros de chamada, o universo passou a ignorar os
    argumentos e a frase voltava a ser removida.
    """
    from backend.app.agente.composicao import Chamada, verificar
    ch = Chamada(chamada_id="f1", ferramenta="visitas_pendentes",
                 linhas=[{"NOME_MEDICO": "A", "MESES_DESDE_ULTIMA_VISITA": 10}],
                 resultado_hash="h", parametros='{"meses": 4}')
    v = verificar("Sem visita ha mais de 4 meses: um profissional, com 10 meses.", [ch])
    assert v.aprovado, v.motivo
    por_numero = {i["numero"]: i for i in v.itens}
    assert por_numero["4"]["campo"] == "<argumento>"
    assert por_numero["10"]["campo"] == "MESES_DESDE_ULTIMA_VISITA"


def test_valor_devolvido_tem_preferencia_sobre_argumento():
    """Se o numero existe nas duas origens, a proveniencia aponta o valor devolvido."""
    from backend.app.agente.composicao import Chamada, verificar
    ch = Chamada(chamada_id="f1", ferramenta="visitas_pendentes",
                 linhas=[{"MESES_DESDE_ULTIMA_VISITA": 4}],
                 resultado_hash="h", parametros='{"meses": 4}')
    v = verificar("Quatro meses: 4.", [ch])
    assert v.itens[0]["campo"] == "MESES_DESDE_ULTIMA_VISITA"


def test_numero_apoiado_em_chamada_que_falhou_nao_conta():
    """O contrato recusa verificacao apoiada em chamada com erro, e com razao."""
    from backend.app.agente.composicao import Chamada, verificar
    ruim = Chamada(chamada_id="f1", ferramenta="perfil_do_medico",
                   linhas=[{"erro": "a consulta falhou", "codigo": 47}],
                   resultado_hash="h", sucesso=False)
    v = verificar("A participação está em 47%.", [ruim])
    assert not v.aprovado
    assert "47" in v.numeros_sem_origem
    assert v.itens == []


def test_a_degradacao_nao_deixa_numero_orfao_no_log():
    """Depois de degradar, numeros_exibidos so tem o que sobrou no texto entregue."""
    ex = ExecutorFalso([[{"UFCRM": "MG1", "PARTICIPACAO_ACHE_PCT": 3.6}]])
    modelo = ModeloComUso([
        {"tool_calls": [_chamada("perfil_do_medico", {"ufcrm": "MG1"})]},
        {"content": "Boa abordagem pela adesão. A participação está em 47%."},
        {"content": "Boa abordagem pela adesão. A participação está em 47%."},
    ])
    r = _interacao(modelo, ex, pergunta="como abordar?")
    assert r.degradada
    assert "47" not in r.texto
    assert "47" not in r.veredito.numeros_exibidos
    linha = registro.montar(r, CTX, id_conversa="c1", turno=1,
                            ts_inicio=__import__("datetime").datetime.now(
                                __import__("datetime").timezone.utc))
    assert linha["sucesso"] is False
    assert linha["erro_tipo"] == "verificacao_degradou"


def test_via_recusa_nao_grava_token_de_modelo_como_zero():
    """Interacao sem chamada ao modelo tem agregado nulo, nao zero. Regra do contrato."""
    r = _interacao(ModeloFalso([{"content": "Isso está fora do que eu respondo."}]),
                   ExecutorFalso(), pergunta="qual o faturamento?")
    linha = registro.montar(r, CTX, id_conversa="c1", turno=1,
                            ts_inicio=__import__("datetime").datetime.now(
                                __import__("datetime").timezone.utc))
    assert linha["via"] == "recusa"
    assert linha["tokens_entrada"] is None and linha["custo_total"] is None


def test_a_mesma_pergunta_gera_a_mesma_chave():
    a = contrato_log.id_interacao("c1", 1, "quem e o loester?")
    b = contrato_log.id_interacao("c1", 1, "quem e o loester?")
    assert a == b
    assert a != contrato_log.id_interacao("c1", 2, "quem e o loester?")


def test_o_merge_nao_atualiza_linha_existente():
    sql = registro.sql_merge("t")
    assert "WHEN NOT MATCHED THEN INSERT" in sql
    assert "WHEN MATCHED" not in sql.replace("WHEN NOT MATCHED", "")


def test_intencao_agrupa_a_mesma_pergunta_sobre_medicos_diferentes():
    a = intencao.normalizar("Vou visitar o Dr. Loester hoje, qual a melhor abordagem?",
                            ["LOESTER DA SILVA NEIVA JUNIOR"])
    b = intencao.normalizar("vou visitar a dra carla silveira hoje, qual a melhor abordagem",
                            ["CARLA LADEIRA GOMES DA SILVEIRA"])
    assert a == b
    assert intencao.hash_da_intencao(a) == intencao.hash_da_intencao(b)


def test_intencao_nao_junta_perguntas_diferentes():
    a = intencao.normalizar("quem esta sem visita ha 4 meses?")
    b = intencao.normalizar("qual a participacao do trezete?")
    assert a != b


def test_o_contrato_aceita_decimal_no_custo():
    """Achado de 19/08: a versao aprovada no G1 recusava Decimal, o tipo da coluna."""
    from decimal import Decimal
    s = contrato_log.serializar_chamadas([{
        "chamada_id": "m1", "endpoint": "e", "modelo": "m", "tokens_entrada": 10,
        "tokens_saida": 5, "tokens_cache": 0, "tarifa_entrada": Decimal("0.003"),
        "tarifa_saida": Decimal("0.015"), "moeda": "USD", "custo": Decimal("0.000105")}])
    assert '"custo": "0.000105"' in s, s
    assert Decimal(json.loads(s)["chamadas"][0]["custo"]) == Decimal("0.000105")


if __name__ == "__main__":
    testes = [(n, o) for n, o in sorted(globals().items())
              if n.startswith("test_") and callable(o)]
    falhas = 0
    for nome, fn in testes:
        try:
            fn()
            print(f"  ok   {nome}")
        except AssertionError as e:
            falhas += 1
            print(f"  FALHOU {nome}: {e}")
        except Exception as e:  # noqa: BLE001
            falhas += 1
            print(f"  ERRO {nome}: {type(e).__name__}: {e}")
    print(f"\n{len(testes) - falhas} de {len(testes)} passaram")
    sys.exit(1 if falhas else 0)


# --------------------------------------------------------------- continuidade


def test_extrai_a_linha_de_sugestoes_e_limpa_o_texto():
    texto = "Raquel está há 14 meses sem visita.\nSUGESTOES: Perfil da Raquel | Produtos para a Raquel"
    limpo, sugestoes = composicao.extrair_sugestoes(texto)
    assert limpo == "Raquel está há 14 meses sem visita."
    assert sugestoes == ["Perfil da Raquel", "Produtos para a Raquel"]


def test_sem_linha_de_sugestoes_o_texto_volta_intacto():
    limpo, sugestoes = composicao.extrair_sugestoes("Só a resposta, sem sugestão.")
    assert limpo == "Só a resposta, sem sugestão."
    assert sugestoes == []


def test_sugestoes_repetidas_e_vazias_sao_descartadas():
    _, sugestoes = composicao.extrair_sugestoes("x\nSUGESTOES: a | | A | b | c | d")
    assert sugestoes == ["a", "b", "c"]


def test_numero_dentro_de_sugestao_nao_e_acusado_pelo_verificador():
    # "3 meses" na sugestão não é afirmação sobre o dado. Sem a extração antes
    # do verificador, a resposta inteira seria degradada por um número que o
    # usuário nem vê como texto.
    modelo = ModeloFalso([
        {"role": "assistant",
         "content": "Nenhuma visita pendente.\nSUGESTOES: Quem está sem visita há 3 meses?"},
    ])
    orq = Orquestrador(CTX, ExecutorFalso(), modelo)
    r = orq.responder("tenho pendências?")
    assert not r.degradada
    assert r.texto == "Nenhuma visita pendente."
    assert r.sugestoes == ["Quem está sem visita há 3 meses?"]


def test_o_historico_entra_entre_o_system_e_a_pergunta():
    """Reproduz o fluxo real: o turno anterior guardado na memória carrega as
    sugestões que saíram do texto da tela, no formato que o router grava."""
    from backend.app.agente import memoria
    memoria.esquecer("rep@ache.com.br|c-hist")
    # turno anterior, como o router grava depois de uma resposta do agente
    memoria.registrar("rep@ache.com.br|c-hist", "user", "o que você faz?")
    memoria.registrar(
        "rep@ache.com.br|c-hist", "assistant",
        "Posso ajudar de algumas formas.\nSugestões oferecidas: Buscar um médico | Visitas pendentes",
    )
    modelo = ModeloFalso([{"role": "assistant", "content": "ok"}])
    orq = Orquestrador(CTX, ExecutorFalso(), modelo)
    orq.responder("quero a segunda opção",
                  historico=memoria.historico("rep@ache.com.br|c-hist"))
    enviadas = modelo.recebido[0]
    papeis = [m["role"] for m in enviadas]
    assert papeis == ["system", "user", "assistant", "user"]
    assert enviadas[-1]["content"] == "quero a segunda opção"
    # o modelo enxerga as opções a que "a segunda" se refere
    assert "Visitas pendentes" in enviadas[2]["content"]
    memoria.esquecer("rep@ache.com.br|c-hist")


def test_historico_malformado_e_ignorado_sem_quebrar():
    modelo = ModeloFalso([{"role": "assistant", "content": "ok"}])
    orq = Orquestrador(CTX, ExecutorFalso(), modelo)
    r = orq.responder("oi", historico=[
        {"role": "tool", "content": "não entra"},
        {"role": "user", "content": "  "},
        "lixo",
        {"role": "user", "content": "essa entra"},
    ])
    enviadas = modelo.recebido[0]
    assert [m["role"] for m in enviadas] == ["system", "user", "user"]
    assert r.texto == "ok"


def test_memoria_guarda_devolve_e_esquece():
    from backend.app.agente import memoria
    memoria.esquecer("c1")
    memoria.registrar("c1", "user", "pergunta um")
    memoria.registrar("c1", "assistant", "resposta um")
    assert memoria.historico("c1") == [
        {"role": "user", "content": "pergunta um"},
        {"role": "assistant", "content": "resposta um"},
    ]
    memoria.esquecer("c1")
    assert memoria.historico("c1") == []


def test_memoria_sem_id_nao_guarda_nada():
    from backend.app.agente import memoria
    memoria.registrar("", "user", "não deve entrar")
    assert memoria.historico("") == []


def test_memoria_respeita_o_teto_de_conversas():
    """A revisão de 31/08/2026 mostrou o dicionário estabilizando em 501 com o
    teto declarado de 500. A remoção agora acontece depois da inserção."""
    from backend.app.agente import memoria
    import backend.app.agente.memoria as m
    original = dict(m._conversas)
    try:
        m._conversas.clear()
        for i in range(memoria.MAX_CONVERSAS + 7):
            memoria.registrar(f"conv-{i}", "user", "oi")
        assert len(m._conversas) == memoria.MAX_CONVERSAS
        # a mais recente sobrevive; a mais antiga caiu
        assert f"conv-{memoria.MAX_CONVERSAS + 6}" in m._conversas
        assert "conv-0" not in m._conversas
    finally:
        m._conversas.clear()
        m._conversas.update(original)


def test_memoria_corta_os_turnos_mais_antigos():
    from backend.app.agente import memoria
    memoria.esquecer("c2")
    for i in range(memoria.MAX_TURNOS * 2 + 5):
        memoria.registrar("c2", "user", f"turno {i}")
    turnos = memoria.historico("c2")
    assert len(turnos) == memoria.MAX_TURNOS * 2
    assert turnos[-1]["content"] == f"turno {memoria.MAX_TURNOS * 2 + 4}"
    memoria.esquecer("c2")


def test_memoria_nao_revive_conversa_vencida():
    """Achado da segunda rodada de 31/08/2026: a leitura atualizava o toque e
    a conversa vencida nunca expirava. O TTL agora vale também na leitura."""
    from backend.app.agente import memoria
    import backend.app.agente.memoria as m
    memoria.esquecer("c-ttl")
    memoria.registrar("c-ttl", "user", "oi")
    with m._trava:
        m._conversas["c-ttl"]["tocada_em"] -= memoria.TTL_SEGUNDOS + 1
    assert memoria.historico("c-ttl") == []
    with m._trava:
        assert "c-ttl" not in m._conversas


def test_conversa_serializa_o_ciclo_da_mesma_chave():
    """Duas threads na mesma conversa nunca se intercalam: cada seção crítica
    grava começo e fim, e os pares saem inteiros."""
    import threading
    import time
    from backend.app.agente import memoria
    memoria.esquecer("c-serial")
    eventos: list[str] = []

    def ciclo(nome: str) -> None:
        with memoria.conversa("c-serial"):
            eventos.append(f"{nome}:inicio")
            # o sono força a troca de thread: sem a trava, os pares
            # intercalariam com certeza prática e o teste falharia
            time.sleep(0.002)
            eventos.append(f"{nome}:fim")

    threads = [threading.Thread(target=ciclo, args=(f"t{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(eventos) == 12
    for i in range(0, 12, 2):
        assert eventos[i].endswith(":inicio")
        assert eventos[i + 1] == eventos[i].replace(":inicio", ":fim")
    memoria.esquecer("c-serial")


def test_conversa_readquire_quando_a_trava_foi_trocada():
    """A janela da quarta rodada: a trava pode sair do registro entre a
    devolução e o acquire. Sem a reconferência, a thread entraria pela trava
    velha; o teste prova que ela fica presa na nova até a liberação."""
    import threading
    import time
    from backend.app.agente import memoria
    import backend.app.agente.memoria as m
    memoria.esquecer("c-troca")
    velha = threading.Lock()
    velha.acquire()  # simula outra requisição em voo com um objeto que saiu do registro
    with m._trava:
        m._travas_por_conversa["c-troca"] = velha
    resultado: list[str] = []

    def tenta() -> None:
        with memoria.conversa("c-troca"):
            resultado.append("entrou")

    t = threading.Thread(target=tenta)
    t.start()
    time.sleep(0.05)  # a thread fica bloqueada na velha
    # troca a trava no registro e segura a nova antes de liberar a velha
    nova = threading.Lock()
    nova.acquire()
    with m._trava:
        m._travas_por_conversa["c-troca"] = nova
    velha.release()
    time.sleep(0.15)
    # sem a reconferência, a thread teria entrado pela velha; com ela, a
    # thread detectou a troca e está presa na nova
    assert resultado == []
    assert t.is_alive()
    nova.release()
    t.join(timeout=5)
    assert resultado == ["entrou"]
    memoria.esquecer("c-troca")


def test_registro_de_travas_nao_cresce_sem_limite():
    """O invariante é de pertencimento: trava morta, sem conversa viva e sem
    uso, não sobrevive à aquisição seguinte. Com chaves todas mortas, o
    registro carrega no máximo a trava em voo e a anterior ainda não varrida."""
    from backend.app.agente import memoria
    import backend.app.agente.memoria as m
    with m._trava:
        travas_originais = dict(m._travas_por_conversa)
        m._travas_por_conversa.clear()
    try:
        pico = 0
        for i in range(200):
            with memoria.conversa(f"trava-{i}"):
                with m._trava:
                    pico = max(pico, len(m._travas_por_conversa))
        assert pico <= 2
    finally:
        with m._trava:
            m._travas_por_conversa.clear()
            m._travas_por_conversa.update(travas_originais)


def test_trava_de_conversa_viva_sobrevive():
    """Conversa com memória viva mantém a trava no registro entre aquisições:
    o pertencimento segue `_conversas`, que já tem TTL e teto próprios."""
    from backend.app.agente import memoria
    import backend.app.agente.memoria as m
    with m._trava:
        travas_originais = dict(m._travas_por_conversa)
        m._travas_por_conversa.clear()
    try:
        with memoria.conversa("c-viva"):
            memoria.registrar("c-viva", "user", "oi")
        for i in range(20):
            with memoria.conversa(f"morta-{i}"):
                pass
        with m._trava:
            assert "c-viva" in m._travas_por_conversa
    finally:
        memoria.esquecer("c-viva")
        with m._trava:
            m._travas_por_conversa.clear()
            m._travas_por_conversa.update(travas_originais)


def test_trava_em_uso_nunca_e_removida_pela_contencao():
    from backend.app.agente import memoria
    import backend.app.agente.memoria as m
    with m._trava:
        travas_originais = dict(m._travas_por_conversa)
        m._travas_por_conversa.clear()
    try:
        with memoria.conversa("trava-segurada"):
            for i in range(memoria.MAX_CONVERSAS + 50):
                with memoria.conversa(f"enche-{i}"):
                    pass
            with m._trava:
                assert "trava-segurada" in m._travas_por_conversa
    finally:
        with m._trava:
            m._travas_por_conversa.clear()
            m._travas_por_conversa.update(travas_originais)


# ------------------------------------------------------------- observações


def test_observacoes_filtram_setor_efetiva_e_limitam():
    """A consulta injeta o setor autenticado, exige visita efetiva e limita.

    O texto da observação é conteúdo, nunca entra no SQL: só setor e UFCRM
    viajam como parâmetro."""
    from backend.app.agente.ferramentas import Ferramentas, LIMITE_OBSERVACOES
    ex = ExecutorFalso([[{"DATA_VISITA": "14/08/2026", "VISITA_TIPO": "PRESENCIAL",
                          "COMENTARIOS": "PEDIU AMOSTRA DE FUSOR"}]])
    f = Ferramentas(CTX, ex)
    with patch(
        "backend.app.db.sql_dialect.get_settings",
        return_value=type("Settings", (), {"data_source": "local"})(),
    ):
        linhas = f.observacoes_do_medico(" rj0462552 ")
    assert linhas[0]["COMENTARIOS"] == "PEDIU AMOSTRA DE FUSOR"
    sql, params = ex.chamadas[0]
    # Le pela view, e nao pela tabela de origem: medido em 04/09/2026, o
    # service principal do portal nao e membro de nenhum grupo
    # `user-renovai-*` e a leitura direta da dmn_produtividade_dev falha com
    # INSUFFICIENT_PERMISSIONS. A view roda com a permissao do dono e ja
    # filtra VISITA_EFETIVA, por isso o filtro saiu do SQL daqui.
    assert "vw_visitacao_comentarios" in sql
    assert "dmn_produtividade_dev" not in sql
    assert "VISITA_EFETIVA" not in sql
    # setor e ufcrm por parametro nomeado, nunca interpolados
    assert "v.SETOR = :setor AND v.UFCRM = :ufcrm" in sql
    # ordena a coluna original: o alias da projecao e texto dd/MM/yyyy e
    # ordenaria 31/01/2025 acima de 01/12/2026
    assert "ORDER BY v.DATA_VISITA DESC" in sql
    assert "TO_CHAR(v.DATA_VISITA, 'DD/MM/YYYY')" in sql
    assert "DATE_FORMAT" not in sql
    assert f"LIMIT {LIMITE_OBSERVACOES}" in sql
    assert params == {"setor": CTX.setor, "ufcrm": "RJ0462552"}


def test_observacoes_usam_date_format_no_databricks():
    from backend.app.agente.ferramentas import Ferramentas

    ex = ExecutorFalso([{"DATA_VISITA": "14/08/2026"}])
    with patch(
        "backend.app.db.sql_dialect.get_settings",
        return_value=type("Settings", (), {"data_source": "databricks"})(),
    ):
        Ferramentas(CTX, ex).observacoes_do_medico("RJ0462552")

    sql, _ = ex.chamadas[0]
    assert "DATE_FORMAT(v.DATA_VISITA, 'dd/MM/yyyy')" in sql
    assert "TO_CHAR" not in sql


def test_numero_de_observacao_nao_autoriza_afirmacao():
    """"Retornar em 15 dias" no comentário autorizava o modelo a escrever
    "15%" sobre participação: o verificador guarda só o valor, sem a unidade.
    COMENTARIOS saiu da autoridade numérica. Achado da revisão de 02/09/2026."""
    ch = composicao.Chamada(chamada_id="f1_0", ferramenta="observacoes_do_medico",
                 linhas=[{"DATA_VISITA": "14/08/2026", "VISITA_TIPO": "PRESENCIAL",
                          "COMENTARIOS": "RETORNAR EM 15 DIAS"}],
                 resultado_hash="h", parametros="{}", latencia_ms=1, sucesso=True)
    veredito = composicao.verificar("A participação está em 15%.", [ch])
    assert not veredito.aprovado


def test_data_da_observacao_continua_autorizada():
    """A data formatada sai do campo DATA_VISITA, que mantém autoridade: citar
    "na visita de 14/08/2026" é fiel ao retorno."""
    ch = composicao.Chamada(chamada_id="f1_0", ferramenta="observacoes_do_medico",
                 linhas=[{"DATA_VISITA": "14/08/2026", "VISITA_TIPO": "PRESENCIAL",
                          "COMENTARIOS": "PEDIU AMOSTRA"}],
                 resultado_hash="h", parametros="{}", latencia_ms=1, sucesso=True)
    veredito = composicao.verificar("Na visita de 14/08/2026 ele pediu amostra.", [ch])
    assert veredito.aprovado


def test_observacoes_estao_no_catalogo_do_modelo():
    from backend.app.agente.ferramentas import Ferramentas
    f = Ferramentas(CTX, ExecutorFalso())
    nomes = [d.nome for d in f.catalogo()]
    assert "observacoes_do_medico" in nomes
    assert len(nomes) == 7
    declarada = next(d for d in f.catalogo() if d.nome == "observacoes_do_medico")
    # setor nao e parametro: o modelo nao tem onde escrever setor de outro
    assert "setor" not in str(declarada.declaracao())


def test_percentual_exige_origem_com_percentual():
    """O golpe de unidade da segunda rodada de 02/09/2026: "15" numa data ou
    cinco linhas de retorno autorizavam "15%". Percentual na resposta agora
    exige ocorrência com % na origem."""
    ch = composicao.Chamada(
        chamada_id="f1_0", ferramenta="observacoes_do_medico",
        linhas=[{"DATA_VISITA": "15/08/2026", "VISITA_TIPO": "PRESENCIAL",
                 "COMENTARIOS": "PEDIU AMOSTRA"}],
        resultado_hash="h", parametros="{}", latencia_ms=1, sucesso=True)
    assert not composicao.verificar("A participação está em 15%.", [ch]).aprovado
    # a mesma data continua autorizada sem o sinal de percentual
    assert composicao.verificar("Na visita de 15/08/2026 ele pediu amostra.", [ch]).aprovado


def test_contagem_de_linhas_nao_autoriza_percentual():
    linhas = [{"NOME_MEDICO": f"M{i}"} for i in range(5)]
    ch = composicao.Chamada(chamada_id="f1_0", ferramenta="buscar_medico",
                            linhas=linhas, resultado_hash="h", parametros="{}",
                            latencia_ms=1, sucesso=True)
    assert composicao.verificar("Encontrei 5 profissionais.", [ch]).aprovado
    assert not composicao.verificar("A participação é 5%.", [ch]).aprovado


def test_percentual_formatado_continua_autorizado():
    """O caminho legítimo não muda: "3,6%" vindo de _formatar_percentual tem o
    % na origem e segue aprovado."""
    ch = composicao.Chamada(chamada_id="f1_0", ferramenta="participacao_no_agrupamento",
                            linhas=[{"PRODUTO": "FUSOR", "PARTICIPACAO": "3,6%"}],
                            resultado_hash="h", parametros="{}", latencia_ms=1, sucesso=True)
    assert composicao.verificar("FUSOR tem 3,6% de participação.", [ch]).aprovado


def test_espaco_antes_do_percentual_nao_contorna_a_unidade():
    """"15 %" com espaço driblava a detecção e a data voltava a autorizar.
    Achado da terceira rodada de 02/09/2026."""
    ch = composicao.Chamada(
        chamada_id="f1_0", ferramenta="observacoes_do_medico",
        linhas=[{"DATA_VISITA": "15/08/2026", "COMENTARIOS": "PEDIU AMOSTRA"}],
        resultado_hash="h", parametros="{}", latencia_ms=1, sucesso=True)
    assert not composicao.verificar("A participação está em 15 %.", [ch]).aprovado


def test_percentual_pequeno_tambem_exige_origem():
    """0, 1 e 2 são livres como quantidade, nunca como percentual: "1%" sem
    origem com unidade é reprovado, "1 produto" continua livre."""
    ch = composicao.Chamada(chamada_id="f1_0", ferramenta="buscar_medico",
                            linhas=[{"NOME_MEDICO": "M"}], resultado_hash="h",
                            parametros="{}", latencia_ms=1, sucesso=True)
    assert not composicao.verificar("A participação é 1%.", [ch]).aprovado
    assert composicao.verificar("Encontrei 1 profissional.", [ch]).aprovado
