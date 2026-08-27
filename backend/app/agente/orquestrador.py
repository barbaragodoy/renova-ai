"""O laço de ferramentas, e o que acontece quando o modelo escreve um número inventado.

Sequência de uma pergunta:

1. o backend resolve o contexto pela identidade autenticada;
2. o modelo recebe a pergunta e o catálogo de ferramentas, sem nenhum dado;
3. cada ferramenta que ele pedir é executada aqui, com o setor injetado;
4. o retorno volta para o modelo, que decide se pede mais ou se responde;
5. o texto final passa pelo verificador antes de sair.

O passo 5 é o que separa este desenho de um chat com acesso ao banco. Se o
texto cita número que não veio de ferramenta, o agente recebe o apontamento e
reescreve uma vez. Se reincidir, a resposta é degradada por remoção das frases
com número sem origem, que é o que a T1.2 pede.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.app.agente import composicao, intencao
from backend.app.agente.composicao import Chamada
from backend.app.agente.ferramentas import Contexto, Ferramentas

logger = logging.getLogger(__name__)


def _hash_do_resultado(resultado: list[dict]) -> str:
    """sha256 do retorno canonicalizado. Permite comparar duas execucoes sem guardar o resultado."""
    bruto = json.dumps(resultado, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


def _via(usadas: list[str], texto: str) -> str:
    """Qual via serviu a interacao. Dominio fechado pela CHECK constraint da tabela."""
    if not usadas:
        return "recusa"
    if all(f == "buscar_conhecimento" for f in usadas):
        return "conhecimento"
    return "via_1"


def _documentos_de(resultado: list[dict]) -> list[tuple[str, list[str]]]:
    """Os arquivos citados, com os hashes das passagens de cada um."""
    achados: list[tuple[str, list[str]]] = []
    vistos = set()
    for linha in resultado or []:
        if not isinstance(linha, dict):
            continue
        trechos = linha.get("trechos") or {}
        for doc in linha.get("documentos") or []:
            if doc in vistos:
                continue
            vistos.add(doc)
            h = trechos.get(doc) or []
            achados.append((doc, [h] if isinstance(h, str) else list(h)))
    return achados


def texto_da_mensagem(msg: dict) -> str:
    """O endpoint devolve `content` como string ou como lista de blocos.

    A forma de lista aparece de forma intermitente na mesma pergunta, entao
    tratar so a string quebrava uma resposta a cada tres mais ou menos.
    """
    bruto = (msg or {}).get("content")
    if isinstance(bruto, str):
        return bruto.strip()
    if isinstance(bruto, list):
        partes = [b.get("text", "") for b in bruto
                  if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in partes if p).strip()
    return ""

MAX_VOLTAS = 6          # teto de idas ao modelo dentro de uma pergunta
MAX_REESCRITAS = 1      # quantas vezes o modelo pode corrigir o próprio número


@dataclass
class Resposta:
    texto: str
    ferramentas_usadas: list[str] = field(default_factory=list)
    documentos_citados: list[str] = field(default_factory=list)
    trechos_citados: dict = field(default_factory=dict)
    degradada: bool = False
    motivo_degradacao: str = ""
    voltas: int = 0
    ms: int = 0
    # material do log, montado durante a interacao e nao reconstruido depois
    chamadas: list[Chamada] = field(default_factory=list)
    chamadas_modelo: list[dict] = field(default_factory=list)
    veredito: Any = None
    ms_modelo: int = 0
    ms_consulta: int = 0
    pergunta: str = ""
    via: str = "via_1"

    def resumo_para_log(self) -> dict[str, Any]:
        """O que vai para `tb_agente_log`. Sem texto de pergunta nem de resposta."""
        return {
            "ferramentas": ",".join(self.ferramentas_usadas),
            "qtd_ferramentas": len(self.ferramentas_usadas),
            # critério de aceite da T1.3: a resposta de conhecimento cita o
            # documento de origem no log. Só o nome do arquivo, nunca o trecho.
            "documentos": ",".join(self.documentos_citados),
            "custo_moeda": (self.chamadas_modelo or [{}])[0].get("moeda", ""),
            "degradada": self.degradada,
            "motivo_degradacao": self.motivo_degradacao,
            "voltas": self.voltas,
            "duracao_ms": self.ms,
        }


class Orquestrador:
    def __init__(self, contexto: Contexto, executor, modelo, conhecimento=None, schema: str | None = None):
        self.ctx = contexto
        self.modelo = modelo
        self.ferramentas = Ferramentas(
            contexto, executor, conhecimento=conhecimento,
            **({"schema": schema} if schema else {}),
        )
        self._por_nome = {f.nome: f for f in self.ferramentas.catalogo()}
        self._declaracoes = [f.declaracao() for f in self.ferramentas.catalogo()]

    # ----------------------------------------------------------------

    def responder(self, pergunta: str) -> Resposta:
        t0 = time.time()
        registro_chamadas: list[Chamada] = []
        registro_modelo: list[dict] = []
        ms_modelo = 0
        mensagens: list[dict] = [
            {"role": "system", "content": composicao.INSTRUCAO},
            {"role": "user", "content": pergunta},
        ]
        usadas: list[str] = []
        documentos: list[str] = []
        trechos: dict[str, str] = {}
        voltas = 0

        texto = ""
        while voltas < MAX_VOLTAS:
            voltas += 1
            tm = time.time()
            volta = self.modelo.conversar(mensagens, self._declaracoes)
            ms_modelo += int((time.time() - tm) * 1000)
            msg = volta.mensagem if hasattr(volta, "mensagem") else volta
            if hasattr(volta, "para_log"):
                registro_modelo.append(volta.para_log(f"m{voltas}"))
            chamadas = msg.get("tool_calls") or []

            if not chamadas:
                texto = texto_da_mensagem(msg)
                break

            mensagens.append({
                "role": "assistant",
                "content": texto_da_mensagem(msg),
                "tool_calls": chamadas,
            })
            for i, chamada in enumerate(chamadas):
                tf = time.time()
                nome, resultado, argumentos = self._executar(chamada)
                ms_ferramenta = int((time.time() - tf) * 1000)
                deu_certo = not (len(resultado) == 1 and "erro" in resultado[0])
                registro_chamadas.append(Chamada(
                    chamada_id=f"f{voltas}_{i}", ferramenta=nome, linhas=resultado,
                    resultado_hash=_hash_do_resultado(resultado),
                    parametros=json.dumps(argumentos, ensure_ascii=False, sort_keys=True,
                                          default=str),
                    latencia_ms=ms_ferramenta, sucesso=deu_certo))
                usadas.append(nome)
                for doc, hashes in _documentos_de(resultado):
                    if doc not in documentos:
                        documentos.append(doc)
                    trechos.setdefault(doc, [])
                    for h in hashes:
                        if h and h not in trechos[doc]:
                            trechos[doc].append(h)
                mensagens.append({
                    "role": "tool",
                    "tool_call_id": chamada.get("id"),
                    "content": json.dumps(resultado, ensure_ascii=False, default=str),
                })
        else:
            logger.warning("agente: teto de %s voltas atingido", MAX_VOLTAS)

        resposta = self._fechar(texto, registro_chamadas, mensagens, usadas, voltas,
                                registro_modelo)
        resposta.documentos_citados = documentos
        resposta.trechos_citados = trechos
        resposta.chamadas = registro_chamadas
        resposta.chamadas_modelo = registro_modelo
        resposta.ms_modelo = ms_modelo
        resposta.ms_consulta = sum(c.latencia_ms for c in registro_chamadas)
        resposta.pergunta = pergunta
        resposta.via = _via(usadas, resposta.texto)
        resposta.ms = int((time.time() - t0) * 1000)
        return resposta

    def entidades_resolvidas(self, chamadas: list[Chamada]) -> list[str]:
        """Nomes que as ferramentas resolveram, para a normalizacao da intencao."""
        nomes = []
        for ch in chamadas:
            for linha in ch.linhas:
                nome = linha.get("NOME_MEDICO") if isinstance(linha, dict) else None
                if nome and nome not in nomes:
                    nomes.append(nome)
        return nomes

    # ----------------------------------------------------------------

    def _executar(self, chamada: dict) -> tuple[str, list[dict], dict]:
        nome = (chamada.get("function") or {}).get("name", "")
        bruto = (chamada.get("function") or {}).get("arguments") or "{}"
        try:
            argumentos = json.loads(bruto) if isinstance(bruto, str) else dict(bruto)
        except json.JSONDecodeError:
            argumentos = {}

        ferramenta = self._por_nome.get(nome)
        if ferramenta is None:
            # o modelo inventou um nome de ferramenta: devolver o erro para ele
            # em vez de estourar, porque ele costuma se corrigir na volta seguinte
            return nome, [{"erro": f"ferramenta '{nome}' não existe"}], {}

        try:
            return nome, ferramenta.executar(**argumentos), argumentos
        except TypeError as exc:
            return nome, [{"erro": f"argumentos inválidos para {nome}: {exc}"}], {}
        except Exception as exc:  # noqa: BLE001
            logger.exception("agente: falha na ferramenta %s", nome)
            return nome, [{"erro": f"a consulta de {nome} falhou"}], {}

    # ----------------------------------------------------------------

    def _fechar(self, texto, chamadas_ferramenta, mensagens, usadas, voltas,
                registro_modelo) -> Resposta:
        if not texto:
            r = Resposta(composicao.MENSAGEM_SEM_RESPOSTA_CONFIAVEL, usadas,
                         degradada=True, motivo_degradacao="modelo não produziu texto",
                         voltas=voltas)
            r.veredito = composicao.verificar(r.texto, chamadas_ferramenta)
            return r

        veredito = composicao.verificar(texto, chamadas_ferramenta)
        if veredito.aprovado:
            r = Resposta(texto, usadas, voltas=voltas)
            r.veredito = veredito
            return r

        # uma chance de o próprio modelo se corrigir, com o apontamento explícito
        for _ in range(MAX_REESCRITAS):
            voltas += 1
            logger.warning("agente: reescrita pedida. %s", veredito.motivo)
            mensagens.append({"role": "assistant", "content": texto})
            mensagens.append({
                "role": "user",
                "content": (
                    "A resposta anterior não passou na verificação: "
                    f"{veredito.motivo}. "
                    "Reescreva usando apenas os valores que as ferramentas devolveram, "
                    "sem arredondar e sem converter. Se um número não veio de ferramenta, "
                    "tire a afirmação inteira em vez de estimar."
                ),
            })
            volta = self.modelo.conversar(mensagens, self._declaracoes)
            msg = volta.mensagem if hasattr(volta, "mensagem") else volta
            if hasattr(volta, "para_log"):
                registro_modelo.append(volta.para_log(f"m{voltas}"))
            novo = texto_da_mensagem(msg)
            if not novo:
                break
            texto = novo
            veredito = composicao.verificar(texto, chamadas_ferramenta)
            if veredito.aprovado:
                r = Resposta(texto, usadas, voltas=voltas)
                r.veredito = veredito
                return r

        # reincidiu: degrada por remoção da frase, não da resposta inteira
        limpo = composicao.degradar(texto, veredito)
        motivo = veredito.motivo
        if not limpo:
            limpo = composicao.MENSAGEM_SEM_RESPOSTA_CONFIAVEL
        r = Resposta(limpo, usadas, degradada=True, motivo_degradacao=motivo, voltas=voltas)
        # o veredito e refeito sobre o texto **entregue**: o contrato exige que
        # todo numero em numeros_exibidos tenha linha de verificacao, e o texto
        # degradado ja nao tem os numeros sem origem
        r.veredito = composicao.verificar(limpo, chamadas_ferramenta)
        return r
