"""Testes do login por e-mail e senha do portal."""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.auth import sessao as modulo_sessao
from backend.app.auth.credenciais import (
    ALFABETO,
    AcessoPortal as AcessoPortalCsv,
    RepositorioDeAcessos,
    gerar_hash,
    gerar_senha,
    verificar_senha,
)
from backend.app.auth.sessao import Identidade, sessao_router
from backend.app.config import Settings

# Estes testes cobrem a mecânica de login (token, tarefa de fundo, registro
# de acesso) — a integração com STATUS_ACESSO tem cobertura dedicada em
# test_status_acesso.py. Fixture compartilhada em conftest.py.
pytestmark = pytest.mark.usefixtures("liberar_acesso_por_padrao")

SEGREDO = "x" * 40
SENHA = "Kd7m-Qw3x-Rt9p"

ACESSO = AcessoPortalCsv(
    email="ana.silva@ache.com.br",
    senha_hash=gerar_hash(SENHA, iteracoes=1_000),  # custo baixo só no teste
    ativo=True,
)

IDENTIDADE = Identidade(
    email="ana.silva@ache.com.br",
    setor="010105010352",
    nome="Ana Silva Souza",
)


def _engine_falsa(linhas):
    class Conexao:
        def execute(self, *_a, **_k):
            return type("R", (), {"fetchall": lambda self: linhas})()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    return type("E", (), {"connect": lambda self: Conexao()})()


def _linha(setor="010105010352", nome="Ana Silva Souza"):
    return type("L", (), {"setor": setor, "nome": nome})()


@contextmanager
def _login_ok():
    """Acesso presente no arquivo e cadastro presente na tabela.

    `registrar_acesso` entra no patch junto com o resto: ele grava em
    `tb_perfil_portal` com a engine real, e sem isto rodar a suíte cria linha
    de teste no Databricks. Aconteceu em 07/08/2026, quando o carimbo de
    acesso foi acrescentado ao login e a suíte gravou `ana.silva@ache.com.br`
    na tabela.
    """
    with patch.object(modulo_sessao.acessos, "buscar", return_value=ACESSO) as busca:
        with patch.object(modulo_sessao, "buscar_cadastro", return_value=IDENTIDADE):
            with patch.object(modulo_sessao, "registrar_acesso"):
                yield busca


@contextmanager
def _login_sem_acesso():
    """E-mail que não está no arquivo de acessos."""
    with patch.object(modulo_sessao.acessos, "buscar", return_value=None) as busca:
        with patch.object(modulo_sessao, "buscar_cadastro", return_value=None):
            with patch.object(modulo_sessao, "registrar_acesso"):
                yield busca


def montar_app(settings: Settings) -> TestClient:
    app = FastAPI()
    app.include_router(sessao_router, prefix="/auth")
    app.dependency_overrides[modulo_sessao.get_settings] = lambda: settings
    return TestClient(app)


@pytest.fixture
def settings_senha() -> Settings:
    return Settings(auth_mode="senha", sessao_jwt_secret=SEGREDO, sessao_token_minutos=60)


@pytest.fixture(autouse=True)
def limpar_tentativas():
    modulo_sessao.tentativas = modulo_sessao.ControleDeTentativas()
    yield


# --------------------------------------------------------------- credenciais


def test_senha_tem_formato_esperado():
    senha = gerar_senha()
    blocos = senha.split("-")
    assert len(blocos) == 3
    assert all(len(bloco) == 4 for bloco in blocos)
    assert all(caractere in ALFABETO for bloco in blocos for caractere in bloco)


def test_senha_nao_usa_caracteres_ambiguos():
    """0, O, 1, l e I são digitados errado quando lidos de um papel."""
    for _ in range(200):
        assert not set(gerar_senha()) & set("0O1lI")


def test_senhas_geradas_sao_diferentes():
    assert len({gerar_senha() for _ in range(500)}) == 500


