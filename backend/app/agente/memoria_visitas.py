"""A Memória de Visitas: o que os comentários de campo dizem sobre o médico.

Substitui o bloco "Como Tratar" do perfil. Duas camadas, com naturezas
diferentes de propósito:

1. **A última visita, crua.** Data, tipo e o comentário como o propagandista
   escreveu. Não passa por modelo, não falha e é a resposta ao pedido de
   produto de 02/09/2026: "sempre priorizar os últimos; se puder falar 'na
   última visita foi isso'".

2. **O resumo estruturado**, gerado por uma chamada de modelo sobre as
   últimas observações, nas dimensões da proposta de captura da Aché
   (Voz do Médico, Momento Clínico) mais o Toque Pessoal, que é decisão de
   produto deste projeto. E a classificação do momento da relação
   (primeira_visita, conquista, defensor, risco_de_perda, indefinido), que
   atende ao Estado da Relação da proposta e ao insumo de perfil do motor de
   abordagem de uma vez.

Regras de honestidade, na ordem em que importam:

- `primeira_visita` é determinística: zero observações efetivas dispensa
  modelo e não tem o que resumir.
- O modelo só pode citar o que está nas observações fornecidas, com a data
  de origem em cada item. Dimensão sem evidência volta vazia, nunca
  preenchida por plausibilidade.
- Classificação fora do vocabulário vira `indefinido`. O campo é sempre
  apresentado como automático; a palavra final é do propagandista.
- Falha de modelo ou de consulta degrada para a camada 1, nunca para erro.

O cache em processo existe porque a estruturação custa uma chamada de modelo
e o mesmo perfil é aberto várias vezes no dia. Uma hora de validade equilibra
custo e frescor: observação nova aparece, no pior caso, na hora seguinte.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from backend.app.db.sql_dialect import formatar_data_sql

logger = logging.getLogger(__name__)

QUANTAS_OBSERVACOES = 8
TTL_CACHE_SEGUNDOS = 60 * 60
# Falha de modelo entra no cache por pouco tempo: o suficiente para uma
# indisponibilidade não cobrar uma chamada perdida a cada abertura do perfil,
# e curto o bastante para a recuperação aparecer em minutos. Achado da
# revisão independente de 03/09/2026.
TTL_FALHA_SEGUNDOS = 120
MAX_CACHE = 2000

MOMENTOS = ("primeira_visita", "conquista", "defensor", "risco_de_perda", "indefinido")
# O modelo não pode devolver primeira_visita: essa classificação é
# determinística (zero observações) e aceitar a versão do modelo com
# observações presentes seria contradição. Achado da revisão de 03/09/2026.
MOMENTOS_DO_MODELO = ("conquista", "defensor", "risco_de_perda", "indefinido")


class ItemDeVisita(BaseModel):
    data: str = ""
    texto: str


class MomentoDaRelacao(BaseModel):
    classificacao: str = "indefinido"
    justificativa: str = ""


class UltimaVisita(BaseModel):
    data: str = ""
    tipo: str = ""
    comentario: str = ""


class MemoriaDeVisitas(BaseModel):
    disponivel: bool = False
    ultima: Optional[UltimaVisita] = None
    momento_da_relacao: Optional[MomentoDaRelacao] = None
    voz_do_medico: list[ItemDeVisita] = []
    momento_clinico: list[ItemDeVisita] = []
    toque_pessoal: list[ItemDeVisita] = []
    # True quando o resumo estruturado não pôde ser gerado e só a camada crua
    # está presente. A tela decide o que mostrar; o backend nunca esconde.
    somente_crua: bool = False


_trava = threading.Lock()
_cache: dict[str, tuple[float, float, MemoriaDeVisitas]] = {}  # (gravado_em, ttl, memoria)
_travas_por_chave: dict[str, threading.Lock] = {}


@contextmanager
def _secao_da_chave(chave: str):
    """Seção crítica por médico, contra o efeito manada.

    A aquisição reconfere o registro depois de obter a trava, o mesmo padrão
    já revisado da memória de conversa: a contenção pode remover uma trava
    livre entre a devolução e o acquire, e sem a reconferência duas
    requisições da mesma chave seguiriam juntas, cada uma com um objeto.
    Registro contido pelo invariante de travas livres acima do teto; trava em
    uso nunca cai. Achados da revisão de 03/09/2026.
    """
    while True:
        with _trava:
            if len(_travas_por_chave) > MAX_CACHE:
                for k in [k for k, tr in _travas_por_chave.items()
                          if k != chave and not tr.locked()]:
                    if len(_travas_por_chave) <= MAX_CACHE:
                        break
                    del _travas_por_chave[k]
            tr = _travas_por_chave.setdefault(chave, threading.Lock())
        tr.acquire()
        with _trava:
            if _travas_por_chave.get(chave) is tr:
                break
        tr.release()
    try:
        yield
    finally:
        tr.release()


INSTRUCAO_CLASSIFICADOR = """Você organiza as observações de visitas de um \
propagandista farmacêutico sobre um médico. Responda SOMENTE um objeto JSON, \
sem markdown e sem texto fora dele, no formato:

