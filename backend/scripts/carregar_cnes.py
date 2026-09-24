"""Carga do CNES para o lakehouse: onde cada médico atende, pelo CRM.

Produz `acheinfo_dev.renovai.tb_cnes_local_atendimento`, uma linha por par
médico e estabelecimento, com o endereço completo, telefone e coordenada do
estabelecimento. É a fonte do "também atende em" do card do médico, decisão de
George em 18/09/2026.

Origem
------
Base mensal do CNES, publicada pelo DATASUS em
`ftp://ftp.datasus.gov.br/cnes/BASE_DE_DADOS_CNES_AAAAMM.ZIP`, perto de 740 MB.
Três tabelas interessam:

- `tbCargaHorariaSus`: o vínculo profissional e estabelecimento. Traz o
  conselho de classe, o número de registro e a UF do CRM. É por aqui que o CRM
  do nosso painel encontra o médico, sem passar por CPF nem CNS.
- `tbEstabelecimento`: nome, endereço, telefone, coordenada, município.
- `tbMunicipio`: nome do município a partir do código.

Medido em 18/09/2026 na competência 202608: 1.795.117 vínculos de médico,
100% com UF e registro, 592.541 CRMs distintos. Numa amostra aleatória de
5.000 médicos do painel, 79,0% bateram; desses, 100% com logradouro, 95,1% com
telefone e 100% com coordenada.

O que este script NÃO faz, de propósito
---------------------------------------
Não lê `tbDadosProfissionalSus`, que traz `CO_CPF` e `CO_CNS`. A chave de
ligação é o CRM, que já está no vínculo, e dado pessoal do profissional não
entra no lakehouse. Se alguém precisar do nome do médico, ele vem da
`tb_dim_medicos` pelo próprio UFCRM.

Como rodar
----------
    # com o ZIP já baixado
    python -m backend.scripts.carregar_cnes --zip /tmp/BASE_DE_DADOS_CNES_202608.ZIP

    # baixando do FTP
    python -m backend.scripts.carregar_cnes --competencia 202608

Precisa do CLI `databricks` autenticado no perfil informado, e do warehouse
com permissão de escrita no schema `renovai`. A tabela é substituída inteira
a cada carga: o CNES é uma foto mensal, e manter competências antigas só
serviria para histórico, que ninguém pediu.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

logger = logging.getLogger("carregar_cnes")

FTP = "ftp://ftp.datasus.gov.br/cnes/BASE_DE_DADOS_CNES_{competencia}.ZIP"

# CBOs de médico começam por 2251, 2252 e 2253. Não filtrar por conselho de
# classe: o código 71, que responde por 99,6% dos vínculos de médico, não
# existe em `tbConselhoClasse`. Conferido em 18/09/2026.
PREFIXOS_CBO_MEDICO = ("2251", "2252", "2253")

TABELA = "acheinfo_dev.renovai.tb_cnes_local_atendimento"
VOLUME = "dbfs:/Volumes/acheinfo_dev/renovai/volume_renovai_dev/_insumos/cnes"

COLUNAS_SAIDA = [
    "ufcrm", "co_cnes", "nome_fantasia", "razao_social", "tipo_unidade",
    "logradouro", "numero", "complemento", "bairro", "cep",
    "co_municipio", "municipio", "uf", "telefone", "latitude", "longitude",
    "competencia",
]


def _abrir_csv(z: zipfile.ZipFile, nome: str):
    return csv.reader(io.TextIOWrapper(z.open(nome), encoding="latin1"), delimiter=";")


def _nome_na_zip(z: zipfile.ZipFile, prefixo: str) -> str:
    for n in z.namelist():
        if n.startswith(prefixo):
            return n
    raise FileNotFoundError(f"{prefixo}* não está no ZIP")


def _ufcrm(uf: str, registro: str) -> str | None:
    """"RS" + "48316" vira "RS0048316", o formato de tb_dim_medicos.

    Os 627.029 médicos do painel seguem UF mais sete dígitos, conferido em
    18/09/2026. Registro com mais de sete dígitos não existe no painel e é
    descartado aqui em vez de truncado.
    """
    uf = (uf or "").strip().upper()
    digitos = re.sub(r"\D", "", registro or "")
    if len(uf) != 2 or not digitos or len(digitos) > 7:
        return None
    return f"{uf}{int(digitos):07d}"


def _cep8(valor: str) -> str | None:
    digitos = re.sub(r"\D", "", valor or "")
    return digitos[-8:] if len(digitos) >= 8 else None


def extrair(zip_path: Path, competencia: str, saida: Path) -> dict:
    """Lê o ZIP e escreve o CSV denormalizado. Devolve contadores."""
    z = zipfile.ZipFile(zip_path)
    contadores = {"vinculos_lidos": 0, "vinculos_medico": 0, "pares": 0,
                  "estabelecimentos": 0, "sem_estabelecimento": 0}

    logger.info("lendo municípios")
    municipios: dict[str, tuple[str, str]] = {}
    r = _abrir_csv(z, _nome_na_zip(z, "tbMunicipio"))
    h = next(r)
    i_co, i_no, i_uf = h.index("CO_MUNICIPIO"), h.index("NO_MUNICIPIO"), h.index("CO_SIGLA_ESTADO")
    for row in r:
        municipios[row[i_co][:6]] = (row[i_no], row[i_uf])

    logger.info("lendo vínculos")
    pares: set[tuple[str, str]] = set()
    r = _abrir_csv(z, _nome_na_zip(z, "tbCargaHorariaSus"))
    h = next(r)
    i_un, i_cbo = h.index("CO_UNIDADE"), h.index("CO_CBO")
    i_reg, i_uf = h.index("NU_REGISTRO"), h.index("SG_UF_CRM")
    for row in r:
        contadores["vinculos_lidos"] += 1
        if not row[i_cbo].startswith(PREFIXOS_CBO_MEDICO):
            continue
        contadores["vinculos_medico"] += 1
        chave = _ufcrm(row[i_uf], row[i_reg])
        if chave:
            pares.add((chave, row[i_un]))
    contadores["pares"] = len(pares)
    unidades = {u for _, u in pares}

    logger.info("lendo estabelecimentos (%d procurados)", len(unidades))
    estab: dict[str, dict] = {}
    r = _abrir_csv(z, _nome_na_zip(z, "tbEstabelecimento"))
    h = next(r)
    campos = {c: h.index(c) for c in (
        "CO_UNIDADE", "CO_CNES", "NO_FANTASIA", "NO_RAZAO_SOCIAL", "TP_UNIDADE",
        "NO_LOGRADOURO", "NU_ENDERECO", "NO_COMPLEMENTO", "NO_BAIRRO", "CO_CEP",
        "CO_MUNICIPIO_GESTOR", "NU_TELEFONE", "NU_LATITUDE", "NU_LONGITUDE",
    )}
    for row in r:
        un = row[campos["CO_UNIDADE"]]
        if un in unidades:
            estab[un] = {c: row[i].strip() for c, i in campos.items()}
    contadores["estabelecimentos"] = len(estab)

    logger.info("escrevendo %s", saida)
    with saida.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUNAS_SAIDA)
        for ufcrm, un in sorted(pares):
            e = estab.get(un)
            if not e:
                contadores["sem_estabelecimento"] += 1
                continue
            nome_mun, uf_mun = municipios.get(e["CO_MUNICIPIO_GESTOR"][:6], ("", ""))
            w.writerow([
                ufcrm, e["CO_CNES"], e["NO_FANTASIA"], e["NO_RAZAO_SOCIAL"], e["TP_UNIDADE"],
                e["NO_LOGRADOURO"], e["NU_ENDERECO"], e["NO_COMPLEMENTO"], e["NO_BAIRRO"],
                _cep8(e["CO_CEP"]) or "",
                e["CO_MUNICIPIO_GESTOR"][:6], nome_mun, uf_mun,
                e["NU_TELEFONE"], e["NU_LATITUDE"], e["NU_LONGITUDE"],
                competencia,
            ])
    return contadores


def _databricks(*args: str, perfil: str) -> str:
    cmd = ["databricks", "--profile", perfil, *args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:4])} falhou: {r.stderr.strip()[:400]}")
    return r.stdout


def _sql(statement: str, perfil: str, warehouse: str) -> dict:
    body = json.dumps({"warehouse_id": warehouse, "wait_timeout": "50s", "statement": statement})
    out = json.loads(_databricks("api", "post", "/api/2.0/sql/statements", "--json", body, perfil=perfil))
    estado = out.get("status", {}).get("state")
    if estado != "SUCCEEDED":
        raise RuntimeError(f"SQL falhou: {json.dumps(out.get('status'))[:400]}")
    return out


def publicar(csv_local: Path, competencia: str, perfil: str, warehouse: str) -> None:
    """Sobe o CSV para o volume e recria a tabela a partir dele."""
    destino = f"{VOLUME}/tb_cnes_local_atendimento_{competencia}.csv"
    logger.info("enviando para %s", destino)
    _databricks("fs", "mkdir", VOLUME, perfil=perfil)
    _databricks("fs", "cp", "--overwrite", str(csv_local), destino, perfil=perfil)

    caminho_sql = destino.replace("dbfs:", "")
    logger.info("recriando %s", TABELA)
    _sql(f"""
        CREATE OR REPLACE TABLE {TABELA} AS
        SELECT
            ufcrm, co_cnes, nome_fantasia, razao_social, tipo_unidade,
            logradouro, numero, complemento, bairro, cep,
            co_municipio, municipio, uf, telefone,
            TRY_CAST(latitude AS DOUBLE) AS latitude,
            TRY_CAST(longitude AS DOUBLE) AS longitude,
            competencia
        FROM read_files(
            '{caminho_sql}',
            format => 'csv', header => true, inferSchema => false,
            multiLine => true, escape => '"'
        )
    """, perfil, warehouse)
    _sql(f"""
        COMMENT ON TABLE {TABELA} IS
        'Onde cada médico atende, pelo CRM, a partir da base mensal do CNES (DATASUS). Uma linha por médico e estabelecimento. Sem CPF nem CNS, por decisão de projeto. Carga por backend/scripts/carregar_cnes.py.'
    """, perfil, warehouse)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--zip", type=Path, help="ZIP já baixado. Sem ele, baixa do FTP.")
    p.add_argument("--competencia", help="AAAAMM. Obrigatório sem --zip; com --zip, inferido do nome.")
    p.add_argument("--perfil", default="ache")
    p.add_argument("--warehouse", default="e0bbf85808a7e35b")
    p.add_argument("--so-extrair", action="store_true", help="Gera o CSV e para, sem publicar.")
    p.add_argument("--saida", type=Path, help="Onde gravar o CSV. Padrão: temporário.")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if a.zip:
        zip_path = a.zip
        competencia = a.competencia or re.search(r"(\d{6})", zip_path.name).group(1)
    else:
        if not a.competencia:
            p.error("--competencia é obrigatório sem --zip")
        competencia = a.competencia
        zip_path = Path(tempfile.gettempdir()) / f"BASE_DE_DADOS_CNES_{competencia}.ZIP"
        logger.info("baixando %s", FTP.format(competencia=competencia))
        subprocess.run(["curl", "-s", "-m", "1800", "-o", str(zip_path),
                        FTP.format(competencia=competencia)], check=True)

    saida = a.saida or Path(tempfile.gettempdir()) / f"tb_cnes_local_atendimento_{competencia}.csv"
    contadores = extrair(zip_path, competencia, saida)
    logger.info("contadores: %s", json.dumps(contadores))

    if a.so_extrair:
        logger.info("CSV em %s", saida)
        return 0
    publicar(saida, competencia, a.perfil, a.warehouse)
    total = _sql(f"SELECT COUNT(*), COUNT(DISTINCT ufcrm) FROM {TABELA}", a.perfil, a.warehouse)
    linhas, medicos = total["result"]["data_array"][0]
    logger.info("publicado: %s linhas, %s médicos distintos em %s", linhas, medicos, TABELA)
    return 0


if __name__ == "__main__":
    sys.exit(main())
