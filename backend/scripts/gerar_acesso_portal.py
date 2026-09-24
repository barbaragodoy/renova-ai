"""Gera as senhas de acesso ao Portal RenovAI.

Lê os propagandistas de `tb_propagandistas`, sorteia uma senha para cada um e
produz dois arquivos:

1. `senhas-portal-<data>.csv`, com e-mail, nome, setor e senha em texto puro.
   É o material de distribuição individual. Não pode ser versionado, enviado
   por canal aberto nem mantido depois da entrega.
2. `acessos.csv`, com e-mail, hash e situação. É o arquivo que a aplicação lê
   no login. Não contém senha em texto puro, mas também não é versionado: o
   monorepo é compartilhado com outras equipes.

Uso:

    python -m backend.scripts.gerar_acesso_portal
    python -m backend.scripts.gerar_acesso_portal --limite 50
    python -m backend.scripts.gerar_acesso_portal --emails a@ache.com.br
    python -m backend.scripts.gerar_acesso_portal --dry-run

O `--limite` atende o piloto, quando o acesso vai para um grupo reduzido antes
da liberação geral. O `--dry-run` mostra quantos registros seriam gerados sem
escrever arquivo.

Para regerar a senha de uma pessoa, rode com `--emails` apenas para ela: o
`acessos.csv` existente é preservado e só aquela linha é substituída. As
demais senhas continuam valendo.

Depois de gerar, o `acessos.csv` precisa estar na raiz do APP_RENOVAI no
momento do build da imagem, porque é de lá que ele é copiado para dentro do
container.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import text

from backend.app.auth.credenciais import gerar_hash, gerar_senha
from backend.app.db.databricks_connection import get_engine

RAIZ = Path(__file__).resolve().parents[2]
ARQUIVO_ACESSOS = RAIZ / "acessos.csv"

SQL_PROPAGANDISTAS = """
SELECT rep_email AS email, rep_nome AS nome, setor AS setor
FROM tb_propagandistas
WHERE rep_email IS NOT NULL
  AND setor IS NOT NULL
ORDER BY rep_email
"""


def carregar_propagandistas(emails: list[str] | None, limite: int | None) -> list[dict]:
    engine = get_engine()
    with engine.connect() as conn:
        linhas = conn.execute(text(SQL_PROPAGANDISTAS)).fetchall()

    registros = [
        {
            "email": str(linha.email).strip(),
            "nome": (str(linha.nome).strip() if linha.nome else ""),
            "setor": str(linha.setor).strip(),
        }
        for linha in linhas
        if str(linha.email or "").strip()
    ]

    if emails:
        desejados = {e.strip().lower() for e in emails if e.strip()}
        registros = [r for r in registros if r["email"].lower() in desejados]
        for email in sorted(desejados - {r["email"].lower() for r in registros}):
            print(f"aviso: {email} não encontrado em tb_propagandistas", file=sys.stderr)

    # E-mail duplicado no cadastro não autentica (ver auth/sessao.py). Gerar
    # senha para ele criaria uma credencial que nunca funciona.
    contagem: dict[str, int] = {}
    for registro in registros:
        chave = registro["email"].lower()
        contagem[chave] = contagem.get(chave, 0) + 1

    duplicados = {email for email, total in contagem.items() if total > 1}
    for email in sorted(duplicados):
        print(f"aviso: {email} tem mais de um cadastro, ignorado", file=sys.stderr)
    registros = [r for r in registros if r["email"].lower() not in duplicados]

    return registros[:limite] if limite else registros


def ler_acessos_existentes() -> dict[str, dict]:
    """Preserva quem já tem senha, para que uma regeração parcial não derrube
    o acesso dos demais."""
    if not ARQUIVO_ACESSOS.is_file():
        return {}

    with ARQUIVO_ACESSOS.open(encoding="utf-8", newline="") as arquivo:
        return {
            (linha.get("rep_email") or "").strip().lower(): linha
            for linha in csv.DictReader(arquivo, delimiter=";")
            if (linha.get("rep_email") or "").strip()
        }


def escrever_senhas(caminho: Path, registros: list[dict]) -> None:
    with caminho.open("w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.DictWriter(
            arquivo, fieldnames=["email", "nome", "setor", "senha"], delimiter=";"
        )
        escritor.writeheader()
        escritor.writerows(
            {chave: registro[chave] for chave in ("email", "nome", "setor", "senha")}
            for registro in registros
        )
    # O arquivo tem senha em texto puro: leitura restrita ao dono.
    caminho.chmod(0o600)


def escrever_acessos(linhas: dict[str, dict]) -> None:
    with ARQUIVO_ACESSOS.open("w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.DictWriter(
            arquivo, fieldnames=["rep_email", "senha_hash", "ativo"], delimiter=";"
        )
        escritor.writeheader()
        for email in sorted(linhas):
            escritor.writerow(linhas[email])
    ARQUIVO_ACESSOS.chmod(0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saida", default=".", help="Diretório da lista de senhas")
    parser.add_argument("--emails", default="", help="Lista separada por vírgula")
    parser.add_argument("--limite", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    argumentos = parser.parse_args()

    emails = [e for e in argumentos.emails.split(",") if e.strip()] or None
    registros = carregar_propagandistas(emails, argumentos.limite)

    if not registros:
        print("Nenhum propagandista encontrado para os filtros informados.")
        return 1

    if argumentos.dry_run:
        print(f"{len(registros)} senha(s) seriam geradas. Nenhum arquivo foi escrito.")
        return 0

    acessos = ler_acessos_existentes()
    preservados = len(acessos)

    for registro in registros:
        registro["senha"] = gerar_senha()
        acessos[registro["email"].lower()] = {
            "rep_email": registro["email"],
            "senha_hash": gerar_hash(registro["senha"]),
            "ativo": "true",
        }

    destino = Path(argumentos.saida)
    destino.mkdir(parents=True, exist_ok=True)
    caminho_senhas = destino / f"senhas-portal-{date.today().isoformat()}.csv"

    escrever_senhas(caminho_senhas, registros)
    escrever_acessos(acessos)

    print(f"{len(registros)} senha(s) gerada(s).")
    if preservados:
        print(f"{preservados} acesso(s) anterior(es) preservado(s).")
    print(f"Lista para distribuição: {caminho_senhas}")
    print(f"Arquivo da aplicação:    {ARQUIVO_ACESSOS}")
    print()
    print("A lista contém senha em texto puro. Entregue individualmente e")
    print("apague o arquivo depois da distribuição. Nenhum dos dois é")
    print("versionado; o acessos.csv precisa estar presente no build da imagem.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
