"""Endereços do médico no card: o da visita e o "também atende em".

Desenho fechado por George em 18/09/2026, depois de comparar as três fontes
na mesma amostra de médicos:

- **Endereço 1, o da visita.** A correção do propagandista, quando existe,
  ganha de tudo: é ele quem foi lá. Senão SalesFarma, porque é onde ele
  agenda, 53,8% do painel. Senão a auditoria de prescrição, 99,2% mas com
  cidade agregada e endereço sem tipo de logradouro, e por isso com a
  etiqueta "confira antes da visita". A correção é registrada em
  `tb_endereco_medico`, só inserção, a mais recente por médico vale, e é o
  que vai sincronizar de volta ao SalesFarma quando a integração existir.
  George decidiu em 18/09/2026 que a carga do CNES é única e o propagandista
  mantém o endereço daí em diante.
- **Endereço 2, "também atende em".** O estabelecimento do CNES que faz mais
  sentido com o setor. O CNES registra vínculos institucionais, hospital,
  posto, UPA e consultório, e um médico tem de um a oito. Sem uma regra de
  escolha, o card mostraria o plantão dele em outra cidade.

A regra de escolha, testada em 16.417 pares médico e setor da amostra:

1. Estabelecimento na mesma área do endereço 1, CEP com os mesmos cinco
   primeiros dígitos. Resolveu 51,9%.
2. Senão, estabelecimento numa cidade do setor do propagandista. Mais 33,0%.
3. Senão, estabelecimento na cidade do endereço 1. Mais 0,3%.
4. Senão, sem endereço 2. Foram 14,8%, e é o caso certo de omitir: o vínculo
   está todo fora do setor e mostrá-lo confundiria.

O setor do propagandista é definido por cidades, `CIDADES_SETOR` em
`tb_propagandistas`, e não por bairros. É por isso que a regra 2 cruza cidade.

`divergente` marca quando os dois endereços apontam para cidades diferentes.
Não é erro de nenhuma fonte, o médico dá plantão num lugar e atende em outro,
mas um dos dois pode estar desatualizado e o propagandista precisa saber.

**O SalesFarma repete o mesmo endereço.** O texto é livre e cada setor grava
do seu jeito: "AVENIDA X 1699", "AVENIDA X 1699 SALA 106", "AV X 1699
ESQUINA CALÇADÃO", "RUA RUA X", "R CEL" e "RUA CORONEL", número "0". Medido
em 20/09/2026 no período mais recente de cada médico: 353.038 médicos com
endereço, 186.273 com mais de uma variante, até oito. George pediu em
20/09/2026 que o card mostre um só por lugar. A chave é a rua sem o tipo de
via e sem abreviação, mais o número; ver `chave_do_logradouro` e
`agrupar_salesfarma`. Endereço com número diferente continua separado, mesmo
que pareça erro de digitação, porque não dá para saber qual dos dois é o
certo.

Tudo aqui é função pura sobre dicionários, sem banco, para o teste não
precisar de mock de conexão.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Optional

FONTE_PROPAGANDISTA = "propagandista"
FONTE_SALESFARMA = "salesfarma"
FONTE_AUDITORIA = "auditoria"
FONTE_CNES = "cnes"


def normalizar(texto: Optional[str]) -> str:
    """Maiúsculas, sem acento, sem pontuação, espaços únicos. Para comparar
    cidade entre fontes que gravam "SÃO PAULO", "SAO PAULO" e "Sao Paulo"."""
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().upper()
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", t).split())


# Tipo de via no início do texto. Sai da chave porque "RUA X", "R X" e "X"
# são a mesma rua, e o SalesFarma grava as três formas, às vezes "RUA RUA X".
_TIPOS_DE_VIA = {
    "RUA", "R", "AV", "AVENIDA", "AL", "ALAMEDA", "TRAV", "TRAVESSA", "TV",
    "ESTR", "EST", "ESTRADA", "PCA", "PC", "PRACA", "ROD", "RODOVIA", "LARGO",
    "LGO", "VIA", "BECO", "VL", "VILA",
}

# Abreviações de título que aparecem no nome da rua. Só as que a amostra
# mostrou; a lista cresce quando um caso novo aparecer.
_ABREVIACOES = {
    "CEL": "CORONEL", "PROF": "PROFESSOR", "PROFA": "PROFESSORA", "DR": "DOUTOR",
    "DRA": "DOUTORA", "STA": "SANTA", "STO": "SANTO", "S": "SAO", "PE": "PADRE",
    "MAL": "MARECHAL", "BRIG": "BRIGADEIRO", "ENG": "ENGENHEIRO",
    "DES": "DESEMBARGADOR", "PRES": "PRESIDENTE", "GOV": "GOVERNADOR",
    "SEN": "SENADOR", "DEP": "DEPUTADO", "MIN": "MINISTRO", "ALM": "ALMIRANTE",
    "GAL": "GENERAL", "GEN": "GENERAL", "CAP": "CAPITAO", "SGT": "SARGENTO",
    "VER": "VEREADOR", "TEN": "TENENTE", "MAJ": "MAJOR", "CMTE": "COMANDANTE",
}


def decompor_logradouro(texto: Optional[str]) -> tuple[str, Optional[str], Optional[str]]:
    """(rua, número, complemento) a partir do texto livre do SalesFarma.

    O número é o primeiro token só de dígitos depois do nome da rua. O que
    vem antes é a rua, o que vem depois é complemento (sala, referência, nome
    da clínica). Mantém o texto original, só tira vírgula: é o que a tela
    mostra. "0" e "00" viram sem número, que é o que significam.
    """
    bruto = " ".join((texto or "").replace(",", " ").split())
    tokens = bruto.split()
    idx = next((i for i, t in enumerate(tokens) if t.isdigit() and i > 0), None)
    if idx is None:
        return bruto, None, None
    numero = tokens[idx].lstrip("0") or None
    complemento = " ".join(tokens[idx + 1:]) or None
    return " ".join(tokens[:idx]), numero, complemento


def rua_para_exibir(rua: str) -> str:
    """Tira o que é ruído de digitação no começo: "RUA RUA X" vira "RUA X",
    "10ª RUA X" vira "RUA X", "RUA R CEL X" vira "R CEL X". Não expande
    abreviação nem tira acento: o texto exibido é o do cadastro."""
    tokens = rua.split()
    while len(tokens) > 1:
        a, b = normalizar(tokens[0]), normalizar(tokens[1])
        if (a in _TIPOS_DE_VIA and b in _TIPOS_DE_VIA) or (re.fullmatch(r"\d+[A-Z]*", a) and b in _TIPOS_DE_VIA):
            tokens.pop(0)
            continue
        break
    return " ".join(tokens)


def chave_do_logradouro(texto: Optional[str]) -> tuple[str, Optional[str]]:
    """Chave de agrupamento: rua normalizada sem tipo de via nem abreviação,
    mais o número. "RUA CORONEL FONTE BOA 186 HOSPITAL", "R CEL FONTE BOA 186"
    e "RUA R CEL FONTE BOA 186 PIO XII" dão a mesma chave."""
    rua, numero, _ = decompor_logradouro(texto)
    tokens = normalizar(rua).split()
    # "10A RUA RUA MARQUES": ordinal solto antes do tipo de via também sai.
    while tokens and (tokens[0] in _TIPOS_DE_VIA or (re.fullmatch(r"\d+[A-Z]*", tokens[0]) and len(tokens) > 1 and tokens[1] in _TIPOS_DE_VIA)):
        tokens.pop(0)
    tokens = [_ABREVIACOES.get(t, t) for t in tokens]
    return " ".join(tokens), numero


def cep8(valor: Optional[str]) -> Optional[str]:
    """Os oito últimos dígitos. A auditoria grava o CEP com zeros à esquerda,
    dez dígitos em vez de oito."""
    d = re.sub(r"\D", "", valor or "")
    return d[-8:] if len(d) >= 8 else None


def cidades_da_auditoria(texto: Optional[str]) -> set[str]:
    """"BETIM-MG + IGARAPE-MG" vira {"BETIM", "IGARAPE"}; "MARISTELA (LARANJAL
    PAULISTA)-SP + OUTRAS" vira {"MARISTELA", "LARANJAL PAULISTA"}.

    A auditoria agrega cidades vizinhas no mesmo campo, com a UF colada e
    às vezes um "+ OUTRAS". É recorte geográfico dela, não endereço."""
    saida: set[str] = set()
    # Separa no texto cru: a normalização apagaria justamente os separadores.
    for parte in (texto or "").split("+"):
        parte = re.sub(r"-\s*[A-Za-z]{2}\s*$", "", parte.strip())  # tira o "-MG" do fim
        for pedaco in re.split(r"[()]", parte):
            pedaco = normalizar(pedaco)
            if pedaco and pedaco != "OUTRAS":
                saida.add(pedaco)
    return saida


def cidade_limpa(texto: Optional[str]) -> str:
    """Tira o "-RS" do fim e normaliza. O SalesFarma também grava assim em
    parte dos registros, "PELOTAS-RS"; sem isso, SalesFarma e CNES no mesmo
    prédio apareciam como cidades diferentes. Achado na prova real de
    18/09/2026 com RS0025000."""
    return normalizar(re.sub(r"-\s*[A-Za-z]{2}\s*$", "", (texto or "").strip()))


def cidades_do_setor(texto: Optional[str]) -> set[str]:
    """`CIDADES_SETOR` vem separado por vírgula."""
    return {normalizar(c) for c in (texto or "").split(",") if normalizar(c)}


@dataclass
class Endereco:
    fonte: str
    local: Optional[str] = None
    logradouro: Optional[str] = None
    numero: Optional[str] = None
    complemento: Optional[str] = None
    bairro: Optional[str] = None
    cidade: Optional[str] = None
    uf: Optional[str] = None
    cep: Optional[str] = None
    telefone: Optional[str] = None
    # Só a correção do propagandista preenche: quem e quando.
    registrado_por: Optional[str] = None
    registrado_em: Optional[str] = None
    # Só a auditoria preenche: as cidades agregadas, para a comparação.
    cidades_possiveis: set[str] = field(default_factory=set, repr=False)

    @property
    def cep5(self) -> Optional[str]:
        c = cep8(self.cep)
        return c[:5] if c else None

    @property
    def cidades(self) -> set[str]:
        if self.cidades_possiveis:
            return self.cidades_possiveis
        return {cidade_limpa(self.cidade)} if self.cidade else set()

    def para_resposta(self) -> dict:
        """Os campos que saem na API. `cidades_possiveis` é só de comparação."""
        return {
            "fonte": self.fonte, "local": self.local, "logradouro": self.logradouro,
            "numero": self.numero, "complemento": self.complemento, "bairro": self.bairro,
            "cidade": self.cidade, "uf": self.uf, "cep": self.cep, "telefone": self.telefone,
            "registrado_por": self.registrado_por, "registrado_em": self.registrado_em,
        }


def endereco_da_visita(
    salesfarma: Iterable[dict],
    auditoria: Optional[dict],
    corrigido: Optional[dict] = None,
) -> list[Endereco]:
    """Endereço 1. A correção do propagandista; senão todos os do SalesFarma;
    senão o único da auditoria."""
    if corrigido and (corrigido.get("logradouro") or "").strip():
        return [
            Endereco(
                fonte=FONTE_PROPAGANDISTA,
                logradouro=corrigido.get("logradouro") or None,
                numero=(corrigido.get("numero") or "").strip() or None,
                complemento=(corrigido.get("complemento") or "").strip() or None,
                bairro=corrigido.get("bairro") or None,
                cidade=corrigido.get("cidade") or None,
                uf=corrigido.get("uf") or None,
                cep=cep8(corrigido.get("cep")),
                registrado_por=corrigido.get("registrado_por") or None,
                registrado_em=str(corrigido["registrado_em"]) if corrigido.get("registrado_em") else None,
            )
        ]
    lista = agrupar_salesfarma(
        [
            Endereco(
                fonte=FONTE_SALESFARMA,
                local=r.get("local") or None,
                logradouro=r.get("logradouro") or None,
                bairro=r.get("bairro") or None,
                cidade=r.get("cidade") or None,
                uf=r.get("uf") or None,
                cep=cep8(r.get("cep")),
            )
            for r in salesfarma
            if (r.get("logradouro") or "").strip()
        ]
    )
    if lista:
        return lista
    if auditoria and (auditoria.get("logradouro") or "").strip():
        return [
            Endereco(
                fonte=FONTE_AUDITORIA,
                logradouro=auditoria.get("logradouro") or None,
                cidade=auditoria.get("cidade") or None,
                uf=auditoria.get("uf") or None,
                cep=cep8(auditoria.get("cep")),
                cidades_possiveis=cidades_da_auditoria(auditoria.get("cidade")),
            )
        ]
    return []


def agrupar_salesfarma(lista: list[Endereco]) -> list[Endereco]:
    """Um endereço por rua e número, na ordem em que apareceram.

    O representante do grupo é a variante mais limpa: sem complemento, com
    o tipo de via, e a mais curta. O CEP é o mais repetido no grupo, porque
    a mesma rua aparece com dois CEPs e o que se repete mais tem mais chance
    de ser o certo. Rua e número saem separados em `logradouro` e `numero`,
    como a correção do propagandista já faz, para o card e o formulário
    tratarem as duas fontes do mesmo jeito.
    """
    grupos: dict[tuple[str, Optional[str]], list[Endereco]] = {}
    for e in lista:
        grupos.setdefault(chave_do_logradouro(e.logradouro), []).append(e)

    def limpeza(e: Endereco) -> tuple[int, int, int]:
        rua, _, complemento = decompor_logradouro(e.logradouro)
        primeiro = normalizar(rua).split()[:1]
        return (
            1 if complemento else 0,
            0 if primeiro and primeiro[0] in _TIPOS_DE_VIA else 1,
            len(e.logradouro or ""),
        )

    resultado = []
    for membros in grupos.values():
        base = min(membros, key=limpeza)
        rua, numero, complemento = decompor_logradouro(base.logradouro)
        ceps = Counter(m.cep for m in membros if m.cep)
        resultado.append(
            Endereco(
                fonte=base.fonte,
                local=base.local,
                logradouro=rua_para_exibir(rua) if rua else base.logradouro,
                numero=numero,
                complemento=complemento,
                bairro=base.bairro,
                cidade=base.cidade,
                uf=base.uf,
                cep=ceps.most_common(1)[0][0] if ceps else base.cep,
            )
        )
    return resultado


def escolher_local_cnes(
    locais_cnes: Iterable[dict],
    endereco_visita: list[Endereco],
    cidades_setor: set[str],
) -> Optional[Endereco]:
    """Endereço 2, pela regra do módulo. `None` quando nenhuma regra casa."""
    candidatos = [
        Endereco(
            fonte=FONTE_CNES,
            local=r.get("nome_fantasia") or r.get("razao_social") or None,
            logradouro=r.get("logradouro") or None,
            numero=(r.get("numero") or "").strip() or None,
            complemento=(r.get("complemento") or "").strip() or None,
            bairro=r.get("bairro") or None,
            cidade=r.get("municipio") or None,
            uf=r.get("uf") or None,
            cep=cep8(r.get("cep")),
            telefone=(r.get("telefone") or "").strip() or None,
        )
        for r in locais_cnes
        if (r.get("logradouro") or "").strip()
    ]
    if not candidatos:
        return None

    cep5_ref = {e.cep5 for e in endereco_visita if e.cep5}
    cidades_ref: set[str] = set()
    for e in endereco_visita:
        cidades_ref |= e.cidades

    # 1. mesma área do endereço 1
    for c in candidatos:
        if c.cep5 and c.cep5 in cep5_ref:
            return c
    # 2. cidade do setor
    for c in candidatos:
        if c.cidade and cidade_limpa(c.cidade) in cidades_setor:
            return c
    # 3. cidade do endereço 1
    for c in candidatos:
        if c.cidade and cidade_limpa(c.cidade) in cidades_ref:
            return c
    return None


def divergem(endereco_visita: list[Endereco], local_cnes: Optional[Endereco]) -> bool:
    """Verdadeiro quando existe endereço 1 e endereço 2 e nenhuma cidade coincide."""
    if not endereco_visita or local_cnes is None or not local_cnes.cidade:
        return False
    cidades_ref: set[str] = set()
    for e in endereco_visita:
        cidades_ref |= e.cidades
    return bool(cidades_ref) and cidade_limpa(local_cnes.cidade) not in cidades_ref
