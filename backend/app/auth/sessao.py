"""Autenticação de sessão do Portal Ped.AI.

Dois modos, selecionados por `AUTH_MODE`:

- `senha`: o propagandista entra com o e-mail corporativo e uma senha gerada
  pelo time. O hash vem de `acessos.csv`, dentro da imagem; setor e nome
  continuam vindo de `tb_propagandistas`, que é a fonte única desses dados.
- `entra_id`: a autenticação passa a ser do Microsoft Entra ID e este módulo
  para de emitir token. O App Service Easy Auth autentica na plataforma e
  `auth/jwt_auth.py` lê os headers `X-MS-CLIENT-PRINCIPAL-*`;
  `POST /auth/login` responde 404.

Ter o hash no arquivo e o cadastro na tabela mantém uma consequência útil:
quem sai de `tb_propagandistas` perde o acesso na hora, sem precisar mexer no
arquivo de senhas.

O token carrega e-mail, setor e nome. Matrícula não entra: os endpoints
resolvem o que precisam a partir do e-mail autenticado, e um dado a menos no
token é um dado a menos exposto se ele vazar.

O e-mail é comparado com LOWER() nos dois lados, pelo mesmo motivo tratado em
`auth/context.py`: parte dos registros tem o e-mail gravado em maiúsculas.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.app.auth.status_acesso import exigir_acesso_liberado
from backend.app.auth.credenciais import (
    RepositorioDeAcessos,
    gerar_hash,
    gerar_senha,
    verificar_senha,
)
from backend.app.auth.perfil import registrar_acesso
from backend.app.config import Settings, get_settings
from backend.app.db.databricks_connection import get_engine

logger = logging.getLogger("renovai")

sessao_router = APIRouter()

EMISSOR = "renovai-portal"
AUDIENCIA = "renovai-portal"

# Hash de uma senha aleatória, gerado uma vez na subida. Serve para gastar o
# mesmo tempo de CPU quando o e-mail não existe, de modo que a duração da
# resposta não revele quais e-mails estão cadastrados.
HASH_DESCARTAVEL = gerar_hash(gerar_senha())

_RAIZ = Path(__file__).resolve().parents[3]
acessos = RepositorioDeAcessos(_RAIZ / "acessos.csv")

SQL_CADASTRO = """
SELECT setor AS setor, rep_nome AS nome
FROM tb_propagandistas
WHERE LOWER(rep_email) = LOWER(:email)
"""


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    senha: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expira_em: int
    nome: str | None = None
    setor: str


@dataclass(frozen=True)
class Identidade:
    email: str
    setor: str
    nome: str | None


class ControleDeTentativas:
    """Atraso progressivo por e-mail, para encarecer tentativa em massa.

    O controle é por processo, não substitui um limitador na borda, mas já
    torna inviável varrer senhas a partir de um único cliente. A janela zera
    sozinha depois de cinco minutos sem tentativa.
    """

    LIMITE_ANTES_DO_ATRASO = 3
    ATRASO_MAXIMO_SEGUNDOS = 8.0
    JANELA_SEGUNDOS = 300

    def __init__(self) -> None:
        self._tentativas: dict[str, tuple[int, float]] = {}
        self._trava = Lock()

    def atraso_atual(self, chave: str) -> float:
        with self._trava:
            registro = self._tentativas.get(chave)
            if not registro:
                return 0.0
            falhas, ultima = registro
            if time.monotonic() - ultima > self.JANELA_SEGUNDOS:
                self._tentativas.pop(chave, None)
                return 0.0
            if falhas <= self.LIMITE_ANTES_DO_ATRASO:
                return 0.0
            excedente = falhas - self.LIMITE_ANTES_DO_ATRASO
            return min(2.0**excedente, self.ATRASO_MAXIMO_SEGUNDOS)

    def registrar_falha(self, chave: str) -> None:
        with self._trava:
            falhas, _ = self._tentativas.get(chave, (0, 0.0))
            self._tentativas[chave] = (falhas + 1, time.monotonic())

    def limpar(self, chave: str) -> None:
        with self._trava:
            self._tentativas.pop(chave, None)


tentativas = ControleDeTentativas()


def _exigir_modo_senha(settings: Settings) -> None:
    if settings.auth_mode.lower() != "senha":
        raise HTTPException(
            status_code=404,
            detail="Endpoint indisponível no modo de autenticação configurado.",
        )


def _exigir_segredo(settings: Settings) -> str:
    segredo = settings.sessao_jwt_secret
    if not segredo or len(segredo) < 32:
        # Falhar aqui é melhor do que assinar com um segredo fraco: um token
        # assinado com valor previsível permitiria forjar a sessão de qualquer
        # propagandista.
        logger.error("SESSAO_JWT_SECRET ausente ou com menos de 32 caracteres.")
        raise HTTPException(
            status_code=503,
            detail="Autenticação indisponível. Configuração pendente no servidor.",
        )
    return segredo


def buscar_cadastro(email: str) -> Identidade | None:
    """Setor e nome do propagandista, direto de tb_propagandistas."""
    engine = get_engine()
    with engine.connect() as conn:
        linhas = conn.execute(text(SQL_CADASTRO), {"email": email}).fetchall()

    # Mais de uma linha é cadastro ambíguo. Tratar como não resolvido, nunca
    # escolher a primeira, é a mesma proteção defensiva de resolver_contexto().
    if len(linhas) != 1:
        return None

    setor = str(linhas[0].setor or "").strip()
    if not setor:
        return None

    return Identidade(
        email=email,
        setor=setor,
        nome=(str(linhas[0].nome).strip() if linhas[0].nome else None),
    )


def criar_token(identidade: Identidade, settings: Settings) -> tuple[str, int]:
    agora = datetime.now(timezone.utc)
    minutos = settings.sessao_token_minutos
    payload = {
        "sub": identidade.email,
        "email": identidade.email,
        "setor": identidade.setor,
        "nome": identidade.nome,
        "iat": agora,
        "exp": agora + timedelta(minutes=minutos),
        "iss": EMISSOR,
        "aud": AUDIENCIA,
    }
    return jwt.encode(payload, _exigir_segredo(settings), algorithm="HS256"), minutos * 60


def ler_token(token: str, settings: Settings) -> dict:
    try:
        return jwt.decode(
            token,
            _exigir_segredo(settings),
            algorithms=["HS256"],
            issuer=EMISSOR,
            audience=AUDIENCIA,
        )
    except jwt.PyJWTError as exc:
        # A causa fica no log do servidor. A resposta ao cliente não distingue
        # token expirado de token adulterado.
        logger.info("Token de sessão rejeitado: %s", type(exc).__name__)
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada.") from exc


@sessao_router.post("/login", response_model=LoginResponse)
def login(
    corpo: LoginRequest,
    tarefas: BackgroundTasks,
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    _exigir_modo_senha(settings)
    _exigir_segredo(settings)

    email = corpo.email.strip().lower()

    atraso = tentativas.atraso_atual(email)
    if atraso:
        time.sleep(atraso)

    acesso = acessos.buscar(email)

    # A verificação roda mesmo sem acesso encontrado, contra um hash
    # descartável, para que o tempo de resposta não revele quais e-mails estão
    # cadastrados.
    senha_confere = verificar_senha(
        corpo.senha, acesso.senha_hash if acesso else HASH_DESCARTAVEL
    )

    # STATUS_ACESSO checado IMEDIATAMENTE após a senha conferir, antes de
    # buscar_cadastro() — ordem explícita: quem não tem linha em
    # tb_perfil_portal (ou está BLOQUEADO) recebe 403 ACESSO_BLOQUEADO em
    # vez do 401 genérico de "e-mail ou senha inválidos", mesmo que a senha
    # esteja certa. Só roda quando a senha já conferiu, para não vazar por
    # tempo de resposta/código de erro se um e-mail existe em acessos.csv.
    identidade = None
    if acesso and senha_confere:
        exigir_acesso_liberado(email, settings)
        identidade = buscar_cadastro(email)

    if not (acesso and senha_confere and identidade):
        tentativas.registrar_falha(email)
        logger.info("Falha de login no portal.")  # sem e-mail, sem senha
        raise HTTPException(status_code=401, detail="E-mail ou senha inválidos.")

    tentativas.limpar(email)

    token, expira_em = criar_token(identidade, settings)

    # Fora do caminho da resposta, de propósito. O carimbo é um MERGE em
    # `tb_perfil_portal` e custa cerca de 2,9 segundos, medido em 07/08/2026:
    # o Delta precisa ler, comparar, reescrever arquivo e commitar transação.
    # Colocado antes da resposta, como estava na primeira versão, ele sozinho
    # respondia por quase todo o tempo de espera de quem entrava no portal.
    #
    # Ninguém aguarda esse dado: ele só alimenta o campo "último acesso" da aba
    # Usuário, que a pessoa vê depois. Em segundo plano, o login responde
    # assim que o token existe e a gravação acontece em seguida.
    #
    # O que se perde: se o processo morrer entre a resposta e a tarefa, aquele
    # acesso não é carimbado. Para um campo informativo, é troca melhor do que
    # três segundos de espera em todo login.
    tarefas.add_task(registrar_acesso, email)

    logger.info("Login efetuado no portal.")
    return LoginResponse(
        access_token=token,
        expira_em=expira_em,
        nome=identidade.nome,
        setor=identidade.setor,
    )


def resolver_sessao(
    authorization: str | None = Header(None),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Dependência dos endpoints que exigem sessão ativa no modo senha."""
    _exigir_modo_senha(settings)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sessão ausente.")
    return ler_token(authorization.split(" ", 1)[1].strip(), settings)
