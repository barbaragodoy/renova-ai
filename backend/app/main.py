import time
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.app.routers import prescricoes, recomendacoes, gerencial
from backend.app.auth.context import auth_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("renovai")

app = FastAPI(title="RenovAI API", version="0.1.0")

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
app.include_router(prescricoes.router, prefix="/prescricoes", tags=["prescricoes"])
app.include_router(recomendacoes.router, prefix="/recomendacoes", tags=["recomendacoes"])
app.include_router(gerencial.router, prefix="/gerencial", tags=["gerencial"])


@app.get("/health")
def health():
    return {"status": "ok"}
