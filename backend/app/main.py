import time
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app.routers import agente, chat, prescricoes, ranking, recomendacoes, gerencial, webhooks_twilio
from backend.app.auth.administrativo import (
    HEADER_VER_COMO,
    METODOS_SOMENTE_LEITURA,
    admin_router,
    registrar_alvo,
)
from backend.app.auth.context import auth_router
from backend.app.auth.foto import foto_router
from backend.app.auth.perfil import perfil_router
from backend.app.auth.sessao import sessao_router
from backend.app.auth.jwt_auth import capturar_cabecalhos_easy_auth
from backend.app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("renovai")

settings = get_settings()

app = FastAPI(
    title="RenovAI API",
    version="0.1.0",
    dependencies=[Depends(capturar_cabecalhos_easy_auth)],
)

# Na imagem única o portal e a API compartilham a origem, então não há
# requisição cross-origin em HMG. A entrada abaixo cobre o Vite em
# desenvolvimento, quando o front roda em porta separada.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    matricula = request.headers.get("X-Matricula", "-")
    response = await call_next(request)
    elapsed = round((time.time() - start) * 1000, 1)
    logger.info(
        "method=%s path=%s matricula=%s status=%s duration_ms=%s",
        request.method,
        request.url.path,
        matricula,
        response.status_code,
        elapsed,
    )
    return response


@app.middleware("http")
async def acesso_administrativo(request: Request, call_next):
    """Registra o setor pedido no header e barra escrita durante conferência.

    Aqui só se lê o header; a permissão é conferida em
    `auth/administrativo.aplicar_personificacao`, que é o único ponto com a
    identidade real do token em mãos. Um header enviado por quem não está na
    lista é ignorado e registrado lá.

    A recusa de escrita é feita antes da autenticação de propósito: vale para
    qualquer requisição que carregue o header, inclusive as que nem chegariam a
    autenticar. Uma sessão de conferência que gravasse um aceite ou uma
    desconsideração deixaria o registro no nome do propagandista, e a pergunta
    "quem decidiu isto" ficaria sem resposta.
    """
    setor_alvo = request.headers.get(HEADER_VER_COMO)
    registrar_alvo(setor_alvo)

    if setor_alvo and request.method.upper() not in METODOS_SOMENTE_LEITURA:
        logger.warning(
            "escrita bloqueada em sessao personificada | method=%s path=%s setor=%s",
            request.method,
            request.url.path,
            setor_alvo,
        )
        return JSONResponse(
            status_code=403,
            content={
                "detail": (
                    "Sessão de conferência é somente leitura. "
                    "Saia do modo de visualização para registrar uma ação."
                )
            },
        )

    return await call_next(request)


app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(perfil_router, prefix="/auth", tags=["auth"])
app.include_router(foto_router, prefix="/auth", tags=["auth"])
app.include_router(sessao_router, prefix="/auth", tags=["auth"])
app.include_router(prescricoes.router, prefix="/prescricoes", tags=["prescricoes"])
app.include_router(recomendacoes.router, prefix="/recomendacoes", tags=["recomendacoes"])
app.include_router(ranking.router, prefix="/ranking", tags=["ranking"])
app.include_router(gerencial.router, prefix="/gerencial", tags=["gerencial"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(agente.router, prefix="/agente", tags=["agente"])
app.include_router(admin_router, prefix="/admin", tags=["admin"])
app.include_router(webhooks_twilio.router, prefix="/webhooks/twilio", tags=["webhooks"])


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------- frontend --
# O React compilado entra na imagem pelo estágio Node do Dockerfile. Em
# desenvolvimento o diretório não existe: a API sobe normalmente e o Vite serve
# a interface na porta 3000.
_DIST = (Path(__file__).resolve().parents[2] / settings.frontend_dist).resolve()

# Os arquivos de `assets` têm o hash do conteúdo no nome, então uma versão
# nova sempre tem nome novo e a antiga pode ficar em cache para sempre. O
# `index.html` é o contrário: o nome nunca muda e ele é quem aponta para o
# pacote da vez. Sem `no-cache` nele, o navegador continua abrindo o pacote
# anterior depois de uma publicação, e foi o que aconteceu em 10/08/2026.
CACHE_IMUTAVEL = "public, max-age=31536000, immutable"
CACHE_SEMPRE_CONFERIR = "no-cache"

if _DIST.is_dir():
    class EstaticosComCache(StaticFiles):
        """`StaticFiles` que marca os arquivos com hash como imutáveis."""

        def file_response(self, *args, **kwargs):
            resposta = super().file_response(*args, **kwargs)
            resposta.headers["Cache-Control"] = CACHE_IMUTAVEL
            return resposta

    app.mount("/assets", EstaticosComCache(directory=_DIST / "assets"), name="assets")

    def _dentro_do_portal(caminho: str) -> Path | None:
        """Resolve o caminho pedido e confirma que ele fica dentro de _DIST.

        Sem esta checagem, um pedido cru como `/../acessos.csv` sairia do
        diretório do portal e entregaria arquivos da aplicação. Clientes HTTP
        normalizam o `..` antes de enviar, mas isso é comportamento do cliente
        e não vale como proteção: uma requisição montada na mão chega com o
        `..` intacto.
        """
        try:
            alvo = (_DIST / caminho).resolve()
        except (OSError, ValueError):
            return None
        if alvo != _DIST and _DIST not in alvo.parents:
            return None
        return alvo if alvo.is_file() else None

    @app.get("/{caminho:path}", include_in_schema=False)
    def servir_portal(caminho: str):
        """Entrega o portal. Rota desconhecida devolve o index.html, para que
        recarregar a página dentro do app não caia em 404."""
        arquivo = _dentro_do_portal(caminho) if caminho else None
        if arquivo is not None:
            # Arquivo de nome fixo, como o ícone e o avião da marca: o navegador
            # pode guardar, mas precisa perguntar antes de reusar.
            return FileResponse(arquivo, headers={"Cache-Control": CACHE_SEMPRE_CONFERIR})
        return FileResponse(
            _DIST / "index.html", headers={"Cache-Control": CACHE_SEMPRE_CONFERIR}
        )

else:
    logger.warning(
        "Frontend não encontrado em %s. A API responde, mas a raiz não serve o portal.",
        _DIST,
    )
