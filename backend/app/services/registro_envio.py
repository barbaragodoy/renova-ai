"""
Serviço de registro de envio de recomendações do piloto (Sprint 5).

Função de serviço, NÃO endpoint FastAPI: ainda não existe job ou
integração de disparo real (Twilio/WhatsApp, templates Meta, e-mail) que
chame isso — ver docs/context/decisions-log.md (entrada 2026-08-10). Quando
essa integração existir, ela importa registrar_envio_recomendacoes()
diretamente, sem precisar de rota HTTP.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from backend.app.db.databricks_connection import get_engine
from backend.app.schemas.envio_recomendacoes import RegistrarEnvioRequest, RegistrarEnvioResponse


def _engine():
    return get_engine()


def registrar_envio_recomendacoes(request: RegistrarEnvioRequest) -> RegistrarEnvioResponse:
    """Registra um envio (ID_ENVIO novo) com uma linha por recomendação em
    request.recomendacoes, todas compartilhando ID_ENVIO/REP_MATRICULA/
    GRUPO_PILOTO/CANAL_ENVIO/DATA_HORA_ENVIO. ID_ENVIO e DATA_HORA_ENVIO são
    sempre gerados aqui — nunca aceitos como parâmetro externo (nem existem
    no schema RegistrarEnvioRequest)."""
    id_envio = str(uuid.uuid4())
    data_hora_envio = datetime.now(timezone.utc)

    with _engine().connect() as conn:
        for item in request.recomendacoes:
            conn.execute(
                text(
                    """
                    INSERT INTO tb_envios_recomendacoes_piloto (
                        id_envio, id_recomendacao, rep_matricula, grupo_piloto,
                        canal_envio, data_hora_envio, ciclo_recomendacao, tipo_recomendacao
                    ) VALUES (
                        :id_envio, :id_recomendacao, :rep_matricula, :grupo_piloto,
                        :canal_envio, :data_hora_envio, :ciclo_recomendacao, :tipo_recomendacao
                    )
                    """
                ),
                {
                    "id_envio": id_envio,
                    "id_recomendacao": item.id_recomendacao,
                    "rep_matricula": request.rep_matricula,
                    "grupo_piloto": request.grupo_piloto,
                    "canal_envio": request.canal_envio,
                    "data_hora_envio": data_hora_envio,
                    "ciclo_recomendacao": item.ciclo_recomendacao,
                    "tipo_recomendacao": item.tipo_recomendacao,
                },
            )
        conn.commit()

    return RegistrarEnvioResponse(
        success=True,
        id_envio=id_envio,
        quantidade_recomendacoes_registradas=len(request.recomendacoes),
        data_hora_envio=data_hora_envio.isoformat(),
    )
