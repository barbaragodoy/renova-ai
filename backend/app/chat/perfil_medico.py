"""Perfil do médico por setor, em cards, sem LLM.

Este módulo entrega a resposta que o Portal RenovAI mostra ao propagandista.
Ele substituiu o fluxo por etapas `/insight-medico`, encerrado em 10/08/2026,
por três motivos.

Primeiro, a fonte mudou. Todo o texto da resposta sai de uma consulta a
`acheinfo_dev.renovai.tb_perfil_medico_setor`, que materializa por SETOR e
UFCRM o que o briefing anterior calculava em tempo de consulta com um SQL de
oito mil caracteres. O SQL daqui tem pouco mais de mil.

Segundo, o formato mudou. A saída não é texto, é o contrato `Message` do
protótipo do Figma Make: uma frase curta mais uma lista de cards tipados. O
texto narrativo continua existindo, mas como conteúdo sob demanda dos chips de
sugestão, no campo `respostas`. Isso resolve de uma vez a exigência registrada
nas entrevistas, de que a resposta precisa ser pequena, e o pedido de Jonas
Buriti em 30/07/2026, de poder conferir a origem do que foi afirmado.

Terceiro, e mais importante, aqui não entra LLM. A medição de 09/08/2026, com
seis casos e três repetições em sete modelos, deu 18 de 18 respostas limpas e
6 de 6 casos idênticos para o formatador determinístico, contra no máximo 16 de
18 e nenhuma estabilidade no melhor modelo. Narrativa de LLM não é homologável:
o mesmo médico produzia texto diferente a cada execução. O LLM continua útil na
cauda, para pergunta que o roteador não reconhece, e isso é decidido em
`rotear()`, não aqui.

Nada neste módulo consulta serviço externo. Dado o dicionário devolvido pela
consulta, a resposta é uma função pura.
"""

from __future__ import annotations

import json as _json
import logging
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor as _ThreadPoolExecutor
from datetime import date as _date
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("renovai")

# --------------------------------------------------------------------------- #
# Roteador determinístico de intenção
# --------------------------------------------------------------------------- #

_SETOR = re.compile(r"\b(\d{12})\b")
_UFCRM = re.compile(r"\b([A-Za-z]{2}\d{7})\b")
_CRMNUM = re.compile(r"\b(\d{4,7})\b")
# Nome próprio em caixa alta, como vem da tabela, ou capitalizado, como o
# propagandista digita. A versão anterior só reconhecia caixa alta e perdia
# "Zurisaday Basabe Garcia" digitado normalmente.
_PALAVRA_NOME = r"(?:[A-ZÁÂÃÉÊÍÓÔÕÚÇ][A-ZÁÂÃÉÊÍÓÔÕÚÇ]+|[A-ZÁÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúùûüç]+)"
_NOME = re.compile(rf"\b({_PALAVRA_NOME}(?:\s+(?:{_PALAVRA_NOME}|d[aeo]s?|e))*\s+{_PALAVRA_NOME})\b")

# Palavras que começam frase e seriam confundidas com nome próprio.
_NAO_E_NOME = {
    "quais", "quantos", "quem", "como", "onde", "qual", "me", "o", "a", "os", "as",
    "medico", "medica", "doutor", "doutora", "setor", "perfil", "brief", "briefing",
    "produtos", "categorias", "resumo", "panorama", "sobre", "para", "por",
}

# Frase de visita. Entra como intenção própria porque é o que a aba Ranking
# gera ao tocar num médico: ela monta "Vou visitar FULANO" e troca de aba.
# Sem isto, a integração que o próprio portal criou caía em "essa pergunta eu
# ainda não sei responder sozinho", e o propagandista tinha que redigitar o
# nome. Reproduzido em 20/08/2026 com o print da tela.
_VISITA = re.compile(
    r"\b(vou visitar|vou ver|estou indo (?:ver|visitar)|indo visitar|"
    r"visita (?:a|ao|à|na|no)|tenho visita (?:com|no|na)|visitando)\b")

# A ordem importa: a primeira que casar vence. `briefing_medico` fica por
# último porque seus termos são os mais genéricos.
_INTENCOES: list[tuple[str, str]] = [
    ("inclusoes", r"\b(inclu\w*|adicionar|entrar no painel|quem colocar|novos medicos)\b"),
    ("exclusoes", r"\b(retirar|remover|excluir|tirar do painel|quem sai|quem tirar|exclu\w*)\b"),
    ("categorias", r"\b(categoria\w*|area\w* terapeutica\w*)\b"),
    ("produtos", r"\b(produto\w*|oferecer|portfolio|o que vender)\b"),
    ("resumo_setor", r"\b(como esta o setor|resumo do setor|visao do setor|panorama|meu setor|situacao do setor)\b"),
    ("briefing_medico", r"(\bbrief\w*|\bperfil d|\bcontexto d|\bsobre o medico|\bquem e o |\bme fala d|\bo que levar para)"),
]

# Termos que denunciam pergunta analítica. Sem esta lista, uma pergunta como
# "quantos médicos do setor X prescrevem antidepressivos" caía no atalho de
# resumo do setor e era respondida com confiança pela coisa errada. Errar para
# o lado de chamar o LLM é barato; errar para o lado de responder errado, não.
_CAUDA = re.compile(
    r"\b(quantos|quanta|compare|comparar|evolucao|tendencia|historico|ultimos meses|"
    r"crescimento|potencial|media|ranking geral|cidade|bairro|regiao|top \d|"
    r"maior|menor|mais de \d|menos de \d|entre \d|por que|porque|explique)\b"
)

# Saudação e cortesia são consumidas como PREFIXO da mensagem, palavra a
# palavra, antes de qualquer extração de identificador. Visto em teste de
# 02/09/2026: "Olá" virava busca por substring e encontrava PAOLA. Para a
# comparação, cada palavra é normalizada para só letras: "Olá!", aspas
# tipográficas e emoji caem na mesma entrada. Palavra com dígito nunca casa
# com o léxico e interrompe o consumo, então "oi 34827" preserva o CRM.
_SO_LETRAS = re.compile(r"[^a-z\s]+")

# Termos que também são palavra de nome real ficaram de fora, medido na
# vw_agente_medico em 02/09/2026 por palavra exata do nome: BELEZA 49
# médicos, PERFEITO 46, SALVE 24, LEGAL 10 e OPA 7, todos fora do léxico.
# Com zero ocorrências, e mantidos: VALEU, OK, BLZ, OIE e EAI (SHOW e OTIMO,
# também zerados, ficaram fora por não serem cortesia de abertura no Brasil).
# OI aparece em 12 nomes e OLA em 11,
# mas permanecem no léxico por decisão de produto: a mensagem que é só "oi" é
# cumprimento com probabilidade dominante, e quem procura esses médicos busca
# pelo nome completo. Cortesia que não estiver aqui desce para o agente, que
# tem o histórico.
_SAUDACOES = frozenset((
    "ola", "oi", "oie", "hey", "hello", "eai", "e ai",
    "bom dia", "boa tarde", "boa noite", "tudo bem", "tudo bom",
    "como vai", "td bem", "td bom",
    "obrigado", "obrigada", "muito obrigado", "muito obrigada",
    "valeu", "ok", "blz",
))

# Da mais longa para a mais curta, para "bom dia" vencer antes de "boa" e
# "oie" antes de "oi" na detecção de prefixo.
_SAUDACOES_POR_TAMANHO = [e.split() for e in sorted(_SAUDACOES, key=len, reverse=True)]


def _prefixo_de_saudacao(pergunta: str) -> tuple[int, bool]:
    """Índice de corte do cumprimento inicial, e se a mensagem inteira é.

    A comparação acontece palavra normalizada a palavra normalizada, com um
    mapa de volta para o token original, porque um token pode carregar mais
    de uma palavra: "oi,bom dia" tem "oi" e "bom" dentro do mesmo token, e a
    sexta rodada da revisão de 02/09/2026 mostrou a regressão de compará-lo
    inteiro. Três regras:

    - palavra de token com dígito nunca é consumível: "oi2" não é cumprimento
      e "34827" interrompe o consumo, preservando CRM, UFCRM e setor;
    - token sem letra e sem dígito é ruído puro (emoji, pontuação) e é
      atravessado; mensagem só de ruído conta como cumprimento, para "👋" e
      "..." ganharem boas-vindas em vez de uma ida ao agente;
    - se o consumo parar no meio de um token (típico de erro de digitação,
      "oi,paola"), nada é cortado e a mensagem segue o fluxo normal.
    """
    tokens = pergunta.split()
    palavras: list[tuple[str, int, bool]] = []  # (palavra, token, consumivel)
    for indice, token in enumerate(tokens):
        tem_digito = any(c.isdigit() for c in token)
        for palavra in _SO_LETRAS.sub(" ", _sem_acento(token)).split():
            palavras.append((palavra, indice, not tem_digito))
        if tem_digito and not _SO_LETRAS.sub(" ", _sem_acento(token)).split():
            palavras.append(("", indice, False))
    if not palavras:
        return (len(tokens), True) if tokens else (0, False)
    consumidas = 0
    while consumidas < len(palavras):
        avancou = False
        for partes in _SAUDACOES_POR_TAMANHO:
            fim = consumidas + len(partes)
            if (fim <= len(palavras)
                    and all(c for _, _, c in palavras[consumidas:fim])
                    and [w for w, _, _ in palavras[consumidas:fim]] == partes):
                consumidas = fim
                avancou = True
                break
        if not avancou:
            break
    if consumidas == 0:
        return 0, False
    if consumidas == len(palavras):
        return len(tokens), True
    corte = palavras[consumidas][1]
    ultimo_consumido = palavras[consumidas - 1][1]
    if corte == ultimo_consumido:
        # o consumo parou no meio de um token: não há corte limpo
        return 0, False
    return corte, False


_STOP = {
    "setor", "do", "da", "de", "no", "na", "o", "a", "os", "as", "e", "para",
    "medico", "dr", "dra", "crm", "codigo", "",
    # Advérbio de tempo e cortesia sobram na frase de visita e entrariam no
    # termo de busca: "vou ver a dra silva hoje" procurava por "silva hoje".
    "hoje", "agora", "amanha", "cedo", "tarde", "noite", "manha", "ainda",
    "depois", "antes", "logo", "ja", "por", "favor", "pfv", "obrigado", "obrigada",
}


