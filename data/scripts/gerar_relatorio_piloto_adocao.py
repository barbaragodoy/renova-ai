"""Gera somente o relatório de ruído, piloto e custo da passada S."""
from __future__ import annotations

import json
from pathlib import Path

from descobrir_barreiras_adocao_piloto import PROMPT, PROMPT_INICIAL, SQL
from barreiras_comum import chave

DESTINO = Path("docs/analises/barreiras_adocao_piloto")


def registros(nome: str) -> list[dict]:
    return [json.loads(x) for x in (DESTINO / nome).read_text().splitlines() if x]


def numero(n: float | int) -> str:
    return f"{n:,.0f}".replace(",", ".")


def decimal(n: float, casas: int = 2) -> str:
    return f"{n:.{casas}f}".replace(".", ",")


def main() -> None:
    snapshot = json.loads((DESTINO / "fonte_snapshot.json").read_text())
    ruido = json.loads((DESTINO / "contagem_ruido.json").read_text())
    visitas = snapshot["rows"]
    if len(visitas) != ruido["visitas"]:
        raise RuntimeError("contagem SQL de ruído não corresponde ao snapshot")
    textos = [x[-1] for x in visitas]
    from collections import Counter
    frequencias = Counter(textos)
    repetidos = sum(n for n in frequencias.values() if n > 1)
    excesso = len(visitas) - len(frequencias)
    inicial_por_texto = {r["comentario"]: r for r in registros("extracoes_piloto.jsonl")
                         if r["chave"] == chave(PROMPT_INICIAL, r["comentario"])}
    if len(inicial_por_texto) != 150:
        raise RuntimeError("piloto S não tem exatamente 150 textos na versão inicial")
    chamadas = {r["chave"]: r for arquivo in
                ("extracoes_piloto.jsonl", "extracoes_ajuste.jsonl", "extracoes_ajuste_final.jsonl")
                for r in registros(arquivo)}
    entrada_real = sum(r["tokens_entrada"] for r in chamadas.values())
    saida_real = sum(r["tokens_saida"] for r in chamadas.values())
    entrada_base = sum(r["tokens_entrada"] for r in inicial_por_texto.values())
    saida_base = sum(r["tokens_saida"] for r in inicial_por_texto.values())
    # As duas consultas repetidas com o prompt final mostraram acréscimo
    # idêntico de 115 tokens de entrada em relação à versão de 150 textos.
    final_por_texto = {r["comentario"]: r for r in registros("extracoes_ajuste_final.jsonl")
                       if r["chave"] == chave(PROMPT, r["comentario"])}
    deltas = {r["tokens_entrada"] - inicial_por_texto[t]["tokens_entrada"]
              for t, r in final_por_texto.items()}
    if len(final_por_texto) != 2 or len(deltas) != 1:
        raise RuntimeError("não foi possível medir o acréscimo do prompt final")
    delta = deltas.pop()
    tokens_entrada_por_chamada = entrada_base / 150 + delta
    tokens_saida_por_chamada = saida_base / 150
    total_2026 = 4_947_363
    distinto_2026_observado = 3_477_987
    bases = [
        ("Recorte aprovado, contagem exata", len(frequencias)),
        ("Base completa, extrapolação matemática do excesso da amostra", round(total_2026 * (1 - excesso / len(visitas)))),
        ("Base completa, desconto de 638/9.940 solicitado", round(total_2026 * (1 - repetidos / len(visitas)))),
        ("Base completa, distintos já medidos por SQL em 2026", distinto_2026_observado),
    ]
    tabela = "\n".join(f"| {rotulo} | {numero(n)} | {numero(round(n * tokens_entrada_por_chamada))} | {numero(round(n * tokens_saida_por_chamada))} | {numero(round(n * (tokens_entrada_por_chamada + tokens_saida_por_chamada)))} |"
                       for rotulo, n in bases)
    texto = f"""# Barreiras de adoção — ruído e piloto (passada S)

Leitura de 18/09/2026. Este relatório usa **somente `VISITA_EFETIVA='S'`**. A extração parou em **150 comentários distintos do piloto**; não há lista final de barreiras de adoção nesta etapa.

## Recorte e proporção de ruído

O recorte aprovado seleciona 0,8% por hash determinístico de `ID` nos ciclos completos `202607` e `202608`, sem filtro de comprimento ou qualidade:

```sql
{SQL}
```

São **{numero(len(visitas))} visitas**, **{numero(len(frequencias))} comentários distintos** e **{numero(repetidos)} visitas cujo texto aparece em mais de uma visita** (**{decimal(repetidos / len(visitas) * 100)}%**). A deduplicação elimina **{excesso} chamadas**, pois preserva uma chamada para cada texto repetido. Portanto, o número correto de chamadas para todo o recorte seria **{numero(len(frequencias))}**; **9.302** resulta de subtrair indevidamente as 638 visitas, inclusive a primeira ocorrência de cada texto.

A [consulta SQL de ruído](contagem_ruido.sql) encontrou **{ruido['sem_conteudo_regras']} visitas com padrões literais sem conteúdo real**, ou **{decimal(ruido['sem_conteudo_regras'] / len(visitas) * 100)}%** do recorte. Os padrões incluem “RELEMBREI”, “VISITA REMOTA”, “SEM COMENTÁRIOS”, notas genéricas de reforço e nomes de produto isolados identificados na leitura. Esta é uma **contagem conservadora por regras explícitas**, não uma revisão semântica exaustiva das 9.940 visitas. Um comentário factual sem obstáculo, como prescrição já existente ou feedback positivo, pertence à classe distinta `COM_CONTEUDO_SEM_BARREIRA`; não foi incluído nesses {ruido['sem_conteudo_regras']}.

Os dois percentuais servem de referência para avaliar representatividade quando houver escala. A taxa de duplicação **já** mostra diferença relevante: na amostra, o excesso de visitas duplicadas é **{decimal(excesso / len(visitas) * 100)}%**; no conjunto `S` de 2026, os **{numero(total_2026)}** registros e **{numero(distinto_2026_observado)}** textos distintos medidos por SQL implicam **{decimal((total_2026 - distinto_2026_observado) / total_2026 * 100)}%** de excesso. Assim, a extrapolação da deduplicação da amostra é frágil para orçamento da base completa.

## Prompt, execução e leitura do piloto

`data/scripts/descobrir_barreiras_adocao_piloto.py` usa `ServingDatabricks.extrair_estruturado` com prompt e arquivos exclusivos desta passada. Seleciona os 150 textos por SHA-256 do comentário dentro do recorte. O script impõe limite de 150 textos e os arquivos `manifesto_ids.jsonl`, `manifesto_piloto.jsonl` e `extracoes_*.jsonl` preservam o recorte e as respostas brutas.

O prompt final ajustado, ainda limitado ao piloto, é:

```text
{PROMPT}
```

Na leitura inicial dos 150 textos, **23** respostas indicaram barreira e **127** não indicaram; todas terminaram com JSON interpretável após aceitar blocos Markdown integrais. Acertos observados: relato de marca “pouco lembrada” com amostras do concorrente; “DODIBE NÃO ESTAVA LEMBRANDO O NOME”; e tratamento “mais difícil devido ao custo”. Negativos adequados: médico já prescrevendo e elogiando a marca; comentário sobre paciente que interrompeu tratamento, sem obstáculo atribuído ao médico.

Erros observados e ajuste: “FOCO EM PREÇO” foi inicialmente tratado como objeção do médico; substituição por genérico **na farmácia após prescrição** foi confundida com não adoção pelo médico. Na revisão de 20 textos, esses dois casos passaram a `false`. Persistiram duas inferências indevidas: prescrever concorrente sem informar o motivo e usar outra molécula para dor de intensidade diferente. O prompt final tornou esses contraexemplos explícitos; ambos passaram a `false` na checagem final de dois textos. As versões anteriores dos prompts permanecem constantes nomeadas no script para auditoria. O piloto indica que a leitura manual continua necessária antes de qualquer escala.

## Custo real do piloto e projeção para decisão

O piloto envolveu **150 textos distintos** e **{len(chamadas)} chamadas reais** contando as versões de checagem e ajuste: **{numero(entrada_real)} tokens de entrada** e **{numero(saida_real)} de saída** (total **{numero(entrada_real + saida_real)}**). A versão inicial de 150 textos consumiu **{numero(entrada_base)} entrada / {numero(saida_base)} saída**. O prompt final acrescentou **{delta} tokens de entrada por chamada** nos dois mesmos textos usados para comparar versões. Para projeção, usei **{decimal(tokens_entrada_por_chamada, 1)} entrada** e **{decimal(tokens_saida_por_chamada, 1)} saída** por comentário, sem preço em dinheiro.

| Base da decisão | Chamadas estimadas | Tokens de entrada | Tokens de saída | Total de tokens |
|---|---:|---:|---:|---:|
{tabela}

As **duas bases solicitadas** são o recorte aprovado e a base completa. Dentro da base completa, a linha do desconto de **638/9.940** mostra literalmente a extrapolação pedida, mas ela **superestima a economia da deduplicação**: 638 é o número de visitas em grupos de texto repetido, enquanto apenas {excesso} visitas são excedentes. A linha do excesso de {excesso}/9.940 corrige essa conta. A linha de **distintos já medidos** usa a contagem real disponível para 2026 e é mais informativa para orçamento desse conjunto. Nenhuma dessas projeções inclui novas iterações de prompt, falhas com cobrança ou eventual agrupamento por modelo.

**Limite desta execução:** nenhum comentário fora dos 150 textos do piloto foi enviado ao modelo nesta passada. A escala do recorte ou da base completa aguarda confirmação após envio desta estimativa ao George e ao Bruno.
"""
    (DESTINO / "relatorio_piloto.md").write_text(texto, encoding="utf-8")
    print(DESTINO / "relatorio_piloto.md")


if __name__ == "__main__":
    main()
