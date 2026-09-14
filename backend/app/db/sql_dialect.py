"""Pequenas diferenças de sintaxe entre PostgreSQL e Spark SQL."""

from backend.app.config import get_settings


def formatar_data_sql(coluna: str) -> str:
    """Formata uma data como dd/MM/yyyy na fonte ativa.

    ``coluna`` é sempre um identificador fixo definido pelo backend. Valores
    vindos da requisição continuam sendo enviados como parâmetros SQL.
    """
    if get_settings().data_source.lower() == "databricks":
        return f"DATE_FORMAT({coluna}, 'dd/MM/yyyy')"
    return f"TO_CHAR({coluna}, 'DD/MM/YYYY')"
