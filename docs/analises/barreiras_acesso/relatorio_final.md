# Barreiras de acesso — visitas não realizadas (passada N)

Leitura de 18/09/2026. Este relatório usa **somente `VISITA_EFETIVA='N'`** e descreve motivos pelos quais uma visita não ocorreu. As categorias são candidatas extraídas dos comentários e revisadas manualmente; a frequência mede visitas do recorte, não prevalência causal em todos os médicos da empresa.

## Resultado

Entre **396.504** registros `N` com `DATA_VISITA` em 2026, **395.428** repetem o texto automático de fechamento e foram excluídos. O recorte restante tem **1076 visitas**, **704 comentários distintos**. Há **634 visitas com barreira de acesso candidata**, envolvendo **589 médicos distintos**. A mesma pessoa pode constar em mais de uma categoria; não somar a coluna de médicos para obter o total.

| Barreira candidata de acesso | Visitas | Médicos distintos | Exemplos literais do campo COMENTARIOS |
|---|---:|---:|---|
| Férias ou recesso | 192 | 189 | “FÉRIAS”<br>“DR DE FÉRIAS.” |
| Mudança de local ou localização desconhecida | 87 | 85 | “DRA MUDOU-SE.”<br>“MUDOU DE ENDEREÇO” |
| Viagem ou congresso | 65 | 65 | “VIAJANDO”<br>“CONGRESSO” |
| Agenda ou horário incompatível | 64 | 62 | “CANCELOU AGENDA.”<br>“MEDICO JÁ TINHA FINALIZADO O ATENDIMENTO” |
| Ausência sem causa mais específica | 61 | 59 | “MÉDICO AUSENTE”<br>“DRA AUSENTE.” |
| Afastamento por saúde | 37 | 34 | “DR AFASTADO DEVIDO À CIRURGIA.”<br>“ESTA AFASTADA POR SAÚDE ( PUNHO)” |
| Licença parental | 37 | 28 | “LICENÇA MATERNIDADE”<br>“DRA EM LICENÇA MATERNIDADE” |
| Recusa ou limitação para receber representantes | 27 | 26 | “NÃO QUER RECEBER VISITA”<br>“MEDICO NAO RECEBE REPRESENTANTE” |
| Restrição institucional ou física de acesso | 20 | 20 | “LUGAR RESTRITO PARA VISITAS”<br>“MEDICO INTERNO NA UNESP SEM ACESSO PARA VISITAÇÃO” |
| Fora da área de atendimento do setor | 19 | 19 | “FORA DO SETOR”<br>“DRA ATENDE CDU. FORA DO BRICK.” |
| Licença ou afastamento sem causa informada | 9 | 9 | “MEDICO AFASTADO TEMPORARIAMENTE”<br>“MEDICO ESTA DE LICENÇA, RETORNANDO AO ATENDIMENTO 01/07” |
| Local de atendimento fechado | 6 | 6 | “A CLÍNICA ESTAVA FECHADA.”<br>“COMSULTORIO FECHADO DEVIDO AO FERIADO” |
| Luto ou falecimento familiar | 6 | 6 | “FALECEU UM FAMILIAR”<br>“MEDICA NÃO VEIO ATENDER DEVIDO AO FALECIMENTO DE SUA VÓ” |
| Atendimento profissional interrompido | 4 | 4 | “APOSENTOU”<br>“MEDICO SUSPENDEU OS ATENDIMENTOS” |

## Sem barreira classificada

| Estado | Visitas | Comentários distintos | Médicos distintos |
|---|---:|---:|---:|
| Sem conteúdo real | 216 | 15 | 180 |
| Com conteúdo, sem causa de acesso identificável | 226 | 159 | 225 |

Dos 216 registros sem conteúdo real, **200** são apenas `-`; os demais são notas genéricas como “DEIXADO AGS” ou “NADA A RELATAR”. Os 226 registros com conteúdo sem barreira incluem descrições de baixo potencial prescritivo ou locais de atendimento sem evidência de impedimento da visita. Duas respostas que apenas repetiam “médico não atendeu” foram revistas como sem causa concreta. Após interpretar JSON integral em Markdown ou no bloco `text` da API, **zero** respostas permanecem sem classificação por erro de formato. As respostas brutas e os desvios de formato continuam auditáveis em `extracoes.jsonl`.

