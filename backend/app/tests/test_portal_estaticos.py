"""Testes da rota que serve o portal.

O caminho vem da URL e é concatenado ao diretório dos estáticos. Sem
validação, um pedido cru como `/../acessos.csv` sai desse diretório e entrega
arquivos da aplicação. Clientes HTTP normalizam o `..` antes de enviar, mas
isso é comportamento do cliente e não vale como proteção.
"""

import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse


def montar_portal(dist: Path) -> FastAPI:
    """Reproduz a rota de backend/app/main.py."""
    app = FastAPI()

    def dentro_do_portal(caminho: str) -> Path | None:
        try:
            alvo = (dist / caminho).resolve()
        except (OSError, ValueError):
            return None
        if alvo != dist and dist not in alvo.parents:
            return None
        return alvo if alvo.is_file() else None

    @app.get("/{caminho:path}", include_in_schema=False)
    def servir_portal(caminho: str):
        arquivo = dentro_do_portal(caminho) if caminho else None
        if arquivo is not None:
            return FileResponse(arquivo)
        return FileResponse(dist / "index.html")

    return app


@pytest.fixture(scope="module")
def ambiente(tmp_path_factory):
    """Monta a mesma estrutura da imagem: os estáticos ficam em uma subpasta
    da raiz da aplicação, ao lado dos arquivos sensíveis."""
    raiz = tmp_path_factory.mktemp("app")
    dist = (raiz / "frontend_dist").resolve()
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>portal</html>")
    (dist / "assets" / "app.js").write_text("console.log('portal')")
    (raiz / "acessos.csv").write_text("rep_email;senha_hash;ativo\nx@ache.com.br;hash-secreto;true\n")
    (raiz / ".env").write_text("DATABRICKS_CLIENT_SECRET=segredo\n")

    servidor = uvicorn.Server(
        uvicorn.Config(montar_portal(dist), host="127.0.0.1", port=8097, log_level="critical")
    )
    threading.Thread(target=servidor.run, daemon=True).start()
    for _ in range(50):
        if getattr(servidor, "started", False):
            break
        time.sleep(0.1)
    yield
    servidor.should_exit = True


def pedir(caminho: str) -> str:
    """Envia a requisição sem normalizar o caminho, como faria um cliente
    montado na mão. Bibliotecas HTTP resolvem o `..` antes de enviar e
    mascarariam a falha."""
    conexao = socket.create_connection(("127.0.0.1", 8097), timeout=10)
    conexao.sendall(
        f"GET {caminho} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode()
    )
    resposta = b""
    while True:
        parte = conexao.recv(4096)
        if not parte:
            break
        resposta += parte
    conexao.close()
    return resposta.decode(errors="replace")


@pytest.mark.parametrize(
    "ataque",
    [
        "/../acessos.csv",
        "/../.env",
        "/assets/../../acessos.csv",
        "/%2e%2e/acessos.csv",
        "/....//....//acessos.csv",
        "/../../../../etc/passwd",
        "/assets/../../../etc/hosts",
    ],
)
def test_nao_entrega_arquivo_fora_do_portal(ambiente, ataque):
    corpo = pedir(ataque)
    assert "hash-secreto" not in corpo
    assert "SECRET" not in corpo
    assert "root:" not in corpo


@pytest.mark.parametrize(
    "caminho, esperado",
    [
        ("/", "portal"),
        ("/index.html", "portal"),
        ("/assets/app.js", "console.log"),
        ("/recomendacoes", "portal"),
    ],
)
def test_portal_continua_funcionando(ambiente, caminho, esperado):
    """Rota desconhecida devolve o index.html, para a navegação do React."""
    assert esperado in pedir(caminho)


def test_index_nao_pode_ficar_em_cache_e_assets_podem():
    """O `index.html` aponta para o pacote da vez e o nome dele nunca muda.
    Sem `no-cache`, o navegador continua abrindo o pacote anterior depois de
    uma publicação. Aconteceu em 10/08/2026, e o portal parecia não ter sido
    publicado. Os arquivos de `assets` têm hash no nome e são o caso oposto."""
    from fastapi.testclient import TestClient

    from backend.app.main import app

    cliente = TestClient(app)
    raiz = cliente.get("/")
    if raiz.status_code != 200:
        pytest.skip("frontend/dist não existe neste ambiente")

    assert raiz.headers.get("cache-control") == "no-cache"

    import re

    achado = re.search(r"assets/[^\"]+\.js", raiz.text)
    assert achado, "o index não referencia nenhum pacote"
    ativo = cliente.get("/" + achado.group(0))
    assert ativo.status_code == 200
    assert "immutable" in ativo.headers.get("cache-control", "")
