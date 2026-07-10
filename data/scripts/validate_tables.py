"""
Validação de qualidade dos dados — RenovAI local
Verifica grão, match entre tabelas e cenários obrigatórios.
"""
import os
import sys
from datetime import date, timedelta
from sqlalchemy import create_engine, text

DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://renovai:renovai@localhost:5432/renovai"
)
CICLO = "202507"
CORTE_RANKING = 100      # equivalente ao corte <=400 na escala real simulada
SEM_VISITA_MESES = 5
DATA_CORTE_VISITA = date.today() - timedelta(days=SEM_VISITA_MESES * 30)

engine = create_engine(DB_URL)
erros = []
alertas = []


def check(descricao: str, query: str, esperado_min: int = 1) -> int:
    with engine.connect() as conn:
        resultado = conn.execute(text(query)).scalar()
    ok = resultado >= esperado_min
    status = "OK" if ok else "FALHOU"
    print(f"  [{status}] {descricao}: {resultado}")
    if not ok:
        erros.append(f"{descricao} → {resultado} (esperado >= {esperado_min})")
    return resultado


def alerta(descricao: str, query: str, limite_max: int = 0):
    with engine.connect() as conn:
        resultado = conn.execute(text(query)).scalar()
    if resultado > limite_max:
        msg = f"ALERTA: {descricao} → {resultado} duplicatas"
        print(f"  [WARN] {msg}")
        alertas.append(msg)
    else:
        print(f"  [OK]   {descricao}: sem duplicatas")
    return resultado


print("\n" + "=" * 60)
print("  RenovAI — Relatório de Qualidade dos Dados")
print("  Ciclo:", CICLO)
print("=" * 60)

# -------------------------------------------------------
print("\n[1] GRÃO — Verificação de duplicidade nas PKs")
# -------------------------------------------------------
alerta(
    "tb_propagandistas: duplicidade em rep_matricula",
    "SELECT COUNT(*) FROM (SELECT rep_matricula FROM tb_propagandistas GROUP BY 1 HAVING COUNT(*) > 1) t"
)
alerta(
    "tb_ranking_medicos: duplicidade na PK",
    "SELECT COUNT(*) FROM (SELECT setor, cod_linha, ufcrm, ciclo_referencia FROM tb_ranking_medicos GROUP BY 1,2,3,4 HAVING COUNT(*) > 1) t"
)
alerta(
    "tb_painel_medico: duplicidade na PK",
    "SELECT COUNT(*) FROM (SELECT setor, ufcrm, ciclo_referencia FROM tb_painel_medico GROUP BY 1,2,3 HAVING COUNT(*) > 1) t"
)
alerta(
    "tb_visitacao_medica: duplicidade na PK",
    "SELECT COUNT(*) FROM (SELECT setor, ufcrm, data_visita FROM tb_visitacao_medica GROUP BY 1,2,3 HAVING COUNT(*) > 1) t"
)

# -------------------------------------------------------
print("\n[2] CONTAGENS — Volumes esperados")
# -------------------------------------------------------
check("Propagandistas cadastrados",
      "SELECT COUNT(*) FROM tb_propagandistas", 10)
check("Propagandistas ativos",
      "SELECT COUNT(*) FROM tb_propagandistas WHERE ativo = TRUE", 9)
check("GDs cadastrados",
      "SELECT COUNT(DISTINCT gd_matricula) FROM tb_hierarquia_gd", 3)
check(f"Médicos no ranking (ciclo {CICLO})",
      f"SELECT COUNT(*) FROM tb_ranking_medicos WHERE ciclo_referencia = '{CICLO}'", 900)
check(f"Médicos no painel (ciclo {CICLO})",
      f"SELECT COUNT(*) FROM tb_painel_medico WHERE ciclo_referencia = '{CICLO}'", 480)
check("Prescrições registradas",
      "SELECT COUNT(*) FROM tb_prescricoes_geral", 100)
