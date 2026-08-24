"""Sessão válida para os testes de regra de negócio.

Em 04/08/2026 o modo `senha` passou a exigir sessão em toda rota de negócio,
depois do bypass de autenticação encontrado naquele dia. Os testes que
exercitam regra de negócio continuam entrando pela porta real, com um token de
verdade, em vez de ligar um modo de exceção: usar o caminho de exceção
desligaria justamente o guarda que existe para impedir rota sem sessão.
"""
from backend.app.auth.sessao import Identidade, criar_token
from backend.app.config import get_settings

EMAIL = "ana.silva@ache.com.br"
SETOR = "SP_INTERIOR"
NOME = "Ana Silva"


def cabecalho(email: str = EMAIL, setor: str = SETOR, nome: str = NOME) -> dict[str, str]:
    """Cabeçalho `Authorization` com uma sessão assinada pelo segredo de teste."""
    token, _ = criar_token(Identidade(email=email, setor=setor, nome=nome), get_settings())
    return {"Authorization": f"Bearer {token}"}


CABECALHO = cabecalho()
