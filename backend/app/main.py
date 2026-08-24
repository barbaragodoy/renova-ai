import time
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.routers import prescricoes, recomendacoes, gerencial
from backend.app.auth.context import auth_router
from backend.app.auth.perfil import perfil_router
from backend.app.auth.sessao import sessao_router
from backend.app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("renovai")

settings = get_settings()

app = FastAPI(title="RenovAI API", version="0.1.0")

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


app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(perfil_router, prefix="/auth", tags=["auth"])
app.include_router(sessao_router, prefix="/auth", tags=["auth"])
app.include_router(prescricoes.router, prefix="/prescricoes", tags=["prescricoes"])
app.include_router(recomendacoes.router, prefix="/recomendacoes", tags=["recomendacoes"])
app.include_router(gerencial.router, prefix="/gerencial", tags=["gerencial"])


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------- frontend --
# O React compilado entra na imagem pelo estágio Node do Dockerfile. Em
# desenvolvimento o diretório não existe: a API sobe normalmente e o Vite serve
# a interface na porta 3000.
_DIST = (Path(__file__).resolve().parents[2] / settings.frontend_dist).resolve()

if _DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

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
            return FileResponse(arquivo)
        return FileResponse(_DIST / "index.html")

else:
    logger.warning(
        "Frontend não encontrado em %s. A API responde, mas a raiz não serve o portal.",
        _DIST,
    )