{"momento_da_relacao": {"classificacao": "...", "justificativa": "..."},
 "voz_do_medico": [{"data": "dd/mm/aaaa", "texto": "..."}],
 "momento_clinico": [{"data": "dd/mm/aaaa", "texto": "..."}],
 "toque_pessoal": [{"data": "dd/mm/aaaa", "texto": "..."}]}

REGRAS SEM EXCEÇÃO:
1. Use apenas o que está nas observações fornecidas. Não complete com
   suposição. Dimensão sem evidência volta como lista vazia.
2. Cada item cita a data da observação de origem e resume em uma frase curta.
   Priorize as observações mais recentes; no máximo 3 itens por dimensão.
3. voz_do_medico: o que o médico disse, pediu, objetou; concorrente citado;
   dúvida clínica; menção a diretriz ou congresso.
4. momento_clinico: perfil de pacientes, satisfação com tratamento, adesão,
   falha de tratamento, abertura a mudança de conduta.
5. toque_pessoal: fato pessoal que ajude o relacionamento (saúde, família,
   interesse). Formule como lembrança útil, por exemplo "comentou que estava
   se recuperando de cirurgia; vale perguntar como está".
6. momento_da_relacao.classificacao é exatamente um destes valores:
   "conquista" (ainda não adotou; em construção), "defensor" (adotou e
   sustenta; relação madura), "risco_de_perda" (sinal de afastamento, troca
   por concorrente, recusa ou queda de receptividade), "indefinido" (as
   observações não sustentam nenhuma). A justificativa cita as evidências
   com data. Na dúvida, "indefinido".