def _sem_acento(texto: str) -> str:
    normalizado = unicodedata.normalize("NFD", texto.lower())
    limpo = "".join(c for c in normalizado if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", limpo).strip()


class Rota(BaseModel):
    intencao: Optional[str] = None
    setor: Optional[str] = None
    ufcrm: Optional[str] = None
    crm_numero: Optional[str] = None
    nome: Optional[str] = None
    # Termo livre para busca parcial: o que sobra depois de tirar frase de
    # visita, tratamento e identificador. Existe porque o propagandista digita
    # "loester" ou "vou visitar o Dr. Loester", e o `nome` só reconhece duas
    # palavras iniciadas em maiúscula.
    termo: Optional[str] = None
    motivo: str = ""


def rotear(pergunta: str) -> Rota:
    """Classifica a pergunta. `intencao=None` significa mandar para o LLM."""
    # O cumprimento é consumido ANTES de qualquer extração, e o resto volta
    # por recursão. Fazer depois deixava rastro em cada canto: "Oi Paola"
    # capitalizado virava nome "OI PAOLA", "oi bom dia paola" perdia o termo,
    # e a limpeza por conjunto apagava palavra repetida fora do prefixo.
    # Achados das revisões independentes de 02/09/2026. Mensagem que é só
    # cumprimento (uma ou encadeadas, com emoji e pontuação atravessados)
    # responde saudação; dígito no meio interrompe o consumo e preserva CRM,
    # UFCRM e setor.
    cortadas, tudo_saudacao = _prefixo_de_saudacao(pergunta)
    if tudo_saudacao:
        return Rota(intencao="saudacao", motivo="saudacao")
    if cortadas:
        return rotear(" ".join(pergunta.split()[cortadas:]))

    texto = _sem_acento(pergunta)

    achado = _SETOR.search(texto)
    setor = achado.group(1) if achado else None
    achado = _UFCRM.search(pergunta)
    ufcrm = achado.group(1).upper() if achado else None

    crm = None
    if not ufcrm:
        candidatos = _CRMNUM.findall(_SETOR.sub(" ", texto))
        crm = candidatos[0] if candidatos else None

    nome = None
    for candidato in _NOME.findall(pergunta):
        partes = candidato.split()
        if len(partes) < 2 or _SETOR.search(candidato) or _UFCRM.search(candidato):
            continue
        # Descarta início de frase que só parece nome, como "Quais medicos".
        if _sem_acento(partes[0]) in _NAO_E_NOME:
            continue
        nome = candidato.strip()
        break

    # O que sobra depois de tirar identificador, frase de visita e tratamento.
    # Vira termo de busca parcial quando não há nome de duas palavras.
    limpo = _VISITA.sub(" ", _UFCRM.sub(" ", _SETOR.sub(" ", texto)))
    if crm:
        limpo = re.sub(r"\b" + crm + r"\b", " ", limpo)
    if nome:
        limpo = limpo.replace(_sem_acento(nome), " ")
    sobra = [p for p in re.split(r"\W+", limpo) if p not in _STOP]

    termo = None
    if not (ufcrm or crm or nome) and 1 <= len(sobra) <= 3:
        # Uma a três palavras soltas que não são pergunta: trata como nome
        # parcial. "loester", "silva neiva", "dra carla". A busca é parcial e
        # devolve vazio quando não é nome, então o custo de errar aqui é uma
        # resposta de não encontrado, não uma resposta sobre a pessoa errada.
        if not any(p in _NAO_E_NOME for p in sobra):
            termo = " ".join(sobra)

    base = {"setor": setor, "ufcrm": ufcrm, "crm_numero": crm, "nome": nome, "termo": termo}

    if _CAUDA.search(texto):
        return Rota(**base, intencao=None, motivo="termo analitico")

    for intencao, padrao in _INTENCOES:
        if re.search(padrao, texto):
            return Rota(**base, intencao=intencao, motivo="palavra-chave")

    # Frase de visita com identificador é briefing, sempre. É o caminho que a
    # aba Ranking usa.
    if _VISITA.search(texto) and (ufcrm or crm or nome or termo):
        return Rota(**base, intencao="briefing_medico", motivo="frase de visita")

    if sobra and not termo:
        return Rota(**base, intencao=None, motivo=f"texto nao reconhecido: {' '.join(sobra[:4])}")

    if ufcrm or crm or nome or termo:
        return Rota(**base, intencao="briefing_medico", motivo="identificador seco")
    if setor:
        return Rota(**base, intencao="resumo_setor", motivo="setor seco")
    return Rota(**base, intencao=None, motivo="sem identificador")


# --------------------------------------------------------------------------- #
# Consulta única. Fonte de tudo que o briefing precisa.
# --------------------------------------------------------------------------- #

def _nome_produto(expressao: str) -> str:
    """Nome de produto pronto para a tela, com as duas limpezas sempre juntas.

    A primeira tira o sufixo entre parênteses, que é código interno de
    embalagem. A segunda tira o `LNI` que sobra no fim, marcação de laboratório
    da fonte, presente em 765.647 dos 2.389.830 nomes do ciclo, medido em
    10/08/2026. Ele aparece em duas formas, `SINVASTATINA LNI` e o nome
    abreviado `AMOXI.CLAV.LNI`, então o separador entra na classe.

    Os regex são escritos sem barra invertida de propósito: a versão com \\s e
    \\( era corrompida no round-trip de JSON e devolvia ")".
    """
    return f"regexp_replace(regexp_replace({expressao}, '[ ]*[(][^)]*[)]', ''), '[ .]LNI$', '')"


# Perfil de comunicação, o mesmo que a gaveta do Ranking edita. Consulta
# separada porque mora em outra view: a `vw_segmentacao_efetiva` resolve edição
# do propagandista, senão SalesFarma, senão A DEFINIR. Medida em 20/08/2026:
# 3,0 segundos com o warehouse quente.
SQL_SEGMENTACAO = (
    "SELECT perfil_efetivo, origem_do_valor "
    "FROM vw_segmentacao_efetiva WHERE setor = :setor AND ufcrm = :ufcrm"
)

# Todos os mercados montados em que o médico prescreveu, da AuditPharma. É a
# mesma fonte que a gaveta do Ranking usa, e aqui sem o corte de três: no chat
# cabe a lista inteira. Medida em 20/08/2026: 9,1 segundos com o warehouse
# quente.
SQL_MERCADOS_DO_MEDICO = (
    "SELECT MERCADO, SUM(RX_MERCADO_ATUAL) AS rx, MAX(ESP_AUDIT) AS especialidade "
    "  FROM vw_gold_auditpharma "
    " WHERE SETOR = :setor AND UFCRM = :ufcrm AND RX_MERCADO_ATUAL > 0 "
    " GROUP BY MERCADO ORDER BY rx DESC"
)

# O que a especialidade dele prescreve no setor e ele ainda não. É o gancho de
# visita: no teste de 20/08, doze cardiologistas do mesmo setor prescreviam Sany
# D e o médico em questão não.
#
# A especialidade é resolvida dentro da própria consulta, e não recebida de
# fora, para esta rodar em paralelo com a de cima em vez de esperar por ela.
# Juntar as duas numa só foi tentado e custou 27 segundos, contra 9 do paralelo:
# o NOT IN com subconsulta é o que sai caro.
SQL_OPORTUNIDADE = (
    "WITH esp AS (SELECT MAX(ESP_AUDIT) AS e FROM vw_gold_auditpharma "
    "              WHERE SETOR = :setor AND UFCRM = :ufcrm), "
    "     dele AS (SELECT DISTINCT MERCADO FROM vw_gold_auditpharma "
    "               WHERE SETOR = :setor AND UFCRM = :ufcrm AND RX_MERCADO_ATUAL > 0) "
    "SELECT a.MERCADO, COUNT(DISTINCT a.UFCRM) AS medicos, SUM(a.RX_MERCADO_ATUAL) AS rx "
    "  FROM vw_gold_auditpharma a JOIN esp ON a.ESP_AUDIT = esp.e "
    " WHERE a.SETOR = :setor AND a.RX_MERCADO_ATUAL > 0 "
    "   AND a.MERCADO NOT IN (SELECT MERCADO FROM dele) "
    " GROUP BY a.MERCADO ORDER BY rx DESC LIMIT 5"
)

SQL_PERFIL = (
    "SELECT p.NOME_MEDICO, p.UFCRM, p.LINHA_PRODUTO, p.POSICAO_RANKING_SETOR, p.PONTOS, "
    "p.QTD_MEDICOS_PAINEL_SETOR, p.RECOMENDACAO, p.MOTIVO_RECOMENDACAO, p.MESES_DESDE_ULTIMA_VISITA, "
    # A ordem importa e o primeiro caso é o que faltava: 4.110 linhas saem por
    # ranking e por visita ao mesmo tempo, e eram lidas só como ranking, o que
    # apagava o segundo motivo, com mediana de cinco meses sem visita.
    "CASE WHEN p.MOTIVO_RECOMENDACAO LIKE '%por ranking%' AND p.MOTIVO_RECOMENDACAO LIKE '%por visita%' THEN 'ranking e visita' "
    "     WHEN p.MOTIVO_RECOMENDACAO LIKE '%por ranking%' THEN 'saiu do corte' "
    "     WHEN p.MOTIVO_RECOMENDACAO LIKE '%nenhuma visita%' THEN 'sem visita registrada' "
    "     WHEN p.MOTIVO_RECOMENDACAO LIKE '%por visita%' THEN 'dentro do corte sem visita' END AS CRITERIO_DA_SAIDA, "
    # Uma janela por resposta, nunca COALESCE item a item. Misturar produzia
    # lista impossivel na tela, do tipo "100% do volume" no primeiro item
    # seguido de mais dois: o 100% vinha do ciclo e os outros dois do
    # historico, com bases de calculo diferentes. A janela e decidida pela
    # primeira categoria e as outras duas seguem a mesma.
    "CASE WHEN p.CICLO_TOP1_CATEGORIA IS NOT NULL THEN p.CICLO_TOP1_CATEGORIA "
    "     WHEN p.YTD_TOP1_CATEGORIA IS NOT NULL THEN p.YTD_TOP1_CATEGORIA "
    "     ELSE p.GERAL_TOP1_CATEGORIA END AS TOP1_CATEGORIA, "
    "ROUND(CASE WHEN p.CICLO_TOP1_CATEGORIA IS NOT NULL THEN p.CICLO_TOP1_PCT "
    "           WHEN p.YTD_TOP1_CATEGORIA IS NOT NULL THEN p.YTD_TOP1_PCT "
    "           ELSE p.GERAL_TOP1_PCT END, 1) AS TOP1_PCT, "
    "CASE WHEN p.CICLO_TOP1_CATEGORIA IS NOT NULL THEN p.CICLO_TOP2_CATEGORIA "
    "     WHEN p.YTD_TOP1_CATEGORIA IS NOT NULL THEN p.YTD_TOP2_CATEGORIA "
    "     ELSE p.GERAL_TOP2_CATEGORIA END AS TOP2_CATEGORIA, "
    # Percentual da segunda e da terceira so existe na janela do ciclo. Fora
    # dela vem nulo, e o formatador entao omite o percentual da lista inteira
    # em vez de deixar um item com numero e dois sem.
    "ROUND(CASE WHEN p.CICLO_TOP1_CATEGORIA IS NOT NULL THEN p.CICLO_TOP2_PCT END, 1) AS TOP2_PCT, "
    "CASE WHEN p.CICLO_TOP1_CATEGORIA IS NOT NULL THEN p.CICLO_TOP3_CATEGORIA "
    "     WHEN p.YTD_TOP1_CATEGORIA IS NOT NULL THEN p.YTD_TOP3_CATEGORIA "
    "     ELSE p.GERAL_TOP3_CATEGORIA END AS TOP3_CATEGORIA, "
    "ROUND(CASE WHEN p.CICLO_TOP1_CATEGORIA IS NOT NULL THEN p.CICLO_TOP3_PCT END, 1) AS TOP3_PCT, "
    # O produto exibido segue a mesma janela da categoria. A tabela guarda
    # produto só nas janelas do ciclo e do histórico, então na janela do ano
    # nenhum produto é mostrado, em vez de trazer o do histórico e misturar
    # períodos, que é o defeito que a janela única veio corrigir.
    + _nome_produto(
        "CASE WHEN p.CICLO_TOP1_CATEGORIA IS NOT NULL THEN p.CICLO_TOP1_PRODUTO "
        "     WHEN p.YTD_TOP1_CATEGORIA IS NOT NULL THEN NULL "
        "     ELSE p.GERAL_TOP1_PRODUTO END"
    ) + " AS TOP1_PRODUTO, "
    + _nome_produto(
        "CASE WHEN p.CICLO_TOP1_CATEGORIA IS NOT NULL THEN p.CICLO_TOP2_PRODUTO "
        "     WHEN p.YTD_TOP1_CATEGORIA IS NOT NULL THEN NULL "
        "     ELSE p.GERAL_TOP2_PRODUTO END"
    ) + " AS TOP2_PRODUTO, "
    + _nome_produto(
        "CASE WHEN p.CICLO_TOP1_CATEGORIA IS NOT NULL THEN p.CICLO_TOP3_PRODUTO "
        "     WHEN p.YTD_TOP1_CATEGORIA IS NOT NULL THEN NULL "
        "     ELSE p.GERAL_TOP3_PRODUTO END"
    ) + " AS TOP3_PRODUTO, "
    # As três janelas cobrem 93,2%, 98,9% e 99,4%. Ler só a do ciclo deixaria
    # 160.773 médicos sem retrato, medido em 09/08/2026.
    "CASE WHEN p.CICLO_TOP1_CATEGORIA IS NOT NULL THEN 'ultimo periodo' "
    "     WHEN p.YTD_TOP1_CATEGORIA IS NOT NULL THEN 'ano vigente' ELSE 'historico' END AS JANELA_USADA, "
    # A participação Aché segue a mesma janela das categorias. Com COALESCE
    # ela pegava o primeiro valor não nulo: um médico sem categoria no ciclo,
    # mas com percentual zero gravado no ciclo, mostrava categorias do ano e
    # percentual do ciclo na mesma frase.
    "ROUND(CASE WHEN p.CICLO_TOP1_CATEGORIA IS NOT NULL THEN p.CICLO_PCT_ACHE "
    "          WHEN p.YTD_TOP1_CATEGORIA IS NOT NULL THEN p.YTD_PCT_ACHE "
    "          ELSE p.GERAL_PCT_ACHE END, 1) AS PCT_ACHE, "
    # PRODUTO_RECOMENDADO_LINHA é a recomendação do propagandista e é sempre da
    # linha do setor. PRODUTO_RECOMENDADO_ACHE é o resgate de qualquer linha, e
    # só entra quando não há produto na linha dele.
    + _nome_produto("p.PRODUTO_RECOMENDADO_LINHA") + " AS PRODUTO_RECOMENDADO, "
    "p.PRODUTO_RECOMENDADO_CATEGORIA AS CATEGORIA_DO_PRODUTO, "
    # Compara com o top 3 da janela escolhida, e não com um COALESCE por
    # posição. Do jeito antigo, o primeiro lugar podia vir do ciclo e o segundo
    # do ano, e a resposta afirmava "está entre as três de maior volume"
    # misturando dois períodos.
    "CASE WHEN p.PRODUTO_RECOMENDADO_CATEGORIA IS NULL THEN NULL "
    "     WHEN p.PRODUTO_RECOMENDADO_CATEGORIA = "
    "          CASE WHEN p.CICLO_TOP1_CATEGORIA IS NOT NULL THEN p.CICLO_TOP1_CATEGORIA "
    "               WHEN p.YTD_TOP1_CATEGORIA IS NOT NULL THEN p.YTD_TOP1_CATEGORIA "
    "               ELSE p.GERAL_TOP1_CATEGORIA END THEN 'primeira' "
    "     WHEN p.PRODUTO_RECOMENDADO_CATEGORIA IN ("
    "          CASE WHEN p.CICLO_TOP1_CATEGORIA IS NOT NULL THEN p.CICLO_TOP2_CATEGORIA "
    "               WHEN p.YTD_TOP1_CATEGORIA IS NOT NULL THEN p.YTD_TOP2_CATEGORIA "
    "               ELSE p.GERAL_TOP2_CATEGORIA END, "
    "          CASE WHEN p.CICLO_TOP1_CATEGORIA IS NOT NULL THEN p.CICLO_TOP3_CATEGORIA "
    "               WHEN p.YTD_TOP1_CATEGORIA IS NOT NULL THEN p.YTD_TOP3_CATEGORIA "
    "               ELSE p.GERAL_TOP3_CATEGORIA END) THEN 'entre as tres' "
    "     ELSE 'fora das tres' END AS POSICAO_DA_CATEGORIA_DO_PRODUTO, "
    # Colunas do bloco de relação. Contagem de categoria e de produto segue a
    # janela como todo o resto. O volume de prescrição não entra em texto
    # nenhum: `RX_QTY` é estimativa projetada de base amostral, nunca contagem
    # de receitas, conforme o comentário da própria tabela.
    "p.CICLOS_NO_PAINEL_JANELA, p.DATA_ULTIMA_VISITA, p.ULTIMO_PERIODO_NA_CATEGORIA, "
    "CASE WHEN p.CICLO_TOP1_CATEGORIA IS NOT NULL THEN p.CICLO_QTD_CATEGORIAS "
    "     WHEN p.YTD_TOP1_CATEGORIA IS NOT NULL THEN p.YTD_QTD_CATEGORIAS "
    "     ELSE p.GERAL_QTD_CATEGORIAS END AS QTD_CATEGORIAS, "
    # A janela do ano não tem contagem de produto na tabela, então ali a linha
    # sai só com categorias, em vez de misturar períodos.
    "CASE WHEN p.CICLO_TOP1_CATEGORIA IS NOT NULL THEN p.CICLO_QTD_PRODUTOS "
    "     WHEN p.YTD_TOP1_CATEGORIA IS NOT NULL THEN NULL "
    "     ELSE p.GERAL_QTD_PRODUTOS END AS QTD_PRODUTOS, "
    "p.REC_E_TOP1, p.ORIGEM_DA_RECOMENDACAO, p.JA_PRESCREVE_O_PRODUTO, "
    # A marca de prescrição segue a mesma janela das categorias e do percentual
    # Aché. Ler a marca de uma janela e o número de outra é o que produzia a
    # contradição entre não ter prescrito Aché no período e já prescrever o
    # produto Aché recomendado.
    "CASE WHEN p.CICLO_TOP1_CATEGORIA IS NOT NULL THEN p.PRESCREVE_NO_CICLO "
    "     WHEN p.YTD_TOP1_CATEGORIA IS NOT NULL THEN p.PRESCREVE_NO_ANO "
    "     ELSE p.JA_PRESCREVE_O_PRODUTO END AS PRESCREVE_NO_PERIODO, "
    # Segundo e terceiro produto da linha com maior aderencia ao que o medico
    # prescreve. Podem ser de categoria fora do top 3 exibido, entao a resposta
    # sempre diz para que cada um serve.
    + _nome_produto("p.PRODUTO2_LINHA") + " AS PRODUTO2, p.PRODUTO2_CATEGORIA, "
    + _nome_produto("p.PRODUTO3_LINHA") + " AS PRODUTO3, p.PRODUTO3_CATEGORIA, "
    + _nome_produto("p.PRODUTO_RECOMENDADO_ACHE") + " AS PRODUTO_ACHE_OUTRA_LINHA, "
    "p.PRODUTO_RECOMENDADO_ACHE_LINHA AS LINHA_DO_PRODUTO_ACHE "
    # Sem qualificação de catálogo: nomes sem `acheinfo_dev.renovai.` já
    # resolvem certo nos dois lados de `DATA_SOURCE` (Postgres local via
    # `search_path`, Databricks via `catalog`/`schema` de `connect_args`,
    # confirmado por teste direto em 26/08/2026).
    "FROM tb_perfil_medico_setor p "
    "WHERE p.SETOR = :setor AND p.UFCRM = :ufcrm"
)


# --------------------------------------------------------------------------- #
# Vocabulário de exibição
# --------------------------------------------------------------------------- #

# A tabela não informa o sexo do médico. A `tt__dim_medico360_digital` tem a
# coluna SEXO, mas cobre 39,6% dos 586.061 médicos e traz UFCRM com M e F ao
# mesmo tempo, medido em 09/08/2026. Por isso nenhum texto daqui flexiona
# gênero: usa o nome ou sujeito oculto, que o português já oferece.
_STATUS = {
    "ADICIONAR": "Recomendado para inclusão",
    "CONTINUAR": "Recomendado para permanência",
    "REMOVER": "Recomendado para saída",
    "SEM_ACAO": "Sem ação no ciclo",
}

# Encurtamento para o termo que o médico usa na conversa. Só entra par cuja
# equivalência é direta; na dúvida, o texto da tabela vai inteiro.
_CURTO = {
    "Medicamentos para tratar depressão e ansiedade": "antidepressivos",
    "Medicamentos para tratar pressão alta": "anti-hipertensivos",
    "Medicamentos para colesterol alto": "medicamentos para colesterol alto",
}

# A leitura da faixa é obrigatória: o percentual sozinho não comunica nada ao
# propagandista, como ficou claro quando George leu "participação de 2,1%" e
# não entendeu do que era a fatia.
_FAIXAS = (
    (5, "Quase todo o volume vai para outras marcas, então há bastante espaço."),
    (15, "A Aché já aparece, mas a maior parte ainda vai para outras marcas."),
    (30, "A Aché já tem presença relevante."),
    (float("inf"), "A Aché já é forte aqui, e o trabalho é manter."),
)

# Cada frase nomeia a categoria como sujeito e diz de qual período fala. Antes
# começava sem sujeito nenhum ("Está entre as três categorias de maior
# volume"), e George apontou em 10/08/2026 que não dava para saber do que ela
# falava. O sujeito plural é garantido por `_classe`.
_JUSTIFICATIVA = {
    "primeira": "{classe} são a categoria de maior volume nas prescrições {periodo}.",
    "entre as tres": "{classe} estão entre as três categorias de maior volume nas prescrições {periodo}.",
    "fora das tres": "{classe} estão fora das três categorias de maior volume nas prescrições {periodo}.",
}

CHIP_VISITA = "O que levar na visita?"
CHIP_PRESCREVE = "O que mais prescreve?"
CHIP_RELACAO = "Como está a relação?"
# Só em remoção. O primeiro sustenta a saída e o segundo é a porta de saída da
# recomendação: a orientação de visita só aparece se o propagandista disser
# que quer manter o médico.
CHIP_POR_QUE_TIRAR = "Por que tirar do painel?"
CHIP_MANTER = "Quero manter e visitar"

# A janela de painel tem três ciclos, fixada na regra de recomendação em
# `nb_tb_RankMedValid`. Estar nos três significa a janela inteira.
#
# Eram cinco até 17/08/2026. A redução veio junto com a da janela de visita, de
# cinco para três meses, para a recomendação chegar como lembrete antes da
# exclusão automática da Aché, que ocorre aos cinco meses e pode passar a
# quatro. Este número precisa acompanhar o do notebook: se ficar em cinco
# enquanto a regra usa três, a frase "a janela inteira que a base cobre" deixa
# de aparecer para quem de fato completou a janela.
CICLOS_DA_JANELA = 3

_MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)