O campo `OPV` não foi usado para inferir a causa. Neste mesmo recorte `N`, seus valores mais frequentes são `-` (372), “EXCLUIR” (69), “EXCLUSÃO” (23), “APRESENTAÇÃO E RELACIONAMENTO.” (18) e “PRÓXIMO CICLO” (17), conforme [consulta própria](consulta_opv.sql). Ele descreve uma ação ou objetivo de acompanhamento, não necessariamente o motivo da visita não realizada.

## Método reproduzível

1. Consulta somente leitura:

```sql
SELECT ID, UFCRM, CICLO, DATA_VISITA, VISITA_TIPO, COMENTARIOS
FROM dmn_produtividade_dev.pfv_tb.propagandistas_visitacao_medica
WHERE VISITA_EFETIVA='N'
  AND DATA_VISITA >= DATE '2026-01-01' AND DATA_VISITA < DATE '2027-01-01'
  AND upper(trim(COMENTARIOS)) <> 'PROFISSIONAIS NÃO VISITADOS ATÉ O FECHAMENTO'
ORDER BY ID
```

2. `manifesto_ids.jsonl` conserva ID, ciclo, data, tipo, UFCRM e hash do comentário de cada visita. `fonte_snapshot.json` conserva a fotografia SQL usada. O texto automático “PROFISSIONAIS NÃO VISITADOS ATÉ O FECHAMENTO” foi excluído antes da extração.
3. Na extração final, cada um dos **703 comentários distintos não vazios** foi enviado uma vez ao modelo; os 10 textos da checagem inicial foram enviados novamente após ajuste do prompt e estão incluídos no custo real. As **200 visitas `-`** não precisaram de inferência. O prompt de acesso é:

```text
Você analisa somente comentários de VISITAS NÃO REALIZADAS (VISITA_EFETIVA=N).
Descubra se o texto informa uma causa concreta que impediu acesso ou contato com o médico naquela visita.
Exemplos de causa: férias/licença/ausência do médico, agenda indisponível, atendimento já encerrado quando o representante chegou, recusa de visita, restrição de entrada, mudança ou fechamento de local.
Baixo potencial, falta de oportunidade prescritiva ou opinião sobre produto NÃO são causa de acesso por si só.
Não invente motivo a partir da flag N. Se houver apenas contexto sem causa de não realização, responda false.
Se houver causa, escreva-a de modo curto, sem nomes próprios nem inferências.
Responda EXCLUSIVAMENTE JSON válido, sem markdown: {"tem_barreira_acesso":true ou false,"barreira_bruta":"causa curta" ou null}.
Para false, barreira_bruta deve ser null.
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

Foram **713 chamadas reais**, incluindo as 10 de checagem inicial e o reprocessamento dos mesmos textos com o prompt corrigido: **288.771 tokens de entrada** e **26.270 de saída** (total **315.041**). Os números vêm do `usage` de cada resposta e contam uma vez cada chave de chamada; normalizações locais não gastaram tokens. Não há conversão para dinheiro, conforme decisão do George.

A leitura manual encontrou acertos claros para férias, agenda encerrada, licença e restrição institucional. Também encontrou falsos negativos para “CONGRESSO”, “CONSULTIVO FECHADO” e “NÃO GOSTA DE RECEBER REPRESENTANTES”, além de dois falsos positivos que só diziam que o médico não atendeu. Essas correções estão registradas, sem apagar a saída original. O resultado é uma lista candidata para revisão de negócio, especialmente nas causas curtas ou ambíguas.

**Achado para decisão futura:** barreiras de acesso reais aparecem em comentários `N`. A ferramenta atual de observações do agente considera apenas `VISITA_EFETIVA='S'`; portanto, não vê esses registros. Este trabalho não altera a ferramenta.
