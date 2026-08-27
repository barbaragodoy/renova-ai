"""Foto de perfil do propagandista.

Os bytes da imagem ficam no volume do Unity Catalog
`/Volumes/acheinfo_dev/renovai/volume_renovai_dev`, e não em banco: volume é
o lugar próprio para binário, já tem governança e linhagem no mesmo catálogo
do resto, e evita inchar `tb_perfil_portal` com blob.

A tabela guarda só o caminho, em `FOTO_PATH`. A coluna já existia antes desta
rota, escrita por nenhum fluxo até aqui.

O arquivo é nomeado pela matrícula, não pelo nome enviado pelo cliente. Nome
de arquivo vindo de fora é vetor de path traversal, e a matrícula já é única
por pessoa. Trocar a foto sobrescreve a anterior: não há histórico de foto,
de propósito, porque ninguém pediu e guardar rosto antigo sem motivo é
retenção desnecessária de dado pessoal.
"""

from __future__ import annotations

import io
import logging
from typing import Optional

from fastapi import APIRouter, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import text

from backend.app.auth.jwt_auth import resolver_email_autenticado
from backend.app.config import get_settings
from backend.app.db.databricks_connection import get_engine

logger = logging.getLogger("renovai")

foto_router = APIRouter()

# Diretório da foto dentro do volume. Subpasta própria para não misturar com
# a KB do agente, que mora no mesmo volume.
_PASTA = "fotos-perfil"

# Tipos aceitos e extensão de cada um. A extensão sai daqui, nunca do nome do
# arquivo enviado, para o caminho gravado ser sempre previsível.
_TIPOS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

# 2 MB. Foto de perfil exibida num círculo de 96px não precisa de mais, e o
# limite protege o volume e a memória do container, já que o upload é lido
# inteiro antes de subir.
_TAMANHO_MAXIMO = 2 * 1024 * 1024

_NAO_ENCONTRADO = "Perfil não encontrado para este e-mail."


def _cliente():
    """WorkspaceClient com as mesmas credenciais que a engine já usa.

    Importado aqui dentro, e não no topo, porque o modo local (Postgres) não
    tem essas credenciais e não deve exigir o SDK só para carregar o módulo.
    """
    from databricks.sdk import WorkspaceClient

    s = get_settings()
    return WorkspaceClient(
        host=f"https://{s.databricks_server_hostname}",
        client_id=s.databricks_client_id,
        client_secret=s.databricks_client_secret,
    )


def _raiz_do_volume() -> str:
    s = get_settings()
    return f"/Volumes/{s.databricks_catalog}/{s.databricks_schema}/volume_renovai_dev"


def _matricula(email: str) -> str:
    with get_engine().connect() as conn:
        linha = (
            conn.execute(
                text(
                    "SELECT rep_matricula FROM tb_propagandistas "
                    "WHERE LOWER(rep_email) = LOWER(:email) LIMIT 1"
                ),
                {"email": email},
            )
            .mappings()
            .fetchone()
        )
    if linha is None:
        raise HTTPException(status_code=404, detail=_NAO_ENCONTRADO)
    return linha["rep_matricula"]


def _gravar_caminho(email: str, matricula: str, caminho: Optional[str]) -> None:
    """Grava só FOTO_PATH.

    O MERGE lista as colunas uma a uma porque a mesma linha guarda o nome
    editado e o limite do painel, escritos por outros fluxos. Um
    `UPDATE SET *` apagaria os dois.
    """
    with get_engine().connect() as conn:
        conn.execute(
            text("""
                MERGE INTO tb_perfil_portal AS destino
                USING (SELECT LOWER(:email) AS rep_email) AS origem
                   ON destino.rep_email = origem.rep_email
                WHEN MATCHED THEN UPDATE SET
                    rep_matricula = :matricula,
                    foto_path = :caminho,
                    dt_atualizacao = current_timestamp
                WHEN NOT MATCHED THEN INSERT
                    (rep_email, rep_matricula, nome_exibicao,
                     nome_origem_na_edicao, foto_path, dt_atualizacao)
                    VALUES (LOWER(:email), :matricula, NULL,
                            NULL, :caminho, current_timestamp)
            """),
            {"email": email, "matricula": matricula, "caminho": caminho},
        )
        conn.commit()


