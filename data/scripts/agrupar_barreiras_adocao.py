"""Consolida, após a extração, as barreiras candidatas da passada S."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from barreiras_comum import chave, ler_jsonl  # noqa: E402
from descobrir_barreiras_adocao_piloto import PROMPT_INICIAL  # noqa: E402


DESTINO = Path("docs/analises/barreiras_adocao_piloto")


def normalizar(texto: str) -> str:
    texto = "".join(c for c in unicodedata.normalize("NFD", texto.lower())
                    if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", texto)


# Vocabulário criado depois da leitura das 1.000 formulações brutas distintas.
# Uma formulação composta pode entrar em mais de uma barreira.
REGRAS = {
    "BAIXA_LEMBRANCA": r"lembr|esquec|record|memori|fixou|fixar|fixad|\bfixa\b|nao decorou|pegou bem a marca|associa bem as marcas|marca.*mente|mente.*marca",
    "CUSTO_ACESSIBILIDADE": r"cust|preco|financeir|poder aquisitivo|\bcar[oa]s?\b|acessivel|acessibilidade|baixa renda|valor alto|valor do produto",
    "DISPONIBILIDADE_ESTOQUE": r"disponib|estoque|desabaste|abastecimento|falta do produto|falta na farm|nao encontr|localizar o produto|encontrar (o produto|a marca|o creme)|dificuldade.*encontrar|deslocar para outra cidade|materia prima",
    "AMOSTRAS": r"amostra|\bags\b|ag s",
    "PRESCRICAO_MOLECULA_GENERICO": r"generico|pela molecula|por molecula|pela substancia|por substancia|prescreve apenas moleculas|nome comercial|prescricao da marca|colocar a marca|marca no receituario|prescricao por moleculas",
    "PREFERENCIA_TERAPEUTICA_CONCORRENTE": r"concorrent|outra marca|marca de preferencia|preferencia por|prefere |preferind|opta por|em vez d|outras classes|outra medica|outro antituss|primeira opcao|prioriza|alterna com|nao substitui|mantem receita|reserva para|parceiros|mais frequente que|nao sendo molecula de escolha",
    "FALTA_EXPERIENCIA_INCORPORACAO": r"experien|ainda nao test|nao test|ainda nao utiliz|nao utilizou|nao iniciou|iniciar prescrever|primeiro contato|familiar|incorpor|pratica com|pratica clinica|avaliar mais|ainda avaliando|ainda nao aderiu|nao .*habitu|acostumar|formar parecer|portifolio|ainda nao conseguiu avaliar|testar em mais|ainda nao teve retorno",
    "HABITO_PROTOCOLO": r"habito|costume|rotina|protocolo|diretriz|guideline|padrao prescr|conduta|receita padrao",
    "DUVIDA_CONHECIMENTO": r"duvid|desconhec|nao conhec|pouco conhec|falta de conhec|manejo|receituario|nao sabia|nao sabe|nao domina|confus|confund|entender melhor|nao tinha conhecimento|conhece pouco",
    "EFICACIA_EVIDENCIA": r"eficac|efetiv|evidenc|resultado|beneficio|nao acredita|comprov|efeito terapeut|resposta clinic|confianca|estudo|nao ve valor|inferior|sem melhora",
    "SEGURANCA_TOLERABILIDADE": r"segur|efeito advers|colater|intoler|reac|receio|medo|risco|contraind|intera[cç]|retencao|toler|diarreia|constipa|acne|lactose|absor[cç]ao",
    "FORMULACAO_APRESENTACAO": r"apresenta[cç]|formula|formula[cç]|dose|dosagem|posolog|comprim|capsul|gota|spray|sache|liquid|isolad|combinad|associa[cç]|via |peso molecular|quantidade de agonista|classe b",
    "PERFIL_POUCA_OPORTUNIDADE": r"pouc.*oportun|pouc.*pacient.*perfil|sem oportun|nao tem (muita |qualquer )?oportun|falta.*oportun|faltou oportunidade|ainda nao teve oportunidade|nao surgem oportunidades|oportunidade.*(limit|reduz)|reduz.*oportun|perfil (de pacient|atendido|prescritivo)|perfil.*limit|nao atende|nao tem atendido|nao tem tido pacientes|nao trata|baixa demanda|faixa etaria|casos? (especific|rar)|nao e rotina clinic|restrit.*pacient|indica pouco|pouco indica|prescri[cç]ao.*pouc|raramente prescrev|nao possui perfil|nao prescreve muita|nao tem casos|baixo volume|foco .* reduz|nao e o foco|fora da area|apenas como|linha .* nao entra|nao esta mais fazendo|sem presen[cç]a consistente|ocasionalmente|nao costuma indicar|pacientes.*menor|produto mais adequado para pacientes|dificuldade de atender.*pacientes com perfil",
    "RESTRICAO_INSTITUCIONAL": r"hospital|sus|rede publica|posto|sistema|padroniza|farmacia popular|servico publico|normas da rede|\bubs\b|farmacia basica|nao pode prescrever",
    "RESISTENCIA_INTERESSE_MEDICO": r"medic.*resisten|resisten.*(marca|prescri|adot|usar|produto)|resistencia (ao|a) (produto|marca|uso|tramadol|suplementos)|nao gosta|nao demonstr.*interesse|pouco aberto|pouca abertura|recusa|nao quer|nao considera|nao ve vantagem|fechado a mudar|sem certeza se vai|nao concorda|relutancia|nao quis|nao tem muita confianca",
    "ADESAO_PERCEPCAO_PACIENTE": r"pacient.*(nao|recus|acha|medo|pref|question|resisten|automedic|ades|reclam)|familia.*resisten|resistencia da familia|adesao (do|das|de) pacient|aceita[cç]ao (do|das|de) pacient|receitas devolvidas|dificuldade de adesao",
    "SUBSTITUICAO_FARMACIA": r"troca.*farm|farmacia.*troca|trocad.*farm|trocas do medicamento|receita.*trocada|relata troca|substitui[cç]ao por generico",
    "BARREIRA_CLINICA_ESPECIFICA": r"nao inicia tratamento|nao costuma iniciar tratamento|nao utiliza antiinflam|nao usa carmelose|nao associa probi|nao costuma associar|nao prescreve de primeira|nao prescreve medicamentos|nao quis carimbo|dificuldades com a marca|mais dificil prescrever|dificuldade de tratamento|produto nao estava no port|nao e sua marca de escolha|nao esta entre as primeiras opcoes|restrito ao uso|nao prescreve produtos a base",
    "CONTEXTO_DA_VISITA": r"limitou o tempo disponivel|desnecessario cadastrar|agenda com nossas marcas",
}

ROTULOS = {
    "BAIXA_LEMBRANCA": "Baixa lembrança da marca",
    "CUSTO_ACESSIBILIDADE": "Custo ou baixa acessibilidade financeira",
    "DISPONIBILIDADE_ESTOQUE": "Baixa disponibilidade ou desabastecimento",
    "AMOSTRAS": "Falta ou desequilíbrio de amostras",
    "PRESCRICAO_MOLECULA_GENERICO": "Prescrição por molécula ou genérico em vez da marca",
    "PREFERENCIA_TERAPEUTICA_CONCORRENTE": "Preferência terapêutica ou por concorrente já estabelecida",
    "FALTA_EXPERIENCIA_INCORPORACAO": "Falta de experiência ou incorporação à prática",
    "HABITO_PROTOCOLO": "Hábito, protocolo ou diretriz consolidada",
    "DUVIDA_CONHECIMENTO": "Dúvida ou desconhecimento técnico",
    "EFICACIA_EVIDENCIA": "Dúvida sobre eficácia, benefício ou evidência",
    "SEGURANCA_TOLERABILIDADE": "Receio de segurança ou tolerabilidade",
    "FORMULACAO_APRESENTACAO": "Preferência ou limitação de formulação, apresentação ou posologia",
    "PERFIL_POUCA_OPORTUNIDADE": "Baixa oportunidade clínica ou desalinhamento com o perfil atendido",
    "RESTRICAO_INSTITUCIONAL": "Restrição institucional ou da rede de atendimento",
    "RESISTENCIA_INTERESSE_MEDICO": "Resistência ou baixo interesse do médico",
    "ADESAO_PERCEPCAO_PACIENTE": "Resistência, percepção ou adesão do paciente",
    "SUBSTITUICAO_FARMACIA": "Substituição da marca após a prescrição na farmácia",
    "BARREIRA_CLINICA_ESPECIFICA": "Restrição clínica específica à adoção",
    "CONTEXTO_DA_VISITA": "Limitação do contexto da visita, sem barreira de adoção",
    "OUTRA_ESPECIFICA": "Outra barreira específica",
}

EXCLUIDAS_DA_LISTA = {
    "PERFIL_POUCA_OPORTUNIDADE", "SUBSTITUICAO_FARMACIA", "CONTEXTO_DA_VISITA",
}

EXEMPLOS_CURADOS = {
    "BAIXA_LEMBRANCA": [
        "não lembra da marca nas oportunidades de prescrição",
        "dificuldade em memorizar o nome da marca",
        "falta de lembrança da marca no momento da prescrição",
    ],
    "PREFERENCIA_TERAPEUTICA_CONCORRENTE": [
        "prescreve concorrente devido a campanha promocional de compre um ganhe outro",
        "médico tem hábito de prescrever pela substância ou marca concorrente, precisa associar a marca",
        "dá preferência ao concorrente Puran em vez de Levoid em casos de hipotireoidismo",
    ],
    "CUSTO_ACESSIBILIDADE": [
        "custo alto dificulta prescrição para população carente",
        "custo elevado do produto pode afetar adesão do paciente",
        "concorrente considerado mais acessível (preço)",
    ],
    "FORMULACAO_APRESENTACAO": [
        "prefere fórmulas isoladas e clean label, não gosta de combinadas",
        "Preferia a apresentação líquida para titular dose em pacientes novos e idosos com dificuldade de deglutição, e questiona a mudança para tablete",
        "ausência da apresentação de 60 mg, considerada diferencial importante",
    ],
    "HABITO_PROTOCOLO": [
        "médicos seguem protocolo antigo de suplementação",
        "não tem hábito de prescrever a dose de 38mcg, prescreve 25mcg e 50mcg",
        "produto ainda não está no hábito de prescrição do médico",
    ],
    "PERFIL_POUCA_OPORTUNIDADE": [
        "poucos pacientes com perfil para o produto, limitando a prescrição",
        "não surgem oportunidades com frequência para prescrever",
        "médico não possui perfil prescritivo para a linha respiratória nem para os produtos citados",
    ],
    "DUVIDA_CONHECIMENTO": [
        "médica precisa ser lembrada mais vezes e demonstra pouco conhecimento dos produtos",
        "confusão na prescrição pela quantidade de marcas e indicações da família de produtos",
        "precisa entender melhor o mecanismo do produto antes de adotar",
    ],
    "FALTA_EXPERIENCIA_INCORPORACAO": [
        "não tem muita experiência com o produto",
        "marca ainda não está incorporada na prática diária do médico",
        "ainda não tem experiência prática com canabidiol e não teve oportunidade de usar o produto na prática clínica",
    ],
    "RESTRICAO_INSTITUCIONAL": [
        "sistema hospitalar exige prescrição por molécula, dificultando uso do nome comercial",
        "na UBS não pode prescrever a marca",
        "prescrição segue normas da rede, priorizando moléculas disponíveis (FP) em vez do produto",
    ],
    "SEGURANCA_TOLERABILIDADE": [
        "objeção ao uso em pacientes com intolerância à lactose",
        "pacientes sensíveis apresentam reações adversas exacerbadas a esse medicamento, levando a uso mais restrito",
        "preocupação com a quantidade de lactose na losartana",
    ],
    "PRESCRICAO_MOLECULA_GENERICO": [
        "Prescreve apenas moléculas devido ao custo",
        "não tem costume de colocar a marca no receituário",
        "Prescreve pela substância, não pela marca, e precisa de amostras para lembrar da marca",
    ],
    "DISPONIBILIDADE_ESTOQUE": [
        "preocupação com falta do produto impede retomar a prescrição",
        "farmácias desabastecidas do produto, dificultando pacientes obterem a medicação prescrita",
        "pacientes não encontraram o produto disponível e compraram concorrente",
    ],
    "ADESAO_PERCEPCAO_PACIENTE": [
        "pacientes já se automedicam com amoxicilina/clavulanato antes da consulta, levando a preferir outras opções",
        "Pacientes resistem à forma líquida, dificultando adesão",
        "dificuldade de adesão das pacientes ao tratamento",
    ],
    "AMOSTRAS": [
        "Não prescreve os antibióticos porque não recebe amostras, enquanto recebe de concorrentes",
        "concorrente deixa mais amostras, o que leva a prescrever mais o concorrente",
        "maior volume de amostras do concorrente influencia preferência por ele em vez da duloxetina",
    ],
    "EFICACIA_EVIDENCIA": [
        "não tem muita confiança ainda no produto no Brasil",
        "Percepção de falta de estudos robustos sobre canabidiol em psiquiatria",
        "considera que a droga não atinge outras partes do corpo e falta estudo específico/robusto",
    ],
    "RESISTENCIA_INTERESSE_MEDICO": [
        "não gosta da classe do produto",
        "médico fechado a mudar prescrição, alega que produto tem atuação apenas de concorrência",
        "médica ainda sem certeza se vai prescrever o produto",
    ],
    "BARREIRA_CLINICA_ESPECIFICA": [
        "não inicia tratamento para asma, apenas resgate na emergência, pois entende pacientes já diagnosticados por outro médico",
        "não costuma iniciar tratamento para ansiedade e depressão, limitando oportunidade para Exodus",
        "não prescreve de primeira, reserva para casos refratários, priorizando repositor de flora antes",
    ],
}


def categorias(barreira: str) -> set[str]:
    texto = normalizar(barreira)
    achadas = {codigo for codigo, padrao in REGRAS.items() if re.search(padrao, texto)}
    return achadas or {"OUTRA_ESPECIFICA"}


def piloto_original() -> list[dict]:
    rows = ler_jsonl(DESTINO / "extracoes_piloto.jsonl")
    por_chave = {x["chave"]: x for x in rows}
    return [x for x in por_chave.values()
            if x["chave"] == chave(PROMPT_INICIAL, x["comentario"])
            and x.get("tem_barreira")]


def main() -> None:
    dados = json.loads((DESTINO / "fonte_snapshot.json").read_text(encoding="utf-8"))
    nomes = [c["name"] for c in dados["schema"]]
    visitas = [dict(zip(nomes, linha)) for linha in dados["rows"]]
    resultados = {x["comentario"]: x for x in ler_jsonl(DESTINO / "resultados_completos.jsonl")}
    if len(resultados) != 9571 or len(visitas) != 9940:
        raise RuntimeError("resultado completo ou snapshot inesperado")

    cats_piloto = set()
    for item in piloto_original():
        cats_piloto.update(categorias(item["barreira_bruta"]))

    visitas_cat = Counter()
    textos_cat: dict[str, set[str]] = defaultdict(set)
    medicos_cat: dict[str, set[str]] = defaultdict(set)
    barreiras_brutas_cat: dict[str, Counter] = defaultdict(Counter)
    exemplos_cat: dict[str, list[str]] = defaultdict(list)
    for visita in visitas:
        comentario = visita["COMENTARIOS"]
        resultado = resultados[comentario]
        if not resultado["tem_barreira"]:
            continue
        for codigo in categorias(resultado["barreira_bruta"]):
            visitas_cat[codigo] += 1
            textos_cat[codigo].add(comentario)
            medicos_cat[codigo].add(str(visita["UFCRM"]))
            barreiras_brutas_cat[codigo][resultado["barreira_bruta"]] += 1
            if comentario not in exemplos_cat[codigo]:
                exemplos_cat[codigo].append(comentario)

    grupos = []
    for codigo in sorted(visitas_cat, key=lambda x: (-visitas_cat[x], x)):
        candidatos = sorted(exemplos_cat[codigo], key=lambda x: (abs(len(x) - 180), len(x)))
        exemplos_curados = EXEMPLOS_CURADOS.get(codigo)
        if exemplos_curados:
            ausentes = [x for x in exemplos_curados if x not in barreiras_brutas_cat[codigo]]
            if ausentes:
                raise RuntimeError(f"exemplo curado não pertence a {codigo}: {ausentes}")
        grupos.append({
            "codigo": codigo, "barreira": ROTULOS[codigo],
            "visitas": visitas_cat[codigo], "medicos_distintos": len(medicos_cat[codigo]),
            "comentarios_distintos": len(textos_cat[codigo]),
            "aparecia_nas_23_do_piloto_original": codigo in cats_piloto,
            "status_lista": "EXCLUIDA_PELA_REGRA_DE_ADOCAO" if codigo in EXCLUIDAS_DA_LISTA else "CANDIDATA",
            "formulacoes_brutas_frequentes": exemplos_curados or [x for x, _ in barreiras_brutas_cat[codigo].most_common(3)],
            "exemplos_reais": candidatos[:3],
        })

    (DESTINO / "barreiras_candidatas.json").write_text(
        json.dumps(grupos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    resumo = {
        "grupos_candidatos": sum(x["status_lista"] == "CANDIDATA" for x in grupos),
        "grupos_excluidos": sum(x["status_lista"] != "CANDIDATA" for x in grupos),
        "ja_apareciam_no_piloto": [x["barreira"] for x in grupos
                                    if x["status_lista"] == "CANDIDATA"
                                    and x["aparecia_nas_23_do_piloto_original"]],
        "novas_na_escala": [x["barreira"] for x in grupos
                             if x["status_lista"] == "CANDIDATA"
                             and not x["aparecia_nas_23_do_piloto_original"]],
        "categorias_piloto_original": sorted(ROTULOS[x] for x in cats_piloto),
    }
    (DESTINO / "resumo_comparacao_piloto.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(resumo, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