# Partículas que ficam em minúscula no meio do nome. As tabelas guardam tudo em
# caixa alta, e caixa alta na tela lê como grito.
_PARTICULAS = {"da", "de", "do", "das", "dos", "e", "di", "du", "del", "van", "von"}


def _maiuscula_inicial(palavra: str) -> str:
    """Primeira letra, e também a que vem depois de apóstrofo.

    A `tb_perfil_medico_setor` não tem nome com apóstrofo, medido em
    10/08/2026, mas a `tb_recomendacoes_painel_historico` tem, e é dela que a
    lista de sugestões lê. Sem este tratamento, `D'AMICO` sairia como
    `D'amico` na lista e `Damico` no card.
    """
    inicio, marca, resto = palavra.partition("'")
    return inicio[:1].upper() + inicio[1:] + marca + resto[:1].upper() + resto[1:]


def _nome_proprio(nome: str | None) -> str:
    """Nome do médico com inicial maiúscula, decisão de George em 10/08/2026."""
    if not nome:
        return ""
    palavras = []
    for posicao, bruta in enumerate(nome.strip().split()):
        palavra = bruta.lower()
        palavras.append(palavra if posicao and palavra in _PARTICULAS else _maiuscula_inicial(palavra))
    return " ".join(palavras)


def _pct(valor: Any) -> str:
    """Percentual no padrão brasileiro. Com vírgula a concordância de 'é' ou
    'são' mudaria conforme o número, então nenhuma frase daqui usa esse verbo."""
    return f"{float(valor):.1f}".replace(".", ",")