def test_hash_muda_a_cada_geracao_pela_mesma_senha():
    """Salt distinto impede identificar duas pessoas com a mesma senha."""
    assert gerar_hash(SENHA, 1_000) != gerar_hash(SENHA, 1_000)


def test_verificacao_aceita_a_senha_correta():
    assert verificar_senha(SENHA, gerar_hash(SENHA, 1_000))


def test_verificacao_recusa_senha_errada():
    assert not verificar_senha("outra-senha", gerar_hash(SENHA, 1_000))


@pytest.mark.parametrize(
    "hash_invalido",
    ["", "sem-cifrao", "pbkdf2_sha256$abc$def", "md5$1000$c2FsdA==$aGFzaA==", None],
)
def test_hash_malformado_nao_derruba_o_login(hash_invalido):
    """Registro corrompido recusa aquele acesso, não quebra o serviço."""
    assert verificar_senha(SENHA, hash_invalido) is False


def test_iteracoes_ficam_no_hash():
    """Permite aumentar o custo depois sem invalidar as senhas distribuídas."""
    assert gerar_hash(SENHA, 1_000).split("$")[1] == "1000"
    assert verificar_senha(SENHA, gerar_hash(SENHA, 2_000))


# --------------------------------------------------------------------- login


def test_login_valido_devolve_token(settings_senha):
    cliente = montar_app(settings_senha)
    with _login_ok():
        resposta = cliente.post(
            "/auth/login", json={"email": "ana.silva@ache.com.br", "senha": SENHA}
        )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["setor"] == "010105010352"
    assert corpo["nome"] == "Ana Silva Souza"
    assert corpo["expira_em"] == 3600


def test_token_nao_carrega_senha_nem_matricula(settings_senha):
    cliente = montar_app(settings_senha)
    with _login_ok():
        resposta = cliente.post(
            "/auth/login", json={"email": "ana.silva@ache.com.br", "senha": SENHA}
        )

    payload = jwt.decode(
        resposta.json()["access_token"],
        SEGREDO,
        algorithms=["HS256"],
        issuer=modulo_sessao.EMISSOR,
        audience=modulo_sessao.AUDIENCIA,
    )
    conteudo = str(payload)
    assert SENHA not in conteudo
    assert "matricula" not in conteudo
    assert payload["setor"] == "010105010352"


def test_senha_errada_devolve_401(settings_senha):
    cliente = montar_app(settings_senha)
    with _login_ok():
        resposta = cliente.post(
            "/auth/login", json={"email": "ana.silva@ache.com.br", "senha": "errada"}
        )
    assert resposta.status_code == 401


def test_email_inexistente_devolve_a_mesma_resposta(settings_senha):
    """Não deve ser possível descobrir quais e-mails estão cadastrados."""
    cliente = montar_app(settings_senha)

    with _login_ok():
        senha_errada = cliente.post(
            "/auth/login", json={"email": "ana.silva@ache.com.br", "senha": "errada"}
        )
    with _login_sem_acesso():
        email_errado = cliente.post(
            "/auth/login", json={"email": "ninguem@ache.com.br", "senha": "errada"}
        )

    assert senha_errada.status_code == email_errado.status_code == 401
    assert senha_errada.json()["detail"] == email_errado.json()["detail"]


def test_email_com_caixa_diferente_funciona(settings_senha):
    cliente = montar_app(settings_senha)
    with _login_ok() as busca:
        resposta = cliente.post(
            "/auth/login", json={"email": "ANA.SILVA@ACHE.COM.BR", "senha": SENHA}
        )

    assert resposta.status_code == 200
    busca.assert_called_once_with("ana.silva@ache.com.br")


def test_sem_segredo_configurado_devolve_503():
    cliente = montar_app(Settings(auth_mode="senha", sessao_jwt_secret=""))
    resposta = cliente.post(
        "/auth/login", json={"email": "ana.silva@ache.com.br", "senha": SENHA}
    )
    assert resposta.status_code == 503


