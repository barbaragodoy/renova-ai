"""Gera o relatório final da escala aprovada da passada S."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from barreiras_comum import ler_jsonl
from descobrir_barreiras_adocao_piloto import PROMPT


DESTINO = Path("docs/analises/barreiras_adocao_piloto")


def numero(valor: int) -> str:
    return f"{valor:,}".replace(",", ".")


def decimal(valor: float) -> str:
    return f"{valor:.2f}".replace(".", ",")


def trecho(texto: str, limite: int = 220) -> str:
    texto = " ".join(texto.split()).replace("|", "/")
    return texto if len(texto) <= limite else texto[: limite - 1].rstrip() + "…"


def uso_real_escala() -> tuple[int, int, int]:
    tentativa1 = ler_jsonl(DESTINO / "extracoes_escala_individual_tentativa1.jsonl")
    principal = ler_jsonl(DESTINO / "extracoes_escala_individual.jsonl")
    if len(tentativa1) != 9101:
        raise RuntimeError("primeira tentativa da escala incompleta")
    erros_t1 = {x["chave"] for x in tentativa1 if x["estado"] != "EXTRAIDO"}
    retries = [x for x in principal if x["chave"] in erros_t1]
    chamadas = tentativa1 + retries
    return (len(chamadas), sum(x["tokens_entrada"] for x in chamadas),
            sum(x["tokens_saida"] for x in chamadas))


def uso_arquivo(nome: str) -> tuple[int, int, int]:
    rows = ler_jsonl(DESTINO / nome)
    return len(rows), sum(x["tokens_entrada"] for x in rows), sum(x["tokens_saida"] for x in rows)


def main() -> None:
    grupos = json.loads((DESTINO / "barreiras_candidatas.json").read_text(encoding="utf-8"))
    comparacao = json.loads((DESTINO / "resumo_comparacao_piloto.json").read_text(encoding="utf-8"))
    resultados = ler_jsonl(DESTINO / "resultados_completos.jsonl")
    snapshot = json.loads((DESTINO / "fonte_snapshot.json").read_text(encoding="utf-8"))
    nomes = [x["name"] for x in snapshot["schema"]]
    visitas = [dict(zip(nomes, x)) for x in snapshot["rows"]]
    frequencias = Counter(v["COMENTARIOS"] for v in visitas)
    classes_texto = Counter(x["classe"] for x in resultados)
    classes_visita = Counter()
    for item in resultados:
        classes_visita[item["classe"]] += frequencias[item["comentario"]]

    chamadas_escala, entrada_escala, saida_escala = uso_real_escala()
    lote_trunc = uso_arquivo("extracoes_validacao_lote_sonnet.jsonl")
    lote_valido = uso_arquivo("extracoes_validacao_lote_sonnet_max4000.jsonl")
    llama = uso_arquivo("extracoes_validacao_llama.jsonl")
    entrada_validacoes = lote_trunc[1] + lote_valido[1] + llama[1]
    saida_validacoes = lote_trunc[2] + lote_valido[2] + llama[2]

    candidatas = [x for x in grupos if x["status_lista"] == "CANDIDATA"]
    excluidas = [x for x in grupos if x["status_lista"] != "CANDIDATA"]
    tabela = "\n".join(
        f"| {x['barreira']} | {numero(x['visitas'])} | {numero(x['medicos_distintos'])} | "
        f"{numero(x['comentarios_distintos'])} | {'Já aparecia' if x['aparecia_nas_23_do_piloto_original'] else 'Nova'} |"
        for x in candidatas
    )
    exemplos = "\n\n".join(
        f"### {x['barreira']}\n\n" + "\n".join(
            f"- “{trecho(exemplo)}”" for exemplo in x["formulacoes_brutas_frequentes"][:3]
        ) for x in candidatas
    )
    ja = "\n".join(f"- {x}" for x in comparacao["ja_apareciam_no_piloto"])
    novas = "\n".join(f"- {x}" for x in comparacao["novas_na_escala"])
    excluidas_txt = "\n".join(
        f"- **{x['barreira']}**: {numero(x['visitas'])} visitas e "
        f"{numero(x['medicos_distintos'])} médicos distintos."
        for x in excluidas
    )

    texto = f"""# Barreiras de adoção — validações e escala completa do recorte