def _curto(categoria: str | None) -> str:
    if not categoria:
        return ""
    if categoria in _CURTO:
        return _CURTO[categoria]
    return categoria[0].lower() + categoria[1:]


def _classe(categoria: str | None) -> str:
    """A categoria como sujeito de frase: "Os anti-hipertensivos".

    Os 109 textos de categoria da tabela são todos substantivos masculinos no
    plural, medido em 10/08/2026, então o artigo é sempre "Os" e o verbo que
    vem depois é sempre plural. As três frases de justificativa dependem disso.
    """
    curto = _curto(categoria)
    if curto.startswith("outros "):
        curto = curto[len("outros "):]
    return f"Os {curto}" if curto else ""


def _singular(categoria: str | None) -> str:
    """A categoria descrevendo um produto só: "anti-hipertensivo".

    Sem isso a frase diz que um produto é "anti-hipertensivos", no plural, que
    foi o que George apontou em 10/08/2026. O singular sai tirando o "s" do
    substantivo que abre o texto; o resto da expressão não muda.

    Só flexiona quando o que vem depois do substantivo é uma expressão com
    "para", que não muda de número. Em "Medicamentos tônicos e revigorantes" os
    adjetivos concordam com o substantivo e a flexão teria que pegar a
    expressão inteira, então a função desiste: 93 linhas em 2.548.243, medido
    em 10/08/2026. Quem chama decide o que dizer no lugar.
    """
    curto = _curto(categoria)
    if not curto:
        return ""
    if curto.startswith("outros "):
        curto = curto[len("outros "):]
    cabeca, espaco, resto = curto.partition(" ")
    if not cabeca.endswith("s") or (resto and not resto.startswith("para ")):
        return ""
    return f"{cabeca[:-1]}{espaco}{resto}"


def _um_da_categoria(categoria: str | None) -> str:
    """"um anti-hipertensivo", ou o nome da categoria quando não dá para flexionar."""
    singular = _singular(categoria)
    if singular:
        return f"um {singular}"
    curto = _curto(categoria)
    return f"da categoria {curto}" if curto else ""


def _para_que_serve(categoria: str | None) -> str:
    """A finalidade da categoria: "para tratar pressão alta".

    108 dos 109 textos têm a forma "<substantivo> para <finalidade>", então a
    finalidade sai do próprio texto. O que sobra cai no nome da categoria.

    A leitura é do texto original, e não do encurtado, porque o encurtamento
    troca a expressão inteira por uma classe ("anti-hipertensivos") e a
    finalidade se perde no caminho.
    """
    if not categoria:
        return ""
    _, marca, finalidade = categoria.partition(" para ")
    return f"para {finalidade}" if marca else f"da categoria {_curto(categoria)}"


def _categorias(d: dict) -> list[dict]:
    """Categorias da janela escolhida, com percentual só quando há para todas.

    Fora da janela do ciclo a tabela guarda percentual apenas da primeira. Uma
    lista com um item numerado e dois sem parece erro de sistema, então nesse
    caso o percentual sai de todos.
    """
    saida = []
    for cat, pct in (
        (d.get("TOP1_CATEGORIA"), d.get("TOP1_PCT")),
        (d.get("TOP2_CATEGORIA"), d.get("TOP2_PCT")),
        (d.get("TOP3_CATEGORIA"), d.get("TOP3_PCT")),
    ):
        if cat:
            saida.append({"categoria": _curto(cat), "pct": float(pct) if pct is not None else None})
    if any(c["pct"] is None for c in saida):
        for c in saida:
            c["pct"] = None
    return saida


def _produtos(d: dict) -> list[str]:
    return [d[k] for k in ("TOP1_PRODUTO", "TOP2_PRODUTO", "TOP3_PRODUTO") if d.get(k)]


def _lista(itens: list[str]) -> str:
    if not itens:
        return ""
    if len(itens) == 1:
        return itens[0]
    return ", ".join(itens[:-1]) + " e " + itens[-1]


def _janela(d: dict) -> str:
    return {"ano vigente": " (considerando o ano)", "historico": " (considerando o histórico)"}.get(
        d.get("JANELA_USADA") or "", ""
    )


def _periodo(d: dict) -> str:
    """Como a janela é dita dentro da frase.

    Toda afirmação sobre participação Aché é do período lido, nunca da vida
    toda do médico. Sem essa marca, a frase mentia: medido em 10/08/2026,
    1.032.248 linhas diziam que o médico não prescreve Aché quando ele
    prescreveu no ano ou no histórico, e a leitura era só do ciclo.
    """
    return {"ano vigente": "neste ano", "historico": "no histórico"}.get(
        d.get("JANELA_USADA") or "", "neste período"
    )


def _do_periodo(d: dict) -> str:
    """A mesma janela ligada a um substantivo: "nas prescrições deste ano"."""
    return {"ano vigente": "deste ano", "historico": "do histórico"}.get(
        d.get("JANELA_USADA") or "", "deste período"
    )


# --------------------------------------------------------------------------- #
# Blocos de texto. Cada um responde a um chip.
# --------------------------------------------------------------------------- #


def bloco_decisao(d: dict) -> str:
    """Frase de abertura. Nenhuma delas repete posição nem pontuação.

    Decisão de George em 10/08/2026: os dois números ficam só no card, que
    aparece logo abaixo da mensagem. Repetir na frase mostrava o mesmo valor
    duas vezes com dois dedos de distância. Meses sem visita continuam no
    texto, porque não estão no card.
    """
    nome = _nome_proprio(d["NOME_MEDICO"])
    rec = d["RECOMENDACAO"]
    if rec == "ADICIONAR":
        # "Chegou a essa posição" sozinho ficava pendurado: tirando o número da
        # frase, o "essa" não apontava para nada dentro dela. Nomear a
        # pontuação e o ranking devolve o referente, e os valores continuam só
        # no card logo abaixo.
        return (
            f"{nome} deveria estar no seu painel por conta da pontuação e do ranking, "
            "que vêm do que prescreve da sua linha."
        )
    if rec == "CONTINUAR":
        # Passa a justificar, decisão de George em 20/08/2026, revendo a de
        # 10/08 que deixava a permanência sem causa. As três recomendações agora
        # dizem por quê: entrada e permanência pelo ranking, saída por ranking,
        # por tempo sem visita ou por nunca ter sido visitado.
        #
        # A ressalva de 10/08 continua válida e virou redação: para as 547 linhas
        # de médico sem prescrição em janela nenhuma, dizer que a posição vem do
        # que ele prescreve seria falso. A frase cita a posição no ranking, que é
        # fato da tabela, e não a origem dela.
        return f"{nome} deve seguir no seu painel pela posição no ranking do seu setor."
    if rec == "REMOVER":
        criterio = d.get("CRITERIO_DA_SAIDA")
        # O texto fala em limite do painel, nunca no número do corte. Decisão de
        # George em 09 e 10/08/2026, e o número seria falso de qualquer forma:
        # só 12 dos 2.153 setores tinham painel de exatamente 400, e os reais
        # vão de 251 a 596.
        #
        # A decisão envelheceu bem. Desde 17/08/2026 o corte deixou de ser um
        # número único e passou a ser o limite que o GD define para cada
        # propagandista, então citar um número aqui teria virado defeito.
        #
        # Os dois critérios de saída são opostos e a resposta erra se tratar os
        # dois igual: 112.426 linhas saem por queda no ranking, sempre além do
        # limite, e 17.075 saem por ausência de visita, sempre dentro dele, às
        # vezes na posição 1. Chamar de fraco quem é primeiro do setor seria
        # falso, e o propagandista percebe.
        if criterio == "ranking e visita":
            return (
                f"{nome} caiu no ranking do seu setor, passou do limite do seu painel ideal "
                f"e ainda não recebe visita há {d.get('MESES_DESDE_ULTIMA_VISITA')} meses."
            )
        if criterio == "saiu do corte":
            return f"{nome} caiu no ranking do seu setor e passou do limite do seu painel ideal."
        if criterio == "sem visita registrada":
            return f"{nome} está dentro do limite do seu painel ideal, mas não tem visita registrada."
        return f"{nome} está dentro do limite do seu painel ideal, mas não recebe visita há {d.get('MESES_DESDE_ULTIMA_VISITA')} meses."
    return f"{nome} não tem ação recomendada neste ciclo."


def bloco_prescricao(d: dict) -> str:
    """O que o médico mais prescreve, por nome de medicamento. Bloco 3.

    Passa a listar **medicamento**, e não categoria com percentual, por decisão
    de George em 20/08/2026. A categoria respondia "que tipo de remédio ele
    receita", e a pergunta de quem está indo visitar é "o que ele receita".
    "Anti-hipertensivos, 33,8% do volume" é verdadeiro e não vira conversa;
    "Aradois, Losartan e Selozok" vira.

    O percentual sai junto com a categoria. Ele media participação de classe, e
    sozinho, sem a classe, não teria referente.
    """
    produtos = _produtos(d)
    if not produtos:
        cats = _categorias(d)
        if not cats:
            return f"Não há prescrição registrada para {_nome_proprio(d['NOME_MEDICO'])}."
        # Sem nome de medicamento na tabela, a categoria é o que sobra. Melhor
        # que bloco vazio, e a tela não precisa saber da diferença.
        linhas = [f"O que mais prescreve{_janela(d)}"]
        linhas += [f"- {c['categoria']}" for c in cats]
        return "\n".join(linhas)

    linhas = [f"O que mais prescreve{_janela(d)}"]
    for produto in produtos:
        linhas.append(f"- {produto}")
    # A frase de rodapé "os que mais aparecem nas prescrições são" saiu: a lista
    # acima já é de medicamentos, e repetir os mesmos três nomes em outro formato
    # logo abaixo era ler duas vezes. A ressalva que ela carregava continua
    # valendo e passou para cá: esta lista é o que o médico receita, de qualquer
    # laboratório, genérico inclusive. A recomendação Aché está em `bloco_acao`,
    # e nunca traz genérico.
    return "\n".join(linhas)


