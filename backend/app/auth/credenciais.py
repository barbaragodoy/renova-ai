"""Geração e verificação das senhas de acesso ao portal.

A senha é gerada pelo time, entregue ao propagandista e armazenada somente
como hash, em `acessos.csv` dentro da imagem. O texto puro não fica em
arquivo, log ou banco.

Optamos por arquivo em vez de tabela porque o piloto tem poucas dezenas de
usuários e o portal já é publicado como imagem única: o arquivo viaja junto
com o container e não exige infraestrutura nova. O custo é que trocar a senha
de alguém pede um novo build, e não um UPDATE. Quando a base crescer ou o
Entra ID entrar, essa camada some.

Formato do hash: `pbkdf2_sha256$<iteracoes>$<salt_b64>$<hash_b64>`.
PBKDF2-HMAC-SHA256 vem da biblioteca padrão e não acrescenta dependência ao
`requirements.txt`. O número de iterações fica dentro do próprio hash, então
aumentar o custo depois não invalida as senhas já distribuídas.

O alfabeto da senha exclui caracteres que se confundem quando alguém digita a
partir de um papel ou de uma mensagem: 0, O, 1, l, I. Os blocos separados por
hífen reduzem erro de digitação em celular, que é o dispositivo principal do
propagandista em campo.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("renovai")

ALGORITMO = "pbkdf2_sha256"
ITERACOES = 600_000
TAMANHO_SALT = 16

ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
BLOCOS = 3
CARACTERES_POR_BLOCO = 4


def gerar_senha() -> str:
    """Devolve uma senha nova, no formato XXXX-XXXX-XXXX.

    São 12 caracteres em um alfabeto de 55 símbolos, o que dá cerca de 69 bits
    de entropia. Suficiente para inviabilizar força bruta contra o hash e
    curta o bastante para o propagandista digitar sem erro.
    """
    blocos = [
        "".join(secrets.choice(ALFABETO) for _ in range(CARACTERES_POR_BLOCO))
        for _ in range(BLOCOS)
    ]
    return "-".join(blocos)


def gerar_hash(senha: str, iteracoes: int = ITERACOES) -> str:
    salt = secrets.token_bytes(TAMANHO_SALT)
    derivado = hashlib.pbkdf2_hmac("sha256", senha.encode(), salt, iteracoes)
    return "${}${}${}${}".format(
        ALGORITMO,
        iteracoes,
        base64.b64encode(salt).decode(),
        base64.b64encode(derivado).decode(),
    ).lstrip("$")


def verificar_senha(senha: str, hash_armazenado: str) -> bool:
    """Compara a senha informada com o hash, em tempo constante.

    Devolve False para qualquer hash malformado em vez de levantar exceção: um
    registro corrompido na tabela não deve derrubar o login dos demais.
    """
    try:
        algoritmo, iteracoes, salt_b64, esperado_b64 = hash_armazenado.split("$")
    except (ValueError, AttributeError):
        return False

    if algoritmo != ALGORITMO:
        return False

    try:
        derivado = hashlib.pbkdf2_hmac(
            "sha256",
            senha.encode(),
            base64.b64decode(salt_b64),
            int(iteracoes),
        )
        esperado = base64.b64decode(esperado_b64)
    except (ValueError, TypeError):
        return False

    return hmac.compare_digest(derivado, esperado)


@dataclass(frozen=True)
class AcessoPortal:
    email: str
    senha_hash: str
    ativo: bool


class RepositorioDeAcessos:
    """Lê `acessos.csv` uma vez e mantém os hashes em memória.

    O arquivo é gerado por `backend/scripts/gerar_acesso_portal.py` e entra na
    imagem no build. Ele não é versionado: contém material de credencial e o
    monorepo é compartilhado com outras equipes.

    Colunas: rep_email, senha_hash, ativo.

    Um e-mail repetido no arquivo invalida os dois registros, em vez de deixar
    o último vencer. Cadastro ambíguo não deve autenticar ninguém, mesma
    postura de resolver_contexto().
    """

    def __init__(self, caminho: Path) -> None:
        self._caminho = caminho
        self._acessos: dict[str, AcessoPortal] | None = None

    @property
    def disponivel(self) -> bool:
        return self._caminho.is_file()

    def carregar(self) -> dict[str, AcessoPortal]:
        if self._acessos is not None:
            return self._acessos

        if not self.disponivel:
            logger.error("Arquivo de acessos não encontrado em %s.", self._caminho)
            self._acessos = {}
            return self._acessos

        acessos: dict[str, AcessoPortal] = {}
        duplicados: set[str] = set()

        with self._caminho.open(encoding="utf-8", newline="") as arquivo:
            for linha in csv.DictReader(arquivo, delimiter=";"):
                email = (linha.get("rep_email") or "").strip().lower()
                senha_hash = (linha.get("senha_hash") or "").strip()
                if not email or not senha_hash:
                    continue
                if email in acessos:
                    duplicados.add(email)
                    continue
                acessos[email] = AcessoPortal(
                    email=email,
                    senha_hash=senha_hash,
                    ativo=(linha.get("ativo") or "true").strip().lower()
                    in ("true", "1", "sim"),
                )

        for email in duplicados:
            acessos.pop(email, None)
        if duplicados:
            logger.warning("%d e-mail(s) repetido(s) no arquivo de acessos.", len(duplicados))

        logger.info("Acessos do portal carregados: %d registro(s).", len(acessos))
        self._acessos = acessos
        return acessos

    def buscar(self, email: str) -> AcessoPortal | None:
        acesso = self.carregar().get(email.strip().lower())
        if acesso is None or not acesso.ativo:
            return None
        return acesso