Execução concluída em 20/09/2026. Este relatório contém exclusivamente a
**Passada 1**, `VISITA_EFETIVA='S'`. Nenhum dado, variável ou resultado da
passada de acesso foi usado.

## Resultado executivo

O recorte aprovado contém **9.940 visitas** e **9.571 comentários distintos**
dos ciclos completos `202607` e `202608`, selecionados por hash determinístico
de `ID`. A extração terminou com decisão para **9.571/9.571 textos**, sem erro
de formato ou chamada pendente.

Foram consolidadas **{len(candidatas)} barreiras candidatas**. Como um mesmo
comentário pode declarar mais de uma causa, as frequências das barreiras podem
se sobrepor e não devem ser somadas. A frequência é ponderada pelo número de
visitas reais associado ao texto deduplicado; médicos distintos usam `UFCRM`.

| Barreira candidata | Visitas | Médicos distintos | Comentários distintos | Comparação com 23 positivos originais |
|---|---:|---:|---:|---|
{tabela}

## Comparação explícita com as 23 ocorrências do piloto original

As “23 do piloto” eram **23 comentários marcados como positivos**, não 23
categorias consolidadas. Aplicando o mesmo vocabulário pós-extração, as
categorias abaixo já apareciam nessas 23 ocorrências:

{ja}

As categorias abaixo só apareceram quando o recorte completo foi processado:

{novas}

Quatro das 23 decisões iniciais do piloto foram corrigidas durante o ajuste do
prompt e não integram o gabarito final: concorrente citado sem causa declarada,
“foco em preço” como ação do propagandista, substituição por genérico feita na
farmácia e uso de outra molécula para intensidade de dor diferente. A
comparação acima usa deliberadamente as **23 ocorrências originais**, conforme
solicitado, e preserva essa ressalva.

## Exemplos extraídos de comentários reais

Os exemplos abaixo são formulações curtas produzidas na extração a partir dos
comentários do recorte. Os comentários brutos completos permanecem nos
artefatos locais ignorados pelo Git.

{exemplos}

## Padrões fora da lista de adoção

{excluidas_txt}

Esses padrões ficam no rastro de auditoria, mas não entram na lista de
barreiras de adoção: baixa oportunidade ou perfil de pacientes é contexto
clínico, conforme a regra explícita do prompt; troca feita pela farmácia
acontece depois de o médico prescrever; tempo/abertura da visita não demonstra
obstáculo do médico para adotar.

## Qualidade e ausência de barreira

| Classe | Comentários distintos | Visitas |
|---|---:|---:|
| `SEM_CONTEUDO_REAL` | {numero(classes_texto['SEM_CONTEUDO_REAL'])} | {numero(classes_visita['SEM_CONTEUDO_REAL'])} |
| `COM_CONTEUDO_SEM_BARREIRA` | {numero(classes_texto['COM_CONTEUDO_SEM_BARREIRA'])} | {numero(classes_visita['COM_CONTEUDO_SEM_BARREIRA'])} |
| `COM_BARREIRA` (saída bruta antes das exclusões de agrupamento) | {numero(classes_texto['COM_BARREIRA'])} | {numero(classes_visita['COM_BARREIRA'])} |

As classes sem conteúdo e com conteúdo sem barreira permanecem separadas. A
contagem de `COM_BARREIRA` é a saída de extração; os três padrões excluídos na
seção anterior continuam nela para manter o rastro entre resposta bruta e
decisão de agrupamento.

## Validações das sugestões do George

### Sonnet em lote de 20