def bloco_ache(d: dict) -> str:
    """Participação Aché, com a frase mudando conforme a recomendação.

    Decisão de George em 10/08/2026. Quando não há prescrição Aché no período,
    a mesma informação serve a três propósitos diferentes: em inclusão e
    permanência é uma ressalva, o médico é recomendado apesar disso; em saída
    por ranking é mais um argumento a favor de tirar; em saída por visita não é
    argumento nenhum, porque o perfil continua forte e a saída vem da ausência
    de visita, não do potencial.
    """
    # Sem prescrição em janela nenhuma não há participação a medir, e a leitura
    # de faixa dizia "quase todo o volume vai para outras marcas" sobre um
    # médico sem volume algum. São 14.525 linhas na tabela, 2.897 delas nos
    # três tipos que geram ação, medido em 10/08/2026.
    if not d.get("TOP1_CATEGORIA"):
        return (
            f"Não há prescrição registrada para {_nome_proprio(d['NOME_MEDICO'])}, "
            "então não dá para medir a participação da Aché."
        )

    pct = float(d.get("PCT_ACHE") or 0)
    periodo = _periodo(d)

    if pct > 0:
        frase = f"Os medicamentos da Aché representam {_pct(pct)}% do que prescreveu {periodo}."
    elif d["RECOMENDACAO"] in ("ADICIONAR", "CONTINUAR"):
        frase = (
            f"Os medicamentos da Aché ainda não apareceram nas prescrições {periodo}. "
            "Porém a recomendação vale mesmo assim."
        )
    else:
        frase = f"Os medicamentos da Aché não apareceram nas prescrições {periodo}."

    # Em saída, nenhuma leitura de oportunidade. As quatro faixas são escritas
    # para animar, de "há bastante espaço" a "a Aché já é forte aqui", e elogiar
    # um médico que a resposta manda tirar do painel derruba a própria
    # recomendação. Decisão de George em 10/08/2026: em remoção nunca elogiar,
    # sempre sustentar a saída.
    if d["RECOMENDACAO"] == "REMOVER":
        return frase
    return f"{frase}\n{next(t for limite, t in _FAIXAS if pct < limite)}"


def _outros_produtos(d: dict) -> str:
    """Segundo e terceiro produto da linha, com a finalidade de cada um.

    Eles vêm da aderência ao que o médico prescreve, não das categorias
    exibidas acima, e podem tratar de coisa que não está naquela lista. Por
    isso cada um sempre vem acompanhado do que trata.

    Quando o produto é da mesma categoria do recomendado, a frase diz isso com
    "também". Sem essa marca a lista parecia abrir uma alternativa nova quando
    estava repetindo a categoria da linha de cima. Medido em 10/08/2026: o
    segundo produto repete a categoria do recomendado em 478.039 das 2.437.460
    linhas que o trazem, e o terceiro em 295.603.
    """
    recomendada = d.get("CATEGORIA_DO_PRODUTO")
    itens = []
    for produto, categoria in (
        (d.get("PRODUTO2"), d.get("PRODUTO2_CATEGORIA")),
        (d.get("PRODUTO3"), d.get("PRODUTO3_CATEGORIA")),
    ):
        if not produto:
            continue
        if not categoria:
            itens.append(produto)
        elif categoria == recomendada:
            singular = _singular(categoria)
            itens.append(f"{produto}, também um {singular}" if singular else f"{produto}, da mesma categoria")
        else:
            itens.append(f"{produto}, {_para_que_serve(categoria)}")
    if not itens:
        return ""
    # Vírgula antes do "e" porque cada item já tem vírgula dentro. Sem ela os
    # dois produtos viram uma frase só e não dá para ver onde um termina.
    corpo = ", e ".join(itens)
    # "Ainda na sua linha" retoma a linha citada na primeira frase, em vez de
    # abrir um assunto novo do nada.
    return f"Ainda na sua linha, você tem {corpo}."


# Cada estado da relação do médico com o produto pede uma visita diferente.
# Decisão de George em 10/08/2026: a resposta não pode ser sempre a mesma
# frase, ela tem que dizer o que fazer.
#
# O sujeito de cada frase é o próprio produto, e não o médico, por dois
# motivos. O primeiro é que a tabela não tem o gênero do médico, então "ele
# prescreve" erraria com toda médica. O segundo é que o estado do produto vem
# de uma leitura sem período, diferente da janela que sustenta a frase da
# categoria: se as duas frases dividissem o mesmo sujeito, a segunda pareceria
# falar do mesmo período da primeira, o que seria falso.
#
# O "então" no meio existe para ligar o que a base diz com o que fazer na
# visita. Sem ele as duas metades ficam soltas, como George apontou em
# 10/08/2026.
_CONVERSA = {
    "manutencao": (
        "{produto} já está sendo prescrito, então a visita é de manutenção: confirmar o "
        "que está funcionando e abrir espaço para outro produto da sua linha."
    ),
    "reativacao": (
        "{produto} já foi prescrito antes e parou, então vale entender o que mudou antes "
        "de propor de novo."
    ),
    "introducao": "{produto} ainda não foi prescrito, então a visita é de primeira apresentação.",
    # Estado provisório, enquanto a tabela não separa manutenção de reativação.
    # A marca de origem lê a base inteira, sem período, então afirmar qualquer
    # um dos dois seria chute. A frase assume a limitação em vez de escondê-la.
    "conhecido": (
        "{produto} já foi prescrito antes, mas a base não diz se ainda é, então vale "
        "confirmar isso para decidir o tom da visita."
    ),
}


def _estado_do_produto(d: dict) -> str:
    """Relação do médico com o produto recomendado, em três estados.

    `JA_PRESCREVE_O_PRODUTO` vem da CTE `ja_prescreve` do notebook, que lê a
    base inteira sem filtro de período. Sozinha, ela não distingue quem
    prescreve agora de quem prescreveu e parou. Enquanto a coluna de período
    não existir, o estado fica em `conhecido` e o texto diz isso.
    """
    if str(d.get("JA_PRESCREVE_O_PRODUTO")) != "1":
        return "introducao"
    agora = d.get("PRESCREVE_NO_PERIODO")
    if agora is None:
        return "conhecido"
    return "manutencao" if str(agora) == "1" else "reativacao"


def _outra_linha(d: dict) -> str:
    """Produto Aché de outra linha, sempre que existir e for mesmo outro.

    Decisão de George em 10/08/2026: a resposta oferece dois tipos, um da linha
    do propagandista e um de outra linha, e os dois são sempre Aché. Antes o de
    outra linha só aparecia quando não havia nada da linha dele.

    O campo de origem é o melhor produto Aché de qualquer linha, então às vezes
    ele coincide com o da linha. Medido em 10/08/2026: de 2.548.166 linhas com
    os dois campos, 516.813 trazem o mesmo produto. Nesses casos ele não entra,
    para não parecer que a resposta está repetindo o mesmo nome de propósito.
    """
    produto = d.get("PRODUTO_ACHE_OUTRA_LINHA")
    linha = d.get("LINHA_DO_PRODUTO_ACHE")
    if not produto or produto == d.get("PRODUTO_RECOMENDADO"):
        return ""
    if str(linha) == str(d.get("LINHA_PRODUTO")):
        return ""
    return f"De outra linha, existe {produto}, da linha {linha}."


# Indicação de cada produto, vinda da estratégia de ciclo. Carregada uma vez por
# linha e guardada em memória: são cerca de 30 arquivos pequenos por linha, e
# ler um por medicamento custaria 1,5 segundo cada, o que inviabilizaria a lista
# inteira numa resposta só.
_INDICACOES: dict[int, dict[str, str]] = {}


def _indicacoes_da_linha(linha: int) -> dict[str, str]:
    """Mapa de produto para indicação, do material aprovado da Aché.

    Só existe para a Linha 6 hoje: a extração dos PDFs do Portal TDV rodou nela
    primeiro, por decisão de George em 20/08/2026. Linha sem extração devolve
    mapa vazio, e a lista sai sem descrição em vez de sair com texto inventado.
    """
    if linha in _INDICACOES:
        return _INDICACOES[linha]

    mapa: dict[str, str] = {}
    try:
        from backend.app.auth.foto import _cliente, _raiz_do_volume

        cliente = _cliente()
        pasta = f"{_raiz_do_volume()}/estrategia-ciclo/Linha-{linha}"
        for arquivo in cliente.files.list_directory_contents(pasta):
            if not (arquivo.name or "").endswith(".json"):
                continue
            bruto = cliente.files.download(arquivo.path).contents.read()
            dados = _json.loads(bruto.decode("utf-8"))
            indicacao = dados.get("indicacao_principal")
            if indicacao and indicacao != "nao_informado":
                mapa[_chave(arquivo.name[:-5])] = indicacao
    except Exception:
        logger.exception("Falha ao carregar a estratégia de ciclo da linha %s.", linha)

    _INDICACOES[linha] = mapa
    return mapa


def _chave(nome: str) -> str:
    """Nome comparável entre fontes: `ADINOS GEN`, `Adinos_GEN`, `Adinos-Gen`."""
    limpo = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]", "", limpo).upper()


def _com_indicacao(mercado: str, mapa: dict[str, str]) -> str:
    """`- COLPISTATIN, para vaginoses bacterianas` quando houver material."""
    indicacao = mapa.get(_chave(mercado))
    if not indicacao:
        return f"- {mercado}"
    # Primeira letra minúscula: a indicação entra no meio da frase, depois da
    # vírgula, e o material às vezes começa com maiúscula de título.
    return f"- {mercado}, {indicacao[0].lower()}{indicacao[1:]}"


def bloco_o_que_levar(d: dict) -> str:
    """O que levar na visita: os mercados da sua linha onde ele já prescreve.

    Funde os antigos blocos "o que mais prescreve" e "oferecer", decisão de
    George em 20/08/2026. Os dois liam a mesma coisa com dois blocos de
    distância, e o primeiro deles ainda usava outra fonte.

    **A fonte é a AuditPharma, a mesma da gaveta.** A `tb_perfil_medico_setor`
    saiu daqui: ela devolve o retrato prescritivo global do médico, igual em
    todos os setores, e ignora a linha de quem está olhando. Medido em
    20/08/2026 com a médica SP0076749: a mesma tripla Glifage XR, Aradois e
    Levofloxacino aparecia nos setores das linhas 1, 3 e 6, enquanto a
    AuditPharma mostrava Corus na linha 1 e Livepax e Mefex na linha 4.
    """
    mercados = [m for m in (d.get("MERCADOS") or []) if m.get("MERCADO")]
    if not mercados:
        return ""

    mapa = _indicacoes_da_linha(int(d.get("LINHA_PRODUTO") or 0) or 0)
    nome = _nome_proprio(d["NOME_MEDICO"])
    abertura = (
        "Se ainda assim for visitar, leve"
        if d.get("RECOMENDACAO") == "REMOVER"
        else f"Se for visitar {nome}, leve"
    )
    linhas = [f"{abertura}:"]
    linhas += [_com_indicacao(m["MERCADO"], mapa) for m in mercados]
    return "\n".join(linhas)


def bloco_oportunidade(d: dict) -> str:
    """Onde há espaço para abrir, com prova social do próprio setor.

    Funde a leitura de volume com a lista do que a especialidade prescreve e
    ele não. Decisão de George em 20/08/2026.

    A frase muda com o tamanho: quem quase não prescreve da linha não é caso de
    aviso, é caso de oportunidade, e é o que abre espaço para a visita.
    """
    mercados = [m for m in (d.get("MERCADOS") or []) if m.get("MERCADO")]
    oportunidades = [o for o in (d.get("OPORTUNIDADES") or []) if o.get("MERCADO")]

    # Pelo nome, e não por "ele". Observação de George em 20/08/2026: os blocos
    # acumulavam pronome e a leitura ficava impessoal, como texto sobre um caso
    # e não sobre a pessoa que o propagandista vai visitar daqui a pouco.
    nome = _nome_proprio(d.get("NOME_MEDICO") or "")
    sujeito = nome.split(" ")[0] if nome else "Ele"

    quantos = len(mercados)
    if quantos == 0:
        leitura = f"{sujeito} não prescreve nada da sua linha neste ciclo."
    elif quantos <= 2:
        leitura = f"{sujeito} quase não prescreve da sua linha neste ciclo."
    else:
        leitura = f"{sujeito} já prescreve bastante da sua linha neste ciclo."

    if not oportunidades:
        return leitura

    mapa = _indicacoes_da_linha(int(d.get("LINHA_PRODUTO") or 0) or 0)
    linhas = [
        f"{leitura} Vale usar a visita para abrir espaço para outros "
        "medicamentos, prescritos por médicos da mesma especialidade no seu setor:"
    ]
    # Sem a contagem de médicos, decisão de George em 20/08/2026. O número
    # parecia prova social e não era: num painel de 338 médicos, "7 médicos
    # prescrevem" não distingue nada, e um número pequeno ao lado do primeiro
    # item ainda enfraquecia a sugestão em vez de sustentá-la. A frase de
    # abertura já diz que vem de colegas da mesma especialidade no setor, que é
    # a parte que importa.
    linhas += [_com_indicacao(o["MERCADO"], mapa) for o in oportunidades]
    return "\n".join(linhas)


