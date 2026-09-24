"""Gera somente o relatório final da passada N a partir dos seus artefatos."""
from __future__ import annotations

import json
from pathlib import Path

from descobrir_barreiras_acesso import PROMPT, SQL

DESTINO = Path("docs/analises/barreiras_acesso")


def numero(n: int) -> str:
    return f"{n:,}".replace(",", ".")


EXEMPLOS = {
    "Férias ou recesso": ["FÉRIAS", "DR DE FÉRIAS."],
    "Mudança de local ou localização desconhecida": ["DRA MUDOU-SE.", "MUDOU DE ENDEREÇO"],
    "Viagem ou congresso": ["VIAJANDO", "CONGRESSO"],
    "Agenda ou horário incompatível": ["CANCELOU AGENDA.", "MEDICO JÁ TINHA FINALIZADO O ATENDIMENTO"],
    "Ausência sem causa mais específica": ["MÉDICO AUSENTE", "DRA AUSENTE."],
    "Afastamento por saúde": ["DR AFASTADO DEVIDO À CIRURGIA.", "ESTA AFASTADA POR SAÚDE ( PUNHO)"],
    "Licença parental": ["LICENÇA MATERNIDADE", "DRA EM LICENÇA MATERNIDADE"],
    "Recusa ou limitação para receber representantes": ["NÃO QUER RECEBER VISITA", "MEDICO NAO RECEBE REPRESENTANTE"],
    "Restrição institucional ou física de acesso": ["LUGAR RESTRITO PARA VISITAS", "MEDICO INTERNO NA UNESP SEM ACESSO PARA VISITAÇÃO"],
    "Fora da área de atendimento do setor": ["FORA DO SETOR", "DRA ATENDE CDU. FORA DO BRICK."],
    "Licença ou afastamento sem causa informada": ["MEDICO AFASTADO TEMPORARIAMENTE", "MEDICO ESTA DE LICENÇA, RETORNANDO AO ATENDIMENTO 01/07"],
    "Local de atendimento fechado": ["A CLÍNICA ESTAVA FECHADA.", "COMSULTORIO FECHADO DEVIDO AO FERIADO"],
    "Luto ou falecimento familiar": ["FALECEU UM FAMILIAR", "MEDICA NÃO VEIO ATENDER DEVIDO AO FALECIMENTO DE SUA VÓ"],
    "Atendimento profissional interrompido": ["APOSENTOU", "MEDICO SUSPENDEU OS ATENDIMENTOS"],
}