@foto_router.put("/perfil/foto")
async def enviar_foto(
    arquivo: UploadFile = File(...),
    email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Envia ou troca a foto de perfil.

    Devolve o caminho gravado. A tela não usa esse caminho para montar URL:
    a leitura é sempre por `GET /auth/perfil/foto`, que resolve a partir da
    sessão. O caminho volta só para a interface saber que existe foto.
    """
    autenticado = resolver_email_autenticado(authorization, email)

    extensao = _TIPOS.get((arquivo.content_type or "").lower())
    if extensao is None:
        raise HTTPException(
            status_code=415,
            detail="Formato não aceito. Envie JPEG, PNG ou WebP.",
        )

    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")
    if len(conteudo) > _TAMANHO_MAXIMO:
        raise HTTPException(
            status_code=413,
            detail="Imagem acima de 2 MB. Envie uma menor.",
        )

    matricula = _matricula(autenticado)
    caminho = f"{_raiz_do_volume()}/{_PASTA}/{matricula}.{extensao}"

    try:
        # `files.upload` espera objeto de arquivo, não bytes: internamente
        # chama .seekable() para decidir entre envio direto e multipart.
        # Passar bytes crus levanta AttributeError, confirmado em produção
        # em 20/08/2026 com o SDK 0.120.0.
        _cliente().files.upload(caminho, io.BytesIO(conteudo), overwrite=True)
    except Exception:
        # O detalhe do erro do SDK pode conter caminho e identificador do
        # principal. Fica no log do servidor, não na resposta.
        logger.exception("Falha ao gravar a foto no volume.")
        raise HTTPException(
            status_code=502, detail="Não foi possível guardar a foto agora."
        )

    _gravar_caminho(autenticado, matricula, caminho)
    return {"foto_path": caminho}


@foto_router.get("/perfil/foto")
def obter_foto(
    email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Devolve os bytes da foto da própria pessoa.

    O caminho vem da tabela, nunca da requisição: assim ninguém consegue
    pedir um arquivo arbitrário do volume passando um caminho na URL.
    """
    autenticado = resolver_email_autenticado(authorization, email)

    with get_engine().connect() as conn:
        linha = (
            conn.execute(
                text(
                    "SELECT foto_path FROM tb_perfil_portal "
                    "WHERE LOWER(rep_email) = LOWER(:email) LIMIT 1"
                ),
                {"email": autenticado},
            )
            .mappings()
            .fetchone()
        )

    caminho = linha["foto_path"] if linha else None
    if not caminho:
        raise HTTPException(status_code=404, detail="Sem foto de perfil.")

    try:
        baixado = _cliente().files.download(caminho)
        conteudo = baixado.contents.read()
    except Exception:
        logger.exception("Falha ao ler a foto do volume.")
        raise HTTPException(
            status_code=502, detail="Não foi possível carregar a foto agora."
        )

    extensao = caminho.rsplit(".", 1)[-1].lower()
    tipo = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(
        extensao, "application/octet-stream"
    )
    # Sem cache no navegador: trocar a foto precisa aparecer na hora.
    return Response(
        content=conteudo,
        media_type=tipo,
        headers={"Cache-Control": "no-store"},
    )


@foto_router.delete("/perfil/foto", status_code=204)
def remover_foto(
    email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Remove a foto.

    Limpa `FOTO_PATH` e apaga o arquivo. Se o arquivo já não existir, a
    limpeza da coluna vale mesmo assim: o estado final desejado é não ter
    foto, e falhar aqui deixaria a pessoa presa a uma foto que ela pediu para
    tirar.
    """
    autenticado = resolver_email_autenticado(authorization, email)
    matricula = _matricula(autenticado)

    with get_engine().connect() as conn:
        linha = (
            conn.execute(
                text(
                    "SELECT foto_path FROM tb_perfil_portal "
                    "WHERE LOWER(rep_email) = LOWER(:email) LIMIT 1"
                ),
                {"email": autenticado},
            )
            .mappings()
            .fetchone()
        )

    caminho = linha["foto_path"] if linha else None
    if caminho:
        try:
            _cliente().files.delete(caminho)
        except Exception:
            logger.warning("Foto não removida do volume: %s", caminho)

    _gravar_caminho(autenticado, matricula, None)
    return Response(status_code=204)