def bloco_acao(d: dict) -> str:
    produto = d.get("PRODUTO_RECOMENDADO")
    if not produto:
        resgate = d.get("PRODUTO_ACHE_OUTRA_LINHA")
        if resgate:
            return (
                "Não há produto da sua linha para esse perfil.\n"
                f"Existe {resgate}, da linha {d.get('LINHA_DO_PRODUTO_ACHE')}, que é de outra linha."
            )
        return f"Não há recomendação de produto para {_nome_proprio(d['NOME_MEDICO'])}."

    # REC_E_TOP1 marca o melhor cenário possível: o produto recomendado já é o
    # mais indicado pelo médico. Não é falha da recomendação, é o resultado que
    # a propaganda persegue, então a visita vira manutenção mais abertura.
    if str(d.get("REC_E_TOP1")) == "1":
        linhas = [f"Aqui o trabalho já deu certo: {produto} é o medicamento mais indicado, e é da sua linha."]
        outros = _outros_produtos(d)
        if outros:
            linhas.append(f"Se for visitar, mantenha {produto}. {outros}")
        linhas.append(_outra_linha(d))
        return "\n".join(l for l in linhas if l)

    # A visita não é certa. Em REMOVER a decisão continua sendo do propagandista,
    # então a informação vem completa e a leitura da base vem depois, nunca no
    # lugar dela.
    abertura = (
        "Se ainda assim for visitar, leve"
        if d["RECOMENDACAO"] == "REMOVER"
        else f"Se for visitar {_nome_proprio(d['NOME_MEDICO'])}, leve"
    )
    categoria = d.get("CATEGORIA_DO_PRODUTO")
    linhas = [f"{abertura} {produto}, {_um_da_categoria(categoria)} da linha {d.get('LINHA_PRODUTO')}."]
    justificativa = _JUSTIFICATIVA.get(d.get("POSICAO_DA_CATEGORIA_DO_PRODUTO") or "")
    estado = _CONVERSA[_estado_do_produto(d)].format(produto=produto)
    if justificativa:
        linhas.append(justificativa.format(classe=_classe(categoria), periodo=_do_periodo(d)))
        # "Dentro dessa categoria" prende a frase do produto à frase da
        # categoria que veio antes. Além de ligar, diz uma coisa a mais: o
        # médico pode prescrever muito na categoria e nunca ter prescrito
        # justamente o produto que o propagandista leva.
        estado = f"Dentro dessa categoria, {estado}"
    linhas.append(estado)
    if d.get("ORIGEM_DA_RECOMENDACAO") == "CATEGORIA_SIMILAR":
        linhas.append("A relação é por proximidade de categoria.")
    outros = _outros_produtos(d)
    if outros:
        linhas.append(outros)
    linhas.append(_outra_linha(d))
    linhas = [l for l in linhas if l]
    return "\n".join(linhas)


def _mes_ano(periodo: Any) -> str:
    """`202602` vira "fevereiro de 2026"."""
    texto = str(periodo)
    if len(texto) != 6 or not texto.isdigit():
        return ""
    mes = int(texto[4:])
    return f"{_MESES[mes - 1]} de {texto[:4]}" if 1 <= mes <= 12 else ""


def _data_br(valor: Any) -> str:
    texto = str(valor or "")[:10]
    partes = texto.split("-")
    return "/".join(reversed(partes)) if len(partes) == 3 else ""


def bloco_relacao(d: dict) -> str:
    """Como está a relação do propagandista com esse médico.

    Só existe para quem já está no painel. Decisão de George em 10/08/2026: a
    permanência aparece pouco, porque não entra na lista de sugestões nem no
    painel de recomendações, e só é vista quando o propagandista pergunta pelo
    médico. Então ali a resposta deve ensinar e orientar, não justificar.

    Cada linha sai de uma coluna real e some quando o dado falta. Cobertura
    medida em 10/08/2026 sobre as 647.115 linhas de permanência: ciclos no
    painel 100%, última visita 79,2%, último período na categoria 99,9%.
    """
    if d["RECOMENDACAO"] != "CONTINUAR":
        return ""

    linhas = []

    ciclos = d.get("CICLOS_NO_PAINEL_JANELA")
    if ciclos:
        inteira = " , a janela inteira que a base cobre" if ciclos >= CICLOS_DA_JANELA else ""
        plural = "ciclo" if ciclos == 1 else "ciclos"
        linhas.append(f"- No seu painel há {ciclos} {plural}{inteira}".replace(" ,", ","))

    # A data da última visita saiu daqui em 03/09/2026, no encurtamento pedido
    # por George: a mesma resposta já a traz na Memória de Visitas e o tempo
    # relativo no bloco "Tempo sem visita". Três vezes era uma a mais.
    if not d.get("DATA_ULTIMA_VISITA"):
        linhas.append("- Sem visita registrada")

    categorias, produtos = d.get("QTD_CATEGORIAS"), d.get("QTD_PRODUTOS")
    if categorias:
        alcance = f"- Prescreveu em {categorias} categorias diferentes"
        if produtos:
            alcance += f", com {produtos} produtos"
        linhas.append(alcance + f"{_janela(d)}")

    # Quando o médico prescreveu pela última vez na categoria do produto que o
    # propagandista vai levar. É o que diz se a conversa é sobre algo vivo ou
    # sobre algo que parou, e não existe em nenhum outro lugar da resposta.
    periodo = _mes_ano(d.get("ULTIMO_PERIODO_NA_CATEGORIA"))
    categoria, produto = d.get("CATEGORIA_DO_PRODUTO"), d.get("PRODUTO_RECOMENDADO")
    if periodo and categoria and produto:
        linhas.append(f"- Última prescrição em {_curto(categoria)}, a categoria do {produto}, em {periodo}")

    return "Como está a relação\n" + "\n".join(linhas)


def _dias_sem_visita(d: dict) -> Optional[int]:
    """Dias desde a última visita, contados contra hoje. `None` quando não há
    data, ela não parseia ou está no futuro, que a base trata como sem
    registro."""
    bruto = d.get("DATA_ULTIMA_VISITA")
    if not bruto:
        return None
    if isinstance(bruto, str):
        try:
            data = _date.fromisoformat(bruto[:10])
        except ValueError:
            return None
    else:
        data = bruto
    dias = (_date.today() - data).days
    return None if dias < 0 else dias


def tempo_de_visita(d: dict) -> str:
    """Texto do tempo relativo para o card do médico: "hoje", "ontem",
    "há 17 dias", "há cerca de 3 meses" ou "sem registro". Nunca lê
    `MESES_DESDE_ULTIMA_VISITA`; ver o porquê em `bloco_visita`."""
    dias = _dias_sem_visita(d)
    if dias is None:
        return "sem registro"
    if dias == 0:
        return "hoje"
    if dias == 1:
        return "ontem"
    if dias <= 60:
        return f"há {dias} dias"
    return f"há cerca de {dias // 30} meses"


def bloco_visita(d: dict) -> str:
    """Há quanto tempo esse médico não é visitado. Bloco 5 do desenho de George.

    **Calculado contra hoje, a partir de `DATA_ULTIMA_VISITA`, e nunca lido de
    `MESES_DESDE_ULTIMA_VISITA`.** Dois motivos, os dois medidos em 20/08/2026.

    O primeiro é que a coluna de meses vale **zero** quando não há data, em
    1.793.364 linhas. Exibir esse zero diria "visitado neste mês" para quem
    nunca foi visitado, que é a mentira mais fácil de acreditar nesta tela.
    A cobertura da data varia muito: 98,5% em REMOVER, 79,2% em CONTINUAR,
    17,6% em ADICIONAR e 5,5% em SEM_ACAO.

    George apontou que `tb_ranking_medicos_validacao` guarda o tempo da última
    visita. Guarda, e com as mesmas 2.565.175 linhas e a mesma cobertura de
    30,1%, mas ela tem uma coluna a mais que confirma o raciocínio acima:
    `FLAG_SEM_VISITA_REGISTRADA`. Medido em 20/08: a flag em 1 cobre exatamente
    as 1.793.364 linhas de data nula, todas com zero meses, e a flag em 0 não
    tem nenhuma data nula e ainda assim tem 70.323 zeros, que são visitas deste
    mês. "Data nula" e "flag em 1" particionam a base do mesmo jeito, então o
    cálculo aqui continua pela data, que é o que a tabela do chat traz.

    O segundo é que a coluna está ancorada na geração da tabela, e não em hoje.
    Ela foi gerada em 10/08 e diverge da conta real em exatamente um mês para
    303.976 das 771.811 linhas com data. Para quem está na porta do consultório,
    o número que importa é o de hoje.

    Em dias até dois meses, em meses depois disso: "há 3 dias" é acionável e
    "há 0 meses" não diz nada.

    Desde 03/09/2026, por pedido de George, o tempo relativo mora no card do
    médico (`last_visit`) e este bloco só existe quando há aviso de risco.
    """
    dias = _dias_sem_visita(d)
    if dias is None or dias <= 60:
        return ""

    # Aviso de risco, decisão de George em 20/08/2026. O corte é de tempo, não de
    # ranking: 17.075 linhas da base saem do painel só por ausência de visita,
    # sempre dentro do limite, às vezes na posição 1 do setor.
    linhas = ["Tempo sem visita"]
    if dias > 90:
        linhas.append(
            "- Passou de três meses sem visita. Sem retomada, o mais provável é "
            "sair do painel no próximo ciclo."
        )
    else:
        linhas.append(
            "- Passou de dois meses sem visita. Vale visitar antes que ele saia "
            "do painel por tempo, e não por potencial."
        )
    return "\n".join(linhas)


def bloco_leitura(d: dict) -> str:
    if d["RECOMENDACAO"] != "REMOVER":
        return ""
    if d.get("CRITERIO_DA_SAIDA") in ("saiu do corte", "ranking e visita"):
        return "A leitura da base é que o retorno é maior com quem está acima no ranking."
    return "O perfil continua forte e a saída vem da ausência de visita, não do potencial."