def test_segredo_curto_devolve_503():
    cliente = montar_app(Settings(auth_mode="senha", sessao_jwt_secret="curto"))
    resposta = cliente.post(
        "/auth/login", json={"email": "ana.silva@ache.com.br", "senha": SENHA}
    )
    assert resposta.status_code == 503


def test_modo_entra_id_desliga_o_endpoint():
    cliente = montar_app(Settings(auth_mode="entra_id", sessao_jwt_secret=SEGREDO))
    resposta = cliente.post(
        "/auth/login", json={"email": "ana.silva@ache.com.br", "senha": SENHA}
    )
    assert resposta.status_code == 404


def test_ler_token_rejeita_assinatura_de_outro_segredo(settings_senha):
    token, _ = modulo_sessao.criar_token(IDENTIDADE, settings_senha)
    outro = Settings(auth_mode="senha", sessao_jwt_secret="y" * 40)

    with pytest.raises(Exception) as erro:
        modulo_sessao.ler_token(token, outro)
    assert getattr(erro.value, "status_code", None) == 401


# --------------------------------------------------- cadastro e arquivo


def test_cadastro_duplicado_nao_autentica():
    with patch.object(
        modulo_sessao, "get_engine", return_value=_engine_falsa([_linha(), _linha()])
    ):
        assert modulo_sessao.buscar_cadastro("ana.silva@ache.com.br") is None


def test_sem_cadastro_devolve_none():
    """Quem sai de tb_propagandistas perde o acesso, mesmo tendo senha."""
    with patch.object(modulo_sessao, "get_engine", return_value=_engine_falsa([])):
        assert modulo_sessao.buscar_cadastro("ninguem@ache.com.br") is None


def test_senha_valida_sem_cadastro_nao_entra(settings_senha):
    cliente = montar_app(settings_senha)
    with patch.object(modulo_sessao.acessos, "buscar", return_value=ACESSO):
        with patch.object(modulo_sessao, "buscar_cadastro", return_value=None):
            resposta = cliente.post(
                "/auth/login", json={"email": "ana.silva@ache.com.br", "senha": SENHA}
            )
    assert resposta.status_code == 401


def _escrever_acessos(tmp_path, linhas):
    caminho = tmp_path / "acessos.csv"
    caminho.write_text(
        "rep_email;senha_hash;ativo\n" + "\n".join(linhas) + "\n", encoding="utf-8"
    )
    return caminho


def test_arquivo_ausente_nao_derruba_o_servico(tmp_path):
    repo = RepositorioDeAcessos(tmp_path / "nao-existe.csv")
    assert repo.disponivel is False
    assert repo.buscar("ana.silva@ache.com.br") is None


def test_arquivo_le_e_normaliza_o_email(tmp_path):
    caminho = _escrever_acessos(tmp_path, ["ANA.SILVA@ACHE.COM.BR;hash-x;true"])
    repo = RepositorioDeAcessos(caminho)
    assert repo.buscar("ana.silva@ache.com.br").senha_hash == "hash-x"


def test_arquivo_respeita_a_coluna_ativo(tmp_path):
    """Revogar um acesso é trocar a coluna, sem apagar a linha."""
    caminho = _escrever_acessos(tmp_path, ["ana.silva@ache.com.br;hash-x;false"])
    assert RepositorioDeAcessos(caminho).buscar("ana.silva@ache.com.br") is None


def test_arquivo_invalida_email_repetido(tmp_path):
    """Linha duplicada não pode deixar a última vencer silenciosamente."""
    caminho = _escrever_acessos(
        tmp_path,
        ["ana.silva@ache.com.br;hash-a;true", "ana.silva@ache.com.br;hash-b;true"],
    )
    assert RepositorioDeAcessos(caminho).buscar("ana.silva@ache.com.br") is None


