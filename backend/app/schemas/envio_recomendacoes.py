"""
Schemas Pydantic para o registro de envio de recomendações do piloto
(Sprint 5). Ainda sem endpoint FastAPI — ver backend/app/services/registro_envio.py.
"""
from typing import List, Literal

from pydantic import BaseModel, Field, model_validator


class EnvioRecomendacaoItem(BaseModel):
    id_recomendacao: str
    tipo_recomendacao: str
    ciclo_recomendacao: str


class RegistrarEnvioRequest(BaseModel):
    # rep_matricula vem de quem chama o serviço (job/integração de disparo),
    # não de input direto de usuário final — diferente de resolver_contexto()
    # nos endpoints REST. data_hora_envio e id_envio não fazem parte do
    # contrato: sempre gerados pelo backend em registrar_envio_recomendacoes().
    rep_matricula: str
    grupo_piloto: Literal["WHATSAPP", "EMAIL", "CONTROLE"]
    canal_envio: Literal["WHATSAPP", "EMAIL", "NENHUM"]
    recomendacoes: List[EnvioRecomendacaoItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _grupo_canal_consistentes(self) -> "RegistrarEnvioRequest":
        if self.grupo_piloto == "CONTROLE" and self.canal_envio != "NENHUM":
            raise ValueError("grupo_piloto 'CONTROLE' exige canal_envio 'NENHUM'.")
        if self.grupo_piloto in ("WHATSAPP", "EMAIL") and self.canal_envio != self.grupo_piloto:
            raise ValueError(
                f"grupo_piloto '{self.grupo_piloto}' exige canal_envio '{self.grupo_piloto}' "
                f"(recebido: '{self.canal_envio}')."
            )
        return self


class RegistrarEnvioResponse(BaseModel):
    success: bool
    id_envio: str
    quantidade_recomendacoes_registradas: int
    data_hora_envio: str