check("Registros de visitação",
      "SELECT COUNT(*) FROM tb_visitacao_medica", 1)

# -------------------------------------------------------
print("\n[3] MATCH — Ranking × Painel (ufcrm compartilhados)")
# -------------------------------------------------------
with engine.connect() as conn:
    total_painel = conn.execute(text(
        f"SELECT COUNT(DISTINCT ufcrm) FROM tb_painel_medico WHERE ciclo_referencia = '{CICLO}'"
    )).scalar()
    match = conn.execute(text(f"""
        SELECT COUNT(DISTINCT p.ufcrm)
        FROM tb_painel_medico p
        JOIN tb_ranking_medicos r USING (ufcrm)
        WHERE p.ciclo_referencia = '{CICLO}' AND r.ciclo_referencia = '{CICLO}'
    """)).scalar()

taxa = round(match / total_painel * 100, 1) if total_painel else 0
print(f"  [INFO] ufcrm no painel: {total_painel} | com match no ranking: {match} | taxa: {taxa}%")
if taxa < 80:
    alertas.append(f"Taxa de match ranking×painel baixa: {taxa}%")

# -------------------------------------------------------
print("\n[4] CENÁRIOS OBRIGATÓRIOS")
# -------------------------------------------------------
# C1: médico acima do corte fora do painel
check(
    "C1 — Médico dentro do corte (pos<=100) fora do painel",
    f"""
    SELECT COUNT(*) FROM tb_ranking_medicos r
    LEFT JOIN tb_painel_medico p USING (setor, ufcrm)
    WHERE r.posicao_ranking <= {CORTE_RANKING}
      AND r.ciclo_referencia = '{CICLO}'
      AND p.ufcrm IS NULL
    """
)

# C2: médico acima do corte no painel
check(
    "C2 — Médico dentro do corte (pos<=100) no painel",
    f"""
    SELECT COUNT(*) FROM tb_ranking_medicos r
    JOIN tb_painel_medico p USING (setor, ufcrm)
    WHERE r.posicao_ranking <= {CORTE_RANKING}
      AND r.ciclo_referencia = '{CICLO}'
      AND p.ciclo_referencia = '{CICLO}'
    """
)

# C3: médico fora do corte no painel
check(
    "C3 — Médico fora do corte (pos>100) no painel",
    f"""
    SELECT COUNT(*) FROM tb_ranking_medicos r
    JOIN tb_painel_medico p USING (setor, ufcrm)
    WHERE r.posicao_ranking > {CORTE_RANKING}
      AND r.ciclo_referencia = '{CICLO}'
      AND p.ciclo_referencia = '{CICLO}'
    """
)

# C4: médico sem visita efetiva há > 5 meses
check(
    f"C4 — Médico sem visita efetiva há > {SEM_VISITA_MESES} meses",
    f"""
    SELECT COUNT(DISTINCT p.ufcrm)
    FROM tb_painel_medico p
    WHERE p.ciclo_referencia = '{CICLO}'
      AND p.ativo = TRUE
      AND NOT EXISTS (
        SELECT 1 FROM tb_visitacao_medica v
        WHERE v.ufcrm = p.ufcrm
          AND v.setor = p.setor
          AND v.visita_efetiva = TRUE
          AND v.data_visita >= '{DATA_CORTE_VISITA}'
      )
    """
)

# -------------------------------------------------------
print("\n" + "=" * 60)
print("  RESULTADO FINAL")
print("=" * 60)
if alertas:
    print("\nAlertas:")
    for a in alertas:
        print(f"  ⚠  {a}")
if erros:
    print("\nErros:")
    for e in erros:
        print(f"  ✗  {e}")
    print(f"\n  {len(erros)} check(s) falharam.")
    sys.exit(1)
else:
    print("\n  Todos os checks passaram.")
    if alertas:
        print(f"  {len(alertas)} alerta(s) registrado(s) — revisar acima.")