def test_arquivo_ignora_linha_incompleta(tmp_path):
    caminho = _escrever_acessos(
        tmp_path, ["ana.silva@ache.com.br;;true", "bruno@ache.com.br;hash-b;true"]
    )
    repo = RepositorioDeAcessos(caminho)
    assert repo.buscar("ana.silva@ache.com.br") is None
    assert repo.buscar("bruno@ache.com.br") is not None


def test_atraso_progressivo_apos_tentativas_seguidas():
    controle = modulo_sessao.ControleDeTentativas()
    chave = "ana.silva@ache.com.br"

    for _ in range(controle.LIMITE_ANTES_DO_ATRASO):
        controle.registrar_falha(chave)
    assert controle.atraso_atual(chave) == 0.0

    controle.registrar_falha(chave)
    assert controle.atraso_atual(chave) > 0.0

    controle.limpar(chave)
    assert controle.atraso_atual(chave) == 0.0


def test_atraso_tem_teto():
    controle = modulo_sessao.ControleDeTentativas()
    for _ in range(50):
        controle.registrar_falha("ana.silva@ache.com.br")
    assert controle.atraso_atual("ana.silva@ache.com.br") == controle.ATRASO_MAXIMO_SEGUNDOS


def test_login_agenda_o_acesso_em_segundo_plano(settings_senha):
    """O carimbo não pode voltar para o caminho da resposta.

    Ele é um MERGE em `tb_perfil_portal` e custa cerca de 2,9 segundos, medido
    em 07/08/2026. Na primeira versão ele rodava antes da resposta e sozinho
    respondia por quase toda a espera de quem entrava no portal.
    """
    from fastapi import BackgroundTasks

    cliente = montar_app(settings_senha)
    agendadas = []

    with patch.object(modulo_sessao.acessos, "buscar", return_value=ACESSO):
        with patch.object(modulo_sessao, "buscar_cadastro", return_value=IDENTIDADE):
            with patch.object(
                BackgroundTasks,
                "add_task",
                lambda self, fn, *a, **k: agendadas.append((fn, a)),
            ):
                resposta = cliente.post(
                    "/auth/login",
                    json={"email": "ana.silva@ache.com.br", "senha": SENHA},
                )

    assert resposta.status_code == 200
    assert agendadas == [(modulo_sessao.registrar_acesso, ("ana.silva@ache.com.br",))]


def test_login_registra_o_acesso(settings_senha):
    """O carimbo de acesso alimenta o campo "último acesso" da aba Usuário."""
    cliente = montar_app(settings_senha)
    with patch.object(modulo_sessao.acessos, "buscar", return_value=ACESSO):
        with patch.object(modulo_sessao, "buscar_cadastro", return_value=IDENTIDADE):
            with patch.object(modulo_sessao, "registrar_acesso") as registro:
                resposta = cliente.post(
                    "/auth/login",
                    json={"email": "ana.silva@ache.com.br", "senha": SENHA},
                )

    assert resposta.status_code == 200
    registro.assert_called_once_with("ana.silva@ache.com.br")


def test_falha_no_registro_de_acesso_nao_impede_o_login(settings_senha):
    """Entrar no portal não pode depender de uma escrita de conveniência.

    A própria `registrar_acesso` engole a exceção, e este teste garante que
    ninguém remova essa proteção sem perceber o efeito.
    """
    cliente = montar_app(settings_senha)
    with patch.object(modulo_sessao.acessos, "buscar", return_value=ACESSO):
        with patch.object(modulo_sessao, "buscar_cadastro", return_value=IDENTIDADE):
            with patch(
                "backend.app.auth.perfil._get_engine",
                side_effect=RuntimeError("banco fora do ar"),
            ):
                resposta = cliente.post(
                    "/auth/login",
                    json={"email": "ana.silva@ache.com.br", "senha": SENHA},
                )

    assert resposta.status_code == 200
    assert resposta.json()["access_token"]
