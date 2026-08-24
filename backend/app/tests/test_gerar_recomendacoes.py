"""
Testes de backend/app/jobs/gerar_recomendacoes.py (Sprint 6).

Diferente de test_cenarios_completos.py::test_e2e_05_novo_ciclo_recorrencia
(mockado, cobre só o caminho de recorrência), este arquivo roda a query real
contra o Postgres local com um cenário isolado (setor/ciclo/matrícula
dedicados, nunca usados em nenhum outro script de seed), para validar a
lógica de CASE que decide os 4 valores de MOTIVO_RECOMENDACAO e o texto de
justificativa — SQL real, não substring matching de mock.
"""
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, text

from backend.app.config import get_settings
from backend.app.jobs.gerar_recomendacoes import gerar_recomendacoes

pytestmark = [pytest.mark.requer_banco, pytest.mark.usefixtures("forcar_data_source_local")]

_SETOR = "SPRINT6_TESTE"
_COD_LINHA = "TESTE"
_CICLO = "209912"
_REP_MAT = "REPSPRINT6"
_REP_EMAIL = "sprint6.teste@ache.com.br"
_LIMITE = 5  # limite de painel baixo, de propósito, para o cenário caber em poucas linhas

# UFCRMs do cenário — nomeados pelo papel que exercem no teste.
_ENTRADA = "T0001"          # fora do painel, ranking dentro do limite → ENTRADA_PAINEL
_FILLER1, _FILLER2, _FILLER3 = "T0002", "T0003", "T0004"  # no painel, ranking bom, visita recente → não geram revisão
_REV_RANKING = "T0005"      # no painel, ranking acima do limite, visita recente
_REV_VISITA = "T0006"       # no painel, ranking dentro do limite, sem visita
_REV_AMBOS = "T0007"        # no painel, ranking acima do limite, sem visita

_HOJE = date.today()
_DATA_INCLUSAO_ANTIGA = date(2020, 1, 1)  # >> _CICLOS_PAINEL_MIN, satisfaz a guarda de "ciclos no painel"
_VISITA_RECENTE = _HOJE - timedelta(days=10)
_VISITA_ANTIGA = _HOJE - timedelta(days=200)  # > sem_visita_meses (3) * 30


def _engine():
    return create_engine(get_settings().database_url)


@pytest.fixture
def cenario_sprint6():
    """Cria o cenário isolado, roda o teste, e limpa tudo — mesmo padrão
    determinístico de data/scripts/10_popular_cenarios_desconsiderar.sql,
    mas via fixture (não script versionado) porque este cenário existe só
    para este teste, não para reaproveitamento manual/curl."""
    eng = _engine()
    with eng.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO tb_propagandistas (rep_matricula, rep_email, setor, cod_linha, rep_nome, ativo)
                VALUES (:mat, :email, :setor, :linha, 'Sprint6 Teste', TRUE)
                ON CONFLICT (rep_matricula) DO NOTHING
            """),
            {"mat": _REP_MAT, "email": _REP_EMAIL, "setor": _SETOR, "linha": _COD_LINHA},
        )
        conn.execute(
            text("""
                INSERT INTO tb_perfil_portal (rep_email, rep_matricula, limite_painel)
                VALUES (:email, :mat, :limite)
                ON CONFLICT (rep_email) DO UPDATE SET limite_painel = :limite
            """),
            {"email": _REP_EMAIL, "mat": _REP_MAT, "limite": _LIMITE},
        )

        rankings = [
            (_ENTRADA, "Dr. Entrada", 3),
            (_FILLER1, "Dr. Filler Um", 1),
            (_FILLER2, "Dr. Filler Dois", 2),
            (_FILLER3, "Dr. Filler Tres", 4),
            (_REV_RANKING, "Dr. Revisao Ranking", 10),
            (_REV_VISITA, "Dr. Revisao Visita", 5),
            (_REV_AMBOS, "Dr. Revisao Ambos", 11),
        ]
        for ufcrm, nome, pos in rankings:
            conn.execute(
                text("""
                    INSERT INTO tb_ranking_medicos (setor, cod_linha, ufcrm, nome_medico, soma_pontuacao, posicao_ranking, ciclo_referencia)
                    VALUES (:setor, :linha, :ufcrm, :nome, :pontos, :pos, :ciclo)
                    ON CONFLICT DO NOTHING
                """),
                {"setor": _SETOR, "linha": _COD_LINHA, "ufcrm": ufcrm, "nome": nome,
                 "pontos": 1000 - pos, "pos": pos, "ciclo": _CICLO},
            )

        painel = [_FILLER1, _FILLER2, _FILLER3, _REV_RANKING, _REV_VISITA, _REV_AMBOS]
        for ufcrm in painel:
            nome = dict((r[0], r[1]) for r in rankings)[ufcrm]
            conn.execute(
                text("""
                    INSERT INTO tb_painel_medico (setor, ufcrm, nome_medico, data_inclusao, ativo, ciclo_referencia)
                    VALUES (:setor, :ufcrm, :nome, :data_inclusao, TRUE, :ciclo)
                    ON CONFLICT DO NOTHING
                """),
                {"setor": _SETOR, "ufcrm": ufcrm, "nome": nome,
                 "data_inclusao": _DATA_INCLUSAO_ANTIGA, "ciclo": _CICLO},
            )

        visitas = [
            (_FILLER1, _VISITA_RECENTE), (_FILLER2, _VISITA_RECENTE), (_FILLER3, _VISITA_RECENTE),
            (_REV_RANKING, _VISITA_RECENTE),
            (_REV_VISITA, _VISITA_ANTIGA),
            (_REV_AMBOS, _VISITA_ANTIGA),
        ]
        for ufcrm, data_visita in visitas:
            conn.execute(
                text("""
                    INSERT INTO tb_visitacao_medica (setor, ufcrm, data_visita, visita_efetiva, ciclo_referencia)
                    VALUES (:setor, :ufcrm, :data_visita, TRUE, :ciclo)
                    ON CONFLICT DO NOTHING
                """),
                {"setor": _SETOR, "ufcrm": ufcrm, "data_visita": data_visita, "ciclo": _CICLO},
            )
        conn.commit()

    try:
        yield
    finally:
        with eng.connect() as conn:
            conn.execute(text("DELETE FROM tb_recomendacoes_painel WHERE rep_matricula = :mat"), {"mat": _REP_MAT})
            conn.execute(text("DELETE FROM tb_visitacao_medica WHERE setor = :setor"), {"setor": _SETOR})
            conn.execute(text("DELETE FROM tb_painel_medico WHERE setor = :setor"), {"setor": _SETOR})
            conn.execute(text("DELETE FROM tb_ranking_medicos WHERE setor = :setor"), {"setor": _SETOR})
            conn.execute(text("DELETE FROM tb_perfil_portal WHERE rep_matricula = :mat"), {"mat": _REP_MAT})
            conn.execute(text("DELETE FROM tb_propagandistas WHERE rep_matricula = :mat"), {"mat": _REP_MAT})
            conn.commit()


def _recomendacoes_geradas():
    eng = _engine()
    with eng.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT ufcrm, tipo_recomendacao, motivo_revisao, justificativa_texto
                FROM tb_recomendacoes_painel
                WHERE rep_matricula = :mat AND ciclo_referencia = :ciclo
            """),
            {"mat": _REP_MAT, "ciclo": _CICLO},
        ).mappings().fetchall()
    return {r["ufcrm"]: r for r in rows}