7. Escreva em português do Brasil, tom de colega de campo."""


def _chave(setor: str, ufcrm: str) -> str:
    return f"{(setor or '').strip()}|{ufcrm}"


def _do_cache(chave: str) -> Optional[MemoriaDeVisitas]:
    agora = time.time()
    with _trava:
        item = _cache.get(chave)
        if not item:
            return None
        gravado_em, ttl, memoria = item
        if agora - gravado_em > ttl:
            del _cache[chave]
            return None
        return memoria


def _guardar(chave: str, memoria: MemoriaDeVisitas,
             ttl: float = TTL_CACHE_SEGUNDOS) -> None:
    with _trava:
        _cache[chave] = (time.time(), ttl, memoria)
        while len(_cache) > MAX_CACHE:
            mais_antiga = min(_cache, key=lambda k: _cache[k][0])
            del _cache[mais_antiga]


def _buscar_observacoes(executor, setor: str, ufcrm: str) -> list[dict[str, Any]]:
    """As últimas observações de visita efetiva do médico naquele setor.

    **Lê `vw_visitacao_comentarios`, e não a tabela de origem.** O service
    principal do portal não tem `USE CATALOG` em `dmn_produtividade_dev`:
    medido em 04/09/2026 autenticando com `oauth_service_principal`, ele não é
    membro de nenhum grupo `user-renovai-*` e a leitura direta falha com
    `INSUFFICIENT_PERMISSIONS`. Era isso que derrubava a Memória em
    homologação, com a seção sumindo em silêncio.

    A view mora em `acheinfo_dev.renovai`, tem o grupo
    `user-renovai-engineering` como dono e já filtra `VISITA_EFETIVA = 'S'`,
    por isso o filtro não aparece aqui. View do Unity Catalog roda com a
    permissão do dono, então o service principal lê por ela o que não lê
    direto. Mesmo mecanismo já usado por `vw_gold_auditpharma` e
    `vw_segmentacao_efetiva`.

    **É contorno, não solução.** Quando o service principal entrar no grupo de
    engenharia, pedido do Orlando ao Flávio em 04/09/2026, a leitura pode
    voltar a ser direta e a view deixa de ser necessária.
    """
    return executor.query(
        """
        SELECT {data_visita} AS DATA_VISITA,
               v.VISITA_TIPO, v.COMENTARIOS
        FROM vw_visitacao_comentarios AS v
        WHERE v.SETOR = :setor AND v.UFCRM = :ufcrm
        ORDER BY v.DATA_VISITA DESC
        LIMIT {limite}
        """.format(
            data_visita=formatar_data_sql("v.DATA_VISITA"),
            limite=QUANTAS_OBSERVACOES,
        ),
        {"setor": setor, "ufcrm": ufcrm},
    )


def _extrair_json(texto: str) -> Optional[dict]:
    """O modelo às vezes embrulha o JSON em cerca de código. Tira e parseia."""
    bruto = (texto or "").strip()
    bruto = re.sub(r"^```(?:json)?\s*|\s*```$", "", bruto)
    inicio, fim = bruto.find("{"), bruto.rfind("}")
    if inicio < 0 or fim <= inicio:
        return None
    try:
        dado = json.loads(bruto[inicio:fim + 1])
    except ValueError:
        return None
    return dado if isinstance(dado, dict) else None


def _chave_de_data(data: str) -> tuple:
    """"dd/mm/aaaa" em tupla ordenável (aaaa, mm, dd). Só data de calendário
    real, com dez caracteres, conta como data: "99/99/2026" ou "14/08/26"
    ordenam por último, junto com a ausente, e a ordem do modelo desempata."""
    if len(data) != 10:
        return (0,)
    try:
        d = datetime.strptime(data, "%d/%m/%Y")
    except ValueError:
        return (0,)
    return (1, d.year, d.month, d.day)


def _itens(bruto: Any) -> list[ItemDeVisita]:
    """Só lista de objetos com texto vira item. Qualquer outra forma que o
    modelo invente (string solta, número, objeto único) é descartada em
    silêncio: JSON válido com estrutura errada derrubava a rota com 500.
    Achado da revisão independente de 03/09/2026.

    A saída volta ordenada da mais recente para a mais antiga, mesmo que o
    modelo entregue fora de ordem: quem corta em "só o primeiro item", como o
    card resumido do Ranking, depende de o primeiro ser o mais novo. Achado da
    mesma revisão."""
    if not isinstance(bruto, list):
        return []
    itens: list[ItemDeVisita] = []
    for item in bruto:
        if not isinstance(item, dict):
            continue
        texto = item.get("texto")
        if not isinstance(texto, str) or not texto.strip():
            continue
        data = item.get("data")
        itens.append(ItemDeVisita(
            data=data.strip() if isinstance(data, str) else "",
            texto=texto.strip(),
        ))
    itens.sort(key=lambda i: _chave_de_data(i.data), reverse=True)
    return itens[:3]


def _estruturar(modelo, observacoes: list[dict[str, Any]]) -> Optional[dict]:
    corpo = "\n\n".join(
        f"[{o.get('DATA_VISITA', '')} | {o.get('VISITA_TIPO', '')}] {o.get('COMENTARIOS', '')}"
        for o in observacoes
    )
    volta = modelo.conversar(
        [{"role": "system", "content": INSTRUCAO_CLASSIFICADOR},
         {"role": "user", "content": f"Observações, da mais recente para a mais antiga:\n\n{corpo}"}],
        [],
    )
    msg = volta.mensagem if hasattr(volta, "mensagem") else volta
    conteudo = msg.get("content") if isinstance(msg, dict) else ""
    if isinstance(conteudo, list):
        conteudo = "\n".join(b.get("text", "") for b in conteudo
                             if isinstance(b, dict) and b.get("type") == "text")
    return _extrair_json(conteudo or "")


def montar(executor, modelo, setor: str, ufcrm: str) -> MemoriaDeVisitas:
    """A Memória de Visitas do médico, com cache e degradação."""
    ufcrm = (ufcrm or "").strip().upper()
    chave = _chave(setor, ufcrm)
    em_cache = _do_cache(chave)
    if em_cache is not None:
        return em_cache

    with _secao_da_chave(chave):
        # reconferência: quem esperou a trava pode encontrar o resultado de
        # quem chegou primeiro, sem pagar a segunda chamada de modelo
        em_cache = _do_cache(chave)
        if em_cache is not None:
            return em_cache
        return _montar_sem_cache(executor, modelo, setor, ufcrm, chave)


def _montar_sem_cache(executor, modelo, setor: str, ufcrm: str,
                      chave: str) -> MemoriaDeVisitas:
    try:
        observacoes = _buscar_observacoes(executor, setor, ufcrm)
    except Exception:  # noqa: BLE001
        # sem grant ou fonte fora do ar: a seção simplesmente não aparece
        logger.warning("memoria de visitas indisponivel para consulta", exc_info=True)
        return MemoriaDeVisitas(disponivel=False)

    if not observacoes:
        memoria = MemoriaDeVisitas(
            disponivel=True,
            momento_da_relacao=MomentoDaRelacao(
                classificacao="primeira_visita",
                justificativa="Sem visita efetiva registrada para este médico no seu setor.",
            ),
            somente_crua=True,
        )
        _guardar(chave, memoria)
        return memoria

    topo = observacoes[0]
    ultima = UltimaVisita(
        data=str(topo.get("DATA_VISITA") or ""),
        tipo=str(topo.get("VISITA_TIPO") or ""),
        comentario=str(topo.get("COMENTARIOS") or ""),
    )

    try:
        estruturado = _estruturar(modelo, observacoes)
    except Exception:  # noqa: BLE001
        logger.warning("estruturacao da memoria de visitas falhou", exc_info=True)
        estruturado = None

    if not estruturado:
        # Falha de modelo entra no cache com validade curta: durante uma
        # indisponibilidade, cada abertura do perfil não paga uma chamada
        # perdida de 30 segundos.
        memoria = MemoriaDeVisitas(disponivel=True, ultima=ultima, somente_crua=True)
        _guardar(chave, memoria, ttl=TTL_FALHA_SEGUNDOS)
        return memoria

    try:
        momento_bruto = estruturado.get("momento_da_relacao")
        if not isinstance(momento_bruto, dict):
            momento_bruto = {}
        classificacao = momento_bruto.get("classificacao")
        classificacao = classificacao.strip().lower() if isinstance(classificacao, str) else ""
        if classificacao not in MOMENTOS_DO_MODELO:
            # inclui o modelo tentando devolver primeira_visita com
            # observações presentes: a determinística não é dele
            classificacao = "indefinido"
        justificativa = momento_bruto.get("justificativa")
        memoria = MemoriaDeVisitas(
            disponivel=True,
            ultima=ultima,
            momento_da_relacao=MomentoDaRelacao(
                classificacao=classificacao,
                justificativa=justificativa.strip() if isinstance(justificativa, str) else "",
            ),
            voz_do_medico=_itens(estruturado.get("voz_do_medico")),
            momento_clinico=_itens(estruturado.get("momento_clinico")),
            toque_pessoal=_itens(estruturado.get("toque_pessoal")),
        )
    except Exception:  # noqa: BLE001
        # JSON válido com estrutura fora do previsto: degrada como falha
        logger.warning("estrutura inesperada na memoria de visitas", exc_info=True)
        memoria = MemoriaDeVisitas(disponivel=True, ultima=ultima, somente_crua=True)
        _guardar(chave, memoria, ttl=TTL_FALHA_SEGUNDOS)
        return memoria
    _guardar(chave, memoria)
    return memoria


def esquecer(setor: str, ufcrm: str) -> None:
    with _trava:
        _cache.pop(_chave(setor, (ufcrm or "").strip().upper()), None)