def bloco_justificativa(d: dict) -> str:
    """Por que tirar o médico do painel, com tudo que sustenta a saída.

    Só existe em remoção. Decisão de George em 10/08/2026: aqui a intenção é
    que o propagandista pare de visitar, então a resposta manda o máximo de
    informação a favor da saída, e a orientação de visita sai da frente e passa
    a depender de uma escolha explícita dele.
    """
    if d["RECOMENDACAO"] != "REMOVER":
        return ""

    criterio = d.get("CRITERIO_DA_SAIDA")
    meses = d.get("MESES_DESDE_ULTIMA_VISITA")
    linhas = []

    if criterio in ("saiu do corte", "ranking e visita"):
        linhas.append("- Caiu no ranking do seu setor e passou do limite do seu painel ideal")
    if criterio == "sem visita registrada":
        linhas.append("- Não tem nenhuma visita registrada")
    elif criterio in ("ranking e visita", "dentro do corte sem visita") and meses:
        linhas.append(f"- Não recebe visita há {meses} meses")

    ciclos = d.get("CICLOS_NO_PAINEL_JANELA")
    if ciclos:
        plural = "ciclo" if ciclos == 1 else "ciclos"
        inteira = ", a janela inteira que a base cobre" if ciclos >= CICLOS_DA_JANELA else ""
        linhas.append(f"- Ocupa uma vaga do seu painel há {ciclos} {plural}{inteira}")

    # A data da última visita só entra quando a saída tem a ver com visita. Na
    # saída por ranking ela seria o contrário de um argumento: apareceu "última
    # visita em 04/08" numa lista intitulada "por que tirar", seis dias depois
    # de o propagandista ter visitado o médico.
    visita = _data_br(d.get("DATA_ULTIMA_VISITA"))
    if visita and criterio in ("ranking e visita", "dentro do corte sem visita"):
        linhas.append(f"- Última visita em {visita}")

    linhas.append("- " + bloco_leitura(d).rstrip("."))
    return "Por que tirar\n" + "\n".join(linhas)


def narrativa(d: dict) -> str:
    """Texto completo, em parágrafos corridos.

    **Fora do chat desde 10/08/2026.** Ela alimentava um chip "Por que esse
    médico?", removido por decisão de George: o card mais os dois chips já
    explicam tudo que havia para explicar, e a narrativa repetia os dois
    inteiros, então quem tocasse nela primeiro lia a mesma coisa três vezes.

    Continua aqui porque é a forma certa para canal de texto corrido, como a
    notificação semanal por WhatsApp e e-mail, que não tem chip nem card.
    """
    partes = [bloco_decisao(d), bloco_prescricao(d), bloco_ache(d), bloco_acao(d), bloco_leitura(d)]
    return "\n\n".join(p for p in partes if p)


# --------------------------------------------------------------------------- #
# Payload de cards. Contrato do protótipo do Figma Make.
# --------------------------------------------------------------------------- #


class Card(BaseModel):
    type: Literal["doctor", "insight", "suggestions", "info-banner"]
    name: Optional[str] = None
    rank: Optional[str] = None
    score: Optional[float] = None
    status: Optional[str] = None
    summary: Optional[str] = None
    text: Optional[str] = None
    items: Optional[list[str]] = None
    # Tempo relativo da última visita ("há 17 dias", "sem registro"). Mora no
    # card, e não num bloco da mensagem, por pedido de George em 03/09/2026.
    last_visit: Optional[str] = None


class Bloco(BaseModel):
    """Um pedaço da resposta, para a tela revelar em sequência.

    A ordem é a que George definiu em 20/08/2026, e ela é de leitura e não de
    cálculo: decisão, ranking, o que ele prescreve, o que oferecer, tempo sem
    visita e, por último, o perfil de comunicação.

    Os cinco primeiros saem da mesma consulta e chegam juntos, em cerca de 1,5
    segundo. Quem encena a sequência é a tela, com intervalo curto, porque
    revelar em blocos é legível e uma parede de texto não é. O sexto chega
    depois de verdade, por `POST /agente/enriquecer`, e a tela o acrescenta
    quando ele responde.

    Pausa longa entre blocos que já estão prontos seria simular que o sistema
    pensa, roubando tempo de quem está na porta do consultório.
    """
    ordem: int
    tipo: str
    texto: str


class PerfilResponse(BaseModel):
    status: str
    mensagem: str
    cards: list[Card] = Field(default_factory=list)
    # Cada chip já vem com a resposta pronta. O toque não dispara consulta nova
    # nem chamada de modelo: é instantâneo e não pode contradizer o card acima.
    respostas: dict[str, str] = Field(default_factory=dict)
    # Ordenados, para a tela revelar um a um. Os `cards` continuam existindo
    # sem mudança: a tela atual desenha por eles, e trocar as duas coisas ao
    # mesmo tempo deixaria o portal sem resposta entre um deploy e outro.
    blocos: list[Bloco] = Field(default_factory=list)
    # A linha bruta da consulta não vai para o front. Ela tem coluna interna,
    # motivo em texto de origem e nome de coluna que não deve aparecer em
    # nenhum canal. O que o front precisa já está nos cards e em `respostas`.
    identificacao: dict = Field(default_factory=dict)


# O `ORDER BY` não é enfeite: sem ele, o mesmo dado podia devolver os chips de
# desambiguação em ordem diferente a cada consulta, e a resposta deixava de ser
# a mesma para a mesma pergunta.
#
# Os zeros à esquerda saem dos dois lados. O propagandista digita `51890` e a
# coluna guarda `PR0051890`, que virava `0051890` na comparação e não casava
# com nada. Conferido contra o banco em 10/08/2026: a busca antiga devolvia
# zero linhas para um médico que existe.
# A busca por nome passou a ser **parcial**, em 20/08/2026, e o motivo está
# medido: com igualdade, "LOESTER" devolvia zero e só "LOESTER DA SILVA NEIVA
# JUNIOR" achava. Era o defeito número 1 da rota de campo de 11/08, e ele
# continuava aqui depois de a correção do CRM ter sido feita em 10/08.
#
# A comparação usa `NOME_BUSCA` de `vw_agente_medico`, que já é maiúscula e sem
# acento, em vez de repetir a normalização nesta consulta. A view é a mesma
# superfície que o agente usa, então as duas rotas passam a achar o mesmo
# médico com o mesmo texto, o que era o ponto: a rota rápida continua rápida e
# deixa de reprovar em campo.
#
# `ORDER BY` continua sem ser enfeite: sem ele, o mesmo dado devolvia os chips
# de desambiguação em ordem diferente a cada consulta. Com busca parcial isso
# passou a valer mais, porque o número de candidatos cresceu.
SQL_LOCALIZA = (
    # Sem qualificação de catálogo: mesmo motivo de SQL_PERFIL acima.
    "SELECT v.UFCRM, v.NOME_MEDICO FROM vw_agente_medico v "
    "WHERE v.SETOR = :setor AND ("
    "   v.UFCRM = :ufcrm"
    "   OR regexp_replace(regexp_replace(v.UFCRM, '^[A-Z][A-Z]', ''), '^0+', '') = :crm"
    "   OR (:padrao <> '' AND (v.NOME_BUSCA LIKE :padrao OR upper(v.UFCRM) LIKE :padrao))) "
    "GROUP BY v.UFCRM, v.NOME_MEDICO "
    # quem está no painel primeiro, depois melhor colocado: com busca parcial o
    # propagandista costuma querer alguém do próprio painel, e o corte de 20
    # cortava por ordem de UFCRM, que não quer dizer nada para ele
    "ORDER BY MAX(CASE WHEN v.NO_PAINEL THEN 1 ELSE 0 END) DESC, "
    "         MIN(v.POSICAO_RANKING), v.UFCRM LIMIT 20"
)


def _padrao_de_busca(rota) -> str:
    """O texto que vai para o LIKE, já como a view guarda: maiúsculo, sem acento.

    **Identificador exato tem precedência sobre nome parcial.** Quando a rota traz
    UFCRM ou CRM, o padrão é vazio e a busca fica só no identificador.

    Sem essa precedência, a desambiguação virava laço infinito. O chip leva o
    UFCRM junto com o nome exatamente para o toque identificar a pessoa, mas as
    formas de busca são ligadas por `OR`: tocar em
    "Ricardo Mendonca Costa (SP0040164)" casava o UFCRM certo **e** o nome
    parcial, que também pega "Ricardo Mendonca Costa Junior". Voltavam dois
    candidatos, e os mesmos dois chips, para sempre.

    Reproduzido em 20/08/2026 com o print da tela e medido contra o banco: com o
    `OR`, dois candidatos; só pelo UFCRM, um.

    O laço é consequência da busca parcial. Com a igualdade anterior no nome
    inteiro, o nome do chip casava com uma pessoa só e o defeito não aparecia.
    """
    if rota.ufcrm or rota.crm_numero:
        return ""
    bruto = (rota.nome or rota.termo or "").strip()
    if not bruto:
        return ""
    return "%" + _sem_acento(bruto).upper() + "%"