def test_gera_entrada_painel_dentro_do_limite(cenario_sprint6):
    gerar_recomendacoes(ciclo=_CICLO, dry_run=False)
    geradas = _recomendacoes_geradas()
    assert geradas[_ENTRADA]["tipo_recomendacao"] == "ENTRADA_PAINEL"
    assert geradas[_ENTRADA]["motivo_revisao"] is None


def test_fillers_nao_geram_revisao(cenario_sprint6):
    """Painel > limite (guarda ativa), mas ranking bom + visita recente —
    não deve gerar nenhuma recomendação de revisão para os fillers."""
    gerar_recomendacoes(ciclo=_CICLO, dry_run=False)
    geradas = _recomendacoes_geradas()
    for ufcrm in (_FILLER1, _FILLER2, _FILLER3):
        assert ufcrm not in geradas


def test_motivo_revisao_ranking_acima_limite(cenario_sprint6):
    gerar_recomendacoes(ciclo=_CICLO, dry_run=False)
    geradas = _recomendacoes_geradas()
    assert geradas[_REV_RANKING]["motivo_revisao"] == "REVISAO_RANKING_SETOR_ACIMA_LIMITE"


def test_motivo_revisao_sem_visita_3_meses(cenario_sprint6):
    gerar_recomendacoes(ciclo=_CICLO, dry_run=False)
    geradas = _recomendacoes_geradas()
    assert geradas[_REV_VISITA]["motivo_revisao"] == "REVISAO_SEM_VISITA_3_MESES"


def test_motivo_revisao_ranking_e_sem_visita_combinados(cenario_sprint6):
    gerar_recomendacoes(ciclo=_CICLO, dry_run=False)
    geradas = _recomendacoes_geradas()
    assert geradas[_REV_AMBOS]["motivo_revisao"] == "REVISAO_RANKING_SETOR_ACIMA_LIMITE_E_SEM_VISITA_3_MESES"


