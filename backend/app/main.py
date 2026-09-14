import time
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.routers import agente, chat, prescricoes, ranking, recomendacoes, gerencial, webhooks_twilio
from backend.app.auth.context import auth_router
from backend.app.auth.foto import foto_router
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
app.include_router(foto_router, prefix="/auth", tags=["auth"])
app.include_router(sessao_router, prefix="/auth", tags=["auth"])
app.include_router(prescricoes.router, prefix="/prescricoes", tags=["prescricoes"])
app.include_router(recomendacoes.router, prefix="/recomendacoes", tags=["recomendacoes"])
app.include_router(ranking.router, prefix="/ranking", tags=["ranking"])
app.include_router(gerencial.router, prefix="/gerencial", tags=["gerencial"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(agente.router, prefix="/agente", tags=["agente"])
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