Com JSON completo, houve **8 divergências em 150 (5,33%)** contra o gabarito:
7 falsos negativos e 1 falso positivo. As divergências ficaram nas posições
1, 4, 6, 12, 13 (duas), 15 e 20. Foram 3/80 nas posições 1–10 (3,75%) e 5/70
nas posições 11–20 (7,14%): maior incidência na segunda metade, sem degradação
monotônica. **Otimização reprovada e não usada na escala.**

### llama-4-maverick como filtro

Concordância geral de **138/150 (92,00%)**, com 9 falsos negativos e 3 falsos
positivos. Nos quatro casos difíceis, concordância de **3/4 (75,00%)**; errou
o caso de molécula diferente conforme intensidade da dor. **Otimização
reprovada e não usada na escala.**

### Corte abaixo de 20 caracteres

A amostra determinística de 30 textos não continha barreira curta. A leitura
complementar dos 99 textos distintos abaixo do corte também não encontrou
barreira. O corte foi usado somente para dispensar o modelo; textos factuais
curtos continuaram separados de `SEM_CONTEUDO_REAL`.

### Classificação manual dos mais frequentes

`classificacoes_manuais.jsonl` contém **250 textos**, representando **600
visitas**, cada um com decisão e justificativa: 133 `SEM_CONTEUDO_REAL`, 109
`COM_CONTEUDO_SEM_BARREIRA` e 8 `COM_BARREIRA`.

## Método reproduzível

1. `validar_otimizacoes_adocao.py` reconstrói o gabarito e testa Sonnet em
   lote e Maverick.
2. `gerar_classificacoes_manuais_adocao.py` reproduz o ranking determinístico
   e grava as 250 decisões revisadas.
3. `descobrir_barreiras_adocao_completo.py` aplica decisões manuais, corte
   revisado, gabarito do piloto e Sonnet individual aos demais textos.
4. `reprocessar_erros_formato_adocao.py` resolve somente resíduos truncados,
   sem alterar a regra de extração.
5. `agrupar_barreiras_adocao.py` aplica o vocabulário criado após ler as
   formulações extraídas. Uma formulação composta pode mapear para mais de uma
   barreira; a frequência usa visitas e `UFCRM` distintos.

Prompt final de extração:

```text
{PROMPT}
```

## Consumo real em tokens

| Etapa | Chamadas | Entrada | Saída | Total |
|---|---:|---:|---:|---:|
| Escala Sonnet individual, incluindo retries cobrados | {numero(chamadas_escala)} | {numero(entrada_escala)} | {numero(saida_escala)} | {numero(entrada_escala + saida_escala)} |
| Validação Sonnet em lote, tentativa truncada | {numero(lote_trunc[0])} | {numero(lote_trunc[1])} | {numero(lote_trunc[2])} | {numero(lote_trunc[1] + lote_trunc[2])} |
| Validação Sonnet em lote, JSON completo | {numero(lote_valido[0])} | {numero(lote_valido[1])} | {numero(lote_valido[2])} | {numero(lote_valido[1] + lote_valido[2])} |
| Validação Maverick | {numero(llama[0])} | {numero(llama[1])} | {numero(llama[2])} | {numero(llama[1] + llama[2])} |
| **Total desta execução** | **{numero(chamadas_escala + lote_trunc[0] + lote_valido[0] + llama[0])}** | **{numero(entrada_escala + entrada_validacoes)}** | **{numero(saida_escala + saida_validacoes)}** | **{numero(entrada_escala + saida_escala + entrada_validacoes + saida_validacoes)}** |

As 10.660 chamadas da escala incluem 9.101 primeiras tentativas, 1.531
retries após HTTP 429/erro de formato, 27 retries com teto maior e 1 retry
final. Chamadas HTTP 429 registraram usage zero. O total não inclui o piloto
original, executado antes desta validação.

## Separação de dados

Todos os scripts, variáveis e artefatos citados usam somente a passada de
adoção (`S`). Nenhum dado da passada de acesso (`N`) foi lido, agregado ou
incluído neste relatório.
"""
    destino = DESTINO / "relatorio_final_adocao.md"
    destino.write_text(texto, encoding="utf-8")
    print(destino)


if __name__ == "__main__":
    main()