def resolver_perfil(pergunta: str, executor, setor_autenticado: str | None = None) -> PerfilResponse:
    """Da pergunta do propagandista até a resposta pronta.

    O setor vem da identidade autenticada, nunca do texto: o que o
    propagandista escreve pode citar um setor que não é dele. O do texto só
    serve quando não há identidade, que é o caso da POC.

    Os status que não são `PERFIL_PRONTO` existem para o canal decidir o que
    fazer. `FORA_DO_ESCOPO` é o único que manda a pergunta para o LLM, e é
    assim de propósito: errar para o lado de chamar o modelo é barato, errar
    para o lado de responder com confiança a coisa errada não é.
    """
    rota = rotear(pergunta)

    # Identidade presente manda, mesmo que venha vazia. O `or` de antes caía
    # para o setor digitado quando o setor da sessão vinha em branco, e o
    # texto da pergunta passava a escolher de qual setor os dados saem.
    if setor_autenticado is not None:
        setor = setor_autenticado.strip()
    else:
        setor = rota.setor
    if not setor:
        return PerfilResponse(status="PRECISA_SETOR", mensagem="Não consegui identificar o seu setor.")

    if rota.intencao is None:
        # O `rota.motivo` é texto de depuração, do tipo "termo analitico" ou
        # "texto nao reconhecido: qual clima hoje". Ele não vai para a tela: a
        # mensagem exibida é escrita, e o motivo fica no campo de diagnóstico.
        return PerfilResponse(
            status="FORA_DO_ESCOPO",
            mensagem="Essa pergunta eu ainda não sei responder sozinho. Vou procurar nos dados.",
            identificacao={"motivo": rota.motivo},
        )

    if rota.intencao == "saudacao":
        # Resposta instantânea, sem modelo: saudação é a primeira mensagem de
        # quase todo teste, e virar busca de médico era a primeira impressão
        # do portal. Os chips são os mesmos caminhos que o agente cobre.
        return PerfilResponse(
            status="SAUDACAO",
            mensagem=(
                "Olá! Estou aqui para apoiar a sua rota. Me diga o nome ou o "
                "CRM de um médico, ou escolha um caminho:"
            ),
            cards=[Card(type="suggestions", items=[
                "Quem está com visita pendente há mais de 3 meses?",
                "Buscar um médico pelo nome",
            ])],
        )

    if rota.intencao != "briefing_medico":
        # As outras cinco intenções são reconhecidas pelo roteador e ainda não
        # têm consulta. Dizer isso é melhor do que devolver texto vazio.
        return PerfilResponse(
            status="NAO_IMPLEMENTADO",
            mensagem="Ainda não sei responder isso. Me pergunte por um médico, pelo nome ou pelo CRM.",
        )

    achados = executor.query(
        SQL_LOCALIZA,
        {
            "setor": setor,
            "ufcrm": rota.ufcrm or "",
            # Sem zeros à esquerda dos dois lados da comparação.
            "crm": (rota.crm_numero or "").lstrip("0"),
            "padrao": _padrao_de_busca(rota),
        },
    )
    if not achados:
        if rota.termo and not (rota.ufcrm or rota.crm_numero or rota.nome):
            # O identificador veio da heurística de sobra de palavras, não de
            # um dado explícito. O teste de 30/08/2026 mostrou o que cai aqui:
            # "quero a lista de pendências" e "quero a segunda opção" viravam
            # busca por um médico chamado "lista pendências" e morriam em
            # "não encontrei ninguém". Continuação de conversa desce para o
            # agente, que tem o histórico e as ferramentas.
            return PerfilResponse(
                status="FORA_DO_ESCOPO",
                mensagem="Essa pergunta eu ainda não sei responder sozinho. Vou procurar nos dados.",
                identificacao={"motivo": f"termo sem correspondencia: {rota.termo}"},
            )
        return PerfilResponse(
            status="MEDICO_NAO_ENCONTRADO",
            mensagem=(
                "Não encontrei ninguém com esse dado no seu setor. Confira o "
                "nome ou o CRM. Também posso ajudar de outras formas."
            ),
            cards=[Card(type="suggestions", items=[
                "Quem está com visita pendente há mais de 3 meses?",
                "Buscar um médico pelo nome",
            ])],
        )
    if len(achados) > 1:
        # Medido em 10/08/2026: dentro do mesmo setor, 856 CRMs sem UF e 2.394
        # nomes apontam para mais de um médico. É pouco, mas escolher um deles
        # em silêncio seria responder sobre a pessoa errada.
        # O chip leva o UFCRM junto com o nome, e não só o nome. Dois médicos
        # homônimos no mesmo setor geravam dois chips idênticos, e tocar num
        # deles repetia a mesma pergunta ambígua para sempre. Com o UFCRM no
        # rótulo, o toque já identifica a pessoa e ainda distingue as duas na
        # tela. São 2.394 nomes repetidos dentro do mesmo setor, medido em
        # 10/08/2026.
        opcoes = [f"{_nome_proprio(a['NOME_MEDICO'])} ({a['UFCRM']})" for a in achados]
        return PerfilResponse(
            status="MEDICO_AMBIGUO",
            mensagem="Encontrei mais de uma pessoa com esse dado no seu setor. Qual delas?",
            cards=[Card(type="suggestions", items=opcoes)],
        )

    parametros = {"setor": setor, "ufcrm": achados[0]["UFCRM"]}
    linhas = executor.query(SQL_PERFIL, parametros)
    if not linhas:
        return PerfilResponse(
            status="MEDICO_NAO_ENCONTRADO",
            mensagem=(
                "Não encontrei ninguém com esse dado no seu setor. Confira o "
                "nome ou o CRM. Também posso ajudar de outras formas."
            ),
            cards=[Card(type="suggestions", items=[
                "Quem está com visita pendente há mais de 3 meses?",
                "Buscar um médico pelo nome",
            ])],
        )

    dados = dict(linhas[0])

    # Falha aqui não derruba a resposta: sem o perfil o card volta ao resumo de
    # prescrição, que é o comportamento anterior. Um médico sem segmentação é
    # caso normal, não erro: 21% da base está como A DEFINIR.
    # As três consultas de enriquecimento são independentes e leem tabelas
    # diferentes. Em série somam mais de vinte segundos; em paralelo o custo é o
    # da mais lenta, cerca de nove. Cada uma abre a própria conexão, então não
    # há estado compartilhado entre elas.
    #
    # Nenhuma delas é obrigatória: falha ou ausência deixa o bloco
    # correspondente de fora, e a resposta continua saindo.
    extras = {
        "PERFIL_COMUNICACAO": None,
        "PERFIL_ORIGEM": None,
        "MERCADOS": [],
        "OPORTUNIDADES": [],
    }

    def _segmentacao():
        linhas_seg = executor.query(SQL_SEGMENTACAO, parametros)
        if linhas_seg:
            extras["PERFIL_COMUNICACAO"] = linhas_seg[0].get("perfil_efetivo")
            extras["PERFIL_ORIGEM"] = linhas_seg[0].get("origem_do_valor")

    def _mercados():
        extras["MERCADOS"] = executor.query(SQL_MERCADOS_DO_MEDICO, parametros)

    def _oportunidades():
        extras["OPORTUNIDADES"] = executor.query(SQL_OPORTUNIDADE, parametros)

    with _ThreadPoolExecutor(max_workers=3) as pool:
        for futuro in [pool.submit(f) for f in (_segmentacao, _mercados, _oportunidades)]:
            try:
                futuro.result()
            except Exception:
                logger.exception("Falha em uma das consultas de enriquecimento.")

    dados.update(extras)
    return montar_payload(dados)


def montar_blocos(d: dict) -> list[Bloco]:
    """Os cinco primeiros blocos, na ordem de leitura definida por George.

    O sexto, o perfil de comunicação, não sai daqui: ele vem de
    `POST /agente/enriquecer` e a tela o acrescenta quando responde. Separar os
    dois é o que evita segurar cinco blocos prontos esperando o que demora.

    Bloco vazio não entra. Um médico sem prescrição registrada não deve receber
    um cabeçalho seguido de nada, e a tela não precisa saber disso.
    """
    candidatos = [
        ("decisao", bloco_decisao(d)),
        ("ranking", bloco_ranking(d)),
        ("oferecer", bloco_o_que_levar(d)),
        ("oportunidade", bloco_oportunidade(d)),
        ("visita", bloco_visita(d)),
    ]
    blocos, ordem = [], 0
    for tipo, texto in candidatos:
        if not (texto or "").strip():
            continue
        ordem += 1
        blocos.append(Bloco(ordem=ordem, tipo=tipo, texto=texto.strip()))
    return blocos


def bloco_ranking(d: dict) -> str:
    """Posição e pontuação, com a leitura de que isso significa. Bloco 2.

    O número do corte do painel **não** aparece, e a decisão é de 09 e 10/08:
    só 12 dos 2.153 setores tinham painel de exatamente 400, e desde 17/08 o
    corte deixou de ser um número único e passou a ser o limite que o GD define
    por propagandista. Citar um número aqui teria virado defeito.
    """
    posicao = d.get("POSICAO_RANKING_SETOR")
    if posicao is None:
        return ""
    linhas = [f"- Posição {posicao} no seu setor"]

    # Sem casas decimais, pedido de George em 03/09/2026: "100.500,22" não diz
    # mais que "100.500" e alonga o número.
    pontos = d.get("PONTOS")
    if pontos is not None:
        linhas.append(f"- {float(pontos):,.0f} pontos".replace(",", "."))

    # `QTD_MEDICOS_PAINEL_SETOR` fica de fora, e por dois motivos medidos em
    # 20/08/2026.
    #
    # O primeiro é que a posição é sobre o **setor inteiro** e não sobre o
    # painel: num setor de teste, 10.636 médicos e 523 no painel. Escrever
    # "posição 401 entre 375 do seu painel" é contraditório, e isso acontece em
    # 1.691.886 das 2.565.175 linhas, dois terços da base.
    #
    # O segundo é a regra 6 de `como-alterar-a-resposta-do-chat.md`: o texto
    # nunca cita o número do corte do painel. Desde 17/08 esse corte deixou de
    # ser um número único e virou o limite que o GD define por propagandista,
    # então citar qualquer número aqui envelhece mal.
    return "Onde ele está no seu ranking\n" + "\n".join(linhas)


def montar_payload(d: dict) -> PerfilResponse:
    """Monta a resposta em cards. Função pura: mesmo dado, mesma saída."""
    # O card passa a mostrar o perfil de comunicação, e não o resumo de
    # prescrição. Decisão de George em 20/08/2026. O resumo antigo repetia, em
    # outro formato, o que o bloco "o que mais prescreve" já dizia logo abaixo,
    # e o perfil responde outra coisa: como conduzir a conversa com aquele
    # médico. É o mesmo perfil que a gaveta do Ranking edita.
    #
    # A ressalva de 10/08 continua: o card não pode ser factual a ponto de o
    # propagandista agir sem o porquê. Por isso a origem aparece junto, e ele
    # distingue a própria leitura da que veio da base.
    perfil = d.get("PERFIL_COMUNICACAO")
    if perfil and perfil != "A DEFINIR":
        origem = {
            "propagandista": "definido por você",
            "salesfarma": "sugerido pela base",
        }.get(d.get("PERFIL_ORIGEM") or "", "")
        resumo = f"Perfil {_maiuscula_inicial(perfil.lower())}"
        resumo += f", {origem}." if origem else "."
    else:
        # Sem segmentação é caso normal, não erro: 21% da base está como
        # A DEFINIR. O card volta ao resumo de prescrição, que é melhor que
        # espaço vazio.
        cats = _categorias(d)
        if cats:
            resumo = f"Prescreve principalmente {cats[0]['categoria']}"
            if cats[0]["pct"] is not None:
                resumo += f", {_pct(cats[0]['pct'])}% do volume"
            resumo += "."
        else:
            resumo = "Sem prescrição registrada no período."

    cards: list[Card] = [
        Card(
            type="doctor",
            name=_nome_proprio(d["NOME_MEDICO"]),
            rank=f"#{d['POSICAO_RANKING_SETOR']} no setor",
            score=float(d["PONTOS"]) if d.get("PONTOS") is not None else None,
            # Valor fora do mapa não vai cru para a tela. Hoje a tabela só tem
            # os quatro mapeados, medido em 10/08/2026, mas o código não pode
            # depender disso.
            status=_STATUS.get(d["RECOMENDACAO"], "Sem classificação"),
            summary=resumo,
            last_visit=tempo_de_visita(d),
        ),
        Card(type="insight", text=bloco_ache(d).replace("\n", " ")),
    ]

    produto = d.get("PRODUTO_RECOMENDADO")
    if not produto and not d.get("PRODUTO_ACHE_OUTRA_LINHA"):
        cards.append(
            Card(
                type="info-banner",
                text=f"Não há recomendação de produto para {_nome_proprio(d['NOME_MEDICO'])}.",
            )
        )

    tem_produto = bool(produto or d.get("PRODUTO_ACHE_OUTRA_LINHA"))
    relacao = bloco_relacao(d)
    justificativa = bloco_justificativa(d)

    # Sem chips de sugestão de continuação, decisão de George em 20/08/2026.
    # A resposta passou a vir inteira, em blocos, então o chip oferecia de novo
    # o que a pessoa acabou de ler. `tem_produto` deixa de ser usado aqui e
    # continua valendo para o banner de "não há recomendação de produto".
    chips = [CHIP_POR_QUE_TIRAR] if justificativa else []
    chips += [CHIP_PRESCREVE]
    if tem_produto:
        chips.append(CHIP_MANTER if justificativa else CHIP_VISITA)
    if relacao and not justificativa:
        chips.append(CHIP_RELACAO)

    respostas = {
        CHIP_VISITA: bloco_acao(d),
        CHIP_MANTER: bloco_acao(d),
        CHIP_PRESCREVE: bloco_prescricao(d),
        CHIP_RELACAO: relacao,
        CHIP_POR_QUE_TIRAR: justificativa,
    }

    return PerfilResponse(
        status="PERFIL_PRONTO",
        mensagem=bloco_decisao(d),
        cards=cards,
        blocos=montar_blocos(d),
        # Só o que é oferecido. Mandar resposta de chip que não aparece é peso
        # no payload e convite a exibir texto que a tela decidiu não mostrar.
        respostas={chip: respostas[chip] for chip in chips},
        identificacao={
            "ufcrm": d.get("UFCRM"),
            "nome_medico": d.get("NOME_MEDICO"),
            "linha_produto": d.get("LINHA_PRODUTO"),
        },
    )