def test_quatro_motivos_sao_exatamente_os_confirmados(cenario_sprint6):
    """Nenhuma variação de nome: exatamente os 4 valores confirmados por
    query real contra o Databricks (ver prompt da task/decisions-log.md),
    sem '_400' nem '_5_MESES' em lugar nenhum."""
    gerar_recomendacoes(ciclo=_CICLO, dry_run=False)
    geradas = _recomendacoes_geradas()
    motivos = {r["motivo_revisao"] for r in geradas.values() if r["motivo_revisao"] is not None}
    assert motivos == {
        "REVISAO_RANKING_SETOR_ACIMA_LIMITE",
        "REVISAO_SEM_VISITA_3_MESES",
        "REVISAO_RANKING_SETOR_ACIMA_LIMITE_E_SEM_VISITA_3_MESES",
    }
    for r in geradas.values():
        for campo in ("motivo_revisao", "justificativa_texto"):
            valor = r[campo] or ""
            assert "400" not in valor
            assert "5 meses" not in valor
            assert "5_MESES" not in valor


def test_justificativa_sem_visita_usa_valor_vigente_3_meses(cenario_sprint6):
    """O texto interpola settings.sem_visita_meses (3), nunca um número
    hardcoded diferente do valor vigente."""
    gerar_recomendacoes(ciclo=_CICLO, dry_run=False)
    geradas = _recomendacoes_geradas()
    texto = geradas[_REV_VISITA]["justificativa_texto"]
    assert "3 meses" in texto
    assert "abandono" not in texto.lower()
    assert "negligência" not in texto.lower()
    assert "não visitado" not in texto.lower()


def test_painel_exatamente_no_limite_nao_gera_revisao():
    """Comparação estrita > confirmada pelo Hugo: painel EXATAMENTE no
    limite não deve disparar revisão, mesmo com médico de ranking ruim ou
    sem visita dentro dele. Cenário próprio (limite == tamanho do painel),
    isolado do resto para não colidir com cenario_sprint6."""
    setor = "SPRINT6_LIMITE_EXATO"
    ciclo = "209913"
    mat = "REPSPRINT6B"
    email = "sprint6b.teste@ache.com.br"
    limite = 2
    ufcrm_ruim = "T0100"

    eng = _engine()
    with eng.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO tb_propagandistas (rep_matricula, rep_email, setor, cod_linha, rep_nome, ativo)
                VALUES (:mat, :email, :setor, 'TESTE', 'Sprint6 Teste B', TRUE)
                ON CONFLICT (rep_matricula) DO NOTHING
            """),
            {"mat": mat, "email": email, "setor": setor},
        )
        conn.execute(
            text("""
                INSERT INTO tb_perfil_portal (rep_email, rep_matricula, limite_painel)
                VALUES (:email, :mat, :limite)
                ON CONFLICT (rep_email) DO UPDATE SET limite_painel = :limite
            """),
            {"email": email, "mat": mat, "limite": limite},
        )
        # Painel com exatamente `limite` médicos — um deles com ranking
        # ruim e sem visita, que só vira revisão se a guarda de painel
        # usasse >= em vez de > (bug que este teste existe para pegar).
        for i, ufcrm in enumerate([ufcrm_ruim, "T0101"], start=1):
            conn.execute(
                text("""
                    INSERT INTO tb_ranking_medicos (setor, cod_linha, ufcrm, nome_medico, soma_pontuacao, posicao_ranking, ciclo_referencia)
                    VALUES (:setor, 'TESTE', :ufcrm, :nome, 100, :pos, :ciclo)
                    ON CONFLICT DO NOTHING
                """),
                {"setor": setor, "ufcrm": ufcrm, "nome": f"Dr. Limite {i}", "pos": 99, "ciclo": ciclo},
            )
            conn.execute(
                text("""
                    INSERT INTO tb_painel_medico (setor, ufcrm, nome_medico, data_inclusao, ativo, ciclo_referencia)
                    VALUES (:setor, :ufcrm, :nome, :data_inclusao, TRUE, :ciclo)
                    ON CONFLICT DO NOTHING
                """),
                {"setor": setor, "ufcrm": ufcrm, "nome": f"Dr. Limite {i}",
                 "data_inclusao": _DATA_INCLUSAO_ANTIGA, "ciclo": ciclo},
            )
        conn.commit()

    try:
        gerar_recomendacoes(ciclo=ciclo, dry_run=False)
        with eng.connect() as conn:
            rows = conn.execute(
                text("SELECT ufcrm FROM tb_recomendacoes_painel WHERE rep_matricula = :mat AND ciclo_referencia = :ciclo"),
                {"mat": mat, "ciclo": ciclo},
            ).mappings().fetchall()
        assert rows == []
    finally:
        with eng.connect() as conn:
            conn.execute(text("DELETE FROM tb_recomendacoes_painel WHERE rep_matricula = :mat"), {"mat": mat})
            conn.execute(text("DELETE FROM tb_painel_medico WHERE setor = :setor"), {"setor": setor})
            conn.execute(text("DELETE FROM tb_ranking_medicos WHERE setor = :setor"), {"setor": setor})
            conn.execute(text("DELETE FROM tb_perfil_portal WHERE rep_matricula = :mat"), {"mat": mat})
            conn.execute(text("DELETE FROM tb_propagandistas WHERE rep_matricula = :mat"), {"mat": mat})
            conn.commit()