def main() -> None:
    candidatos = json.loads((DESTINO / "barreiras_candidatas.json").read_text())
    resumo = json.loads((DESTINO / "resumo_final.json").read_text())
    snapshot = json.loads((DESTINO / "fonte_snapshot.json").read_text())
    textos_fonte = {linha[-1] for linha in snapshot["rows"]}
    if sum(x["visitas"] for x in candidatos) != resumo["estados"]["COM_BARREIRA"]["visitas"]:
        raise RuntimeError("soma das barreiras não fecha com o resumo")
    linhas = []
    for item in candidatos:
        exemplos = EXEMPLOS[item["barreira"]]
        if not 2 <= len(exemplos) <= 3 or any(e not in textos_fonte for e in exemplos):
            raise RuntimeError(f"exemplos ausentes da fonte: {item['barreira']}")
        linhas.append("| " + item["barreira"] + " | " + str(item["visitas"]) + " | "
                      + str(item["medicos_distintos"]) + " | "
                      + "<br>".join('“' + e.replace("|", "\\|") + '”' for e in exemplos) + " |")
    estados = resumo["estados"]
    texto = f"""# Barreiras de acesso — visitas não realizadas (passada N)

Leitura de 18/09/2026. Este relatório usa **somente `VISITA_EFETIVA='N'`** e descreve motivos pelos quais uma visita não ocorreu. As categorias são candidatas extraídas dos comentários e revisadas manualmente; a frequência mede visitas do recorte, não prevalência causal em todos os médicos da empresa.

## Resultado

Entre **396.504** registros `N` com `DATA_VISITA` em 2026, **395.428** repetem o texto automático de fechamento e foram excluídos. O recorte restante tem **{resumo['visitas']} visitas**, **{resumo['comentarios_distintos']} comentários distintos**. Há **{estados['COM_BARREIRA']['visitas']} visitas com barreira de acesso candidata**, envolvendo **{estados['COM_BARREIRA']['medicos_distintos']} médicos distintos**. A mesma pessoa pode constar em mais de uma categoria; não somar a coluna de médicos para obter o total.

| Barreira candidata de acesso | Visitas | Médicos distintos | Exemplos literais do campo COMENTARIOS |
|---|---:|---:|---|
{chr(10).join(linhas)}

## Sem barreira classificada

| Estado | Visitas | Comentários distintos | Médicos distintos |
|---|---:|---:|---:|
| Sem conteúdo real | {estados['SEM_CONTEUDO_REAL']['visitas']} | {estados['SEM_CONTEUDO_REAL']['comentarios_distintos']} | {estados['SEM_CONTEUDO_REAL']['medicos_distintos']} |
| Com conteúdo, sem causa de acesso identificável | {estados['COM_CONTEUDO_SEM_BARREIRA']['visitas']} | {estados['COM_CONTEUDO_SEM_BARREIRA']['comentarios_distintos']} | {estados['COM_CONTEUDO_SEM_BARREIRA']['medicos_distintos']} |

Dos {estados['SEM_CONTEUDO_REAL']['visitas']} registros sem conteúdo real, **200** são apenas `-`; os demais são notas genéricas como “DEIXADO AGS” ou “NADA A RELATAR”. Os {estados['COM_CONTEUDO_SEM_BARREIRA']['visitas']} registros com conteúdo sem barreira incluem descrições de baixo potencial prescritivo ou locais de atendimento sem evidência de impedimento da visita. Duas respostas que apenas repetiam “médico não atendeu” foram revistas como sem causa concreta. Após interpretar JSON integral em Markdown ou no bloco `text` da API, **zero** respostas permanecem sem classificação por erro de formato. As respostas brutas e os desvios de formato continuam auditáveis em `extracoes.jsonl`.

O campo `OPV` não foi usado para inferir a causa. Neste mesmo recorte `N`, seus valores mais frequentes são `-` (372), “EXCLUIR” (69), “EXCLUSÃO” (23), “APRESENTAÇÃO E RELACIONAMENTO.” (18) e “PRÓXIMO CICLO” (17), conforme [consulta própria](consulta_opv.sql). Ele descreve uma ação ou objetivo de acompanhamento, não necessariamente o motivo da visita não realizada.

## Método reproduzível

1. Consulta somente leitura:

```sql
{SQL}
```

2. `manifesto_ids.jsonl` conserva ID, ciclo, data, tipo, UFCRM e hash do comentário de cada visita. `fonte_snapshot.json` conserva a fotografia SQL usada. O texto automático “PROFISSIONAIS NÃO VISITADOS ATÉ O FECHAMENTO” foi excluído antes da extração.
3. Na extração final, cada um dos **703 comentários distintos não vazios** foi enviado uma vez ao modelo; os 10 textos da checagem inicial foram enviados novamente após ajuste do prompt e estão incluídos no custo real. As **200 visitas `-`** não precisaram de inferência. O prompt de acesso é:

```text
{PROMPT}
```

4. Antes da primeira chamada, 12 comentários reais foram lidos diretamente por SQL. O teste mental esperava `true` para “DR ESTÁ DE FÉRIAS.”, “DRA FECHOU AGENDA HOJE.”, “DR NAO TEM INTERESSE EM RECEBER NOSSA VISITA POR CONTA DE AGENDA APERTADA” e o relato de agenda não aberta na clínica; esperava `false` para “BAIXO POTENCIAL PARA OS PRODUTOS PROMOVIDOS PELA LINHA 6” e “NÃO FORAM IDENTIFICADAS OPORTUNIDADES RELEVANTES PARA AS MARCAS DO PORTFÓLIO”. O primeiro lote real de 10 mostrou o caso de atendimento já encerrado, acrescentado ao prompt antes da execução completa.
5. O script `data/scripts/descobrir_barreiras_acesso.py` usa `ServingDatabricks.extrair_estruturado`, sem ferramentas, com máximo de 160 tokens de saída. `extracoes.jsonl` guarda resposta bruta e `usage` por chamada. JSON integral em bloco Markdown ou no bloco `text` da resposta é interpretado localmente; outros erros permanecem com estado explícito.
6. `data/scripts/agrupar_barreiras_acesso.py` aplica vocabulário consolidado **depois** da leitura das barreiras brutas: férias/recesso, mudança/localização, viagem/congresso, agenda/horário, ausência, saúde, licença parental, recusa, restrição institucional/física, território, licença sem causa, fechamento de local, luto e interrupção da atividade. A ordem das regras e as revisões manuais de falsos positivos/negativos estão no script. `revisao_residual.jsonl` registra cada correção. Frequência = número de visitas ligadas ao comentário; médicos distintos = `COUNT(DISTINCT UFCRM)` dentro da categoria.

Para reproduzir a fotografia usada nesta execução, rodar na raiz do projeto:

```bash
.venv/bin/python data/scripts/descobrir_barreiras_acesso.py --snapshot-sql-api docs/analises/barreiras_acesso/fonte_snapshot.json
.venv/bin/python data/scripts/agrupar_barreiras_acesso.py --snapshot-sql-api docs/analises/barreiras_acesso/fonte_snapshot.json
.venv/bin/python data/scripts/gerar_relatorio_barreiras_acesso.py
```

## Custo real e limites

Foram **{resumo['chamadas_reais_incluindo_teste_inicial']} chamadas reais**, incluindo as 10 de checagem inicial e o reprocessamento dos mesmos textos com o prompt corrigido: **{numero(resumo['tokens_entrada_reais'])} tokens de entrada** e **{numero(resumo['tokens_saida_reais'])} de saída** (total **{numero(resumo['tokens_entrada_reais'] + resumo['tokens_saida_reais'])}**). Os números vêm do `usage` de cada resposta e contam uma vez cada chave de chamada; normalizações locais não gastaram tokens. Não há conversão para dinheiro, conforme decisão do George.

A leitura manual encontrou acertos claros para férias, agenda encerrada, licença e restrição institucional. Também encontrou falsos negativos para “CONGRESSO”, “CONSULTIVO FECHADO” e “NÃO GOSTA DE RECEBER REPRESENTANTES”, além de dois falsos positivos que só diziam que o médico não atendeu. Essas correções estão registradas, sem apagar a saída original. O resultado é uma lista candidata para revisão de negócio, especialmente nas causas curtas ou ambíguas.

**Achado para decisão futura:** barreiras de acesso reais aparecem em comentários `N`. A ferramenta atual de observações do agente considera apenas `VISITA_EFETIVA='S'`; portanto, não vê esses registros. Este trabalho não altera a ferramenta.
"""
    (DESTINO / "relatorio_final.md").write_text(texto, encoding="utf-8")
    print(DESTINO / "relatorio_final.md")


if __name__ == "__main__":
    main()
