# Barreiras de adoção — ruído e piloto (passada S)

Leitura de 18/09/2026. Este relatório usa **somente `VISITA_EFETIVA='S'`**. A extração parou em **150 comentários distintos do piloto**; não há lista final de barreiras de adoção nesta etapa.

## Recorte e proporção de ruído

O recorte aprovado seleciona 0,8% por hash determinístico de `ID` nos ciclos completos `202607` e `202608`, sem filtro de comprimento ou qualidade:

```sql
SELECT ID, UFCRM, SETOR, CICLO, DATA_VISITA, VISITA_TIPO, COMENTARIOS
FROM dmn_produtividade_dev.pfv_tb.propagandistas_visitacao_medica
WHERE VISITA_EFETIVA='S' AND CICLO IN ('202607','202608')
  AND pmod(xxhash64(ID),100000)<800 ORDER BY ID
```

São **9.940 visitas**, **9.571 comentários distintos** e **638 visitas cujo texto aparece em mais de uma visita** (**6,42%**). A deduplicação elimina **369 chamadas**, pois preserva uma chamada para cada texto repetido. Portanto, o número correto de chamadas para todo o recorte seria **9.571**; **9.302** resulta de subtrair indevidamente as 638 visitas, inclusive a primeira ocorrência de cada texto.

A [consulta SQL de ruído](contagem_ruido.sql) encontrou **85 visitas com padrões literais sem conteúdo real**, ou **0,86%** do recorte. Os padrões incluem “RELEMBREI”, “VISITA REMOTA”, “SEM COMENTÁRIOS”, notas genéricas de reforço e nomes de produto isolados identificados na leitura. Esta é uma **contagem conservadora por regras explícitas**, não uma revisão semântica exaustiva das 9.940 visitas. Um comentário factual sem obstáculo, como prescrição já existente ou feedback positivo, pertence à classe distinta `COM_CONTEUDO_SEM_BARREIRA`; não foi incluído nesses 85.

Os dois percentuais servem de referência para avaliar representatividade quando houver escala. A taxa de duplicação **já** mostra diferença relevante: na amostra, o excesso de visitas duplicadas é **3,71%**; no conjunto `S` de 2026, os **4.947.363** registros e **3.477.987** textos distintos medidos por SQL implicam **29,70%** de excesso. Assim, a extrapolação da deduplicação da amostra é frágil para orçamento da base completa.

## Prompt, execução e leitura do piloto

`data/scripts/descobrir_barreiras_adocao_piloto.py` usa `ServingDatabricks.extrair_estruturado` com prompt e arquivos exclusivos desta passada. Seleciona os 150 textos por SHA-256 do comentário dentro do recorte. O script impõe limite de 150 textos e os arquivos `manifesto_ids.jsonl`, `manifesto_piloto.jsonl` e `extracoes_*.jsonl` preservam o recorte e as respostas brutas.

O prompt final ajustado, ainda limitado ao piloto, é:

```text
Você analisa somente comentários de VISITAS REALIZADAS (VISITA_EFETIVA=S).
Descubra se o texto relata obstáculo concreto para o médico adotar ou prescrever uma marca/produto apresentado.
Exemplos: médico não lembra a marca nas oportunidades, declara preferência por concorrente com motivo, considera custo alto, tem dúvida ou receio de eficácia/segurança, ainda não tem experiência clínica e isso impede a adoção.
Não transforme simples ação do propagandista (reforço, apresentação, foco em preço, amostra), característica de paciente, oportunidade positiva, elogio de custo-benefício ou ausência neutra de feedback em barreira.
Não deduza barreira só porque o texto não informa prescrição, diz que o médico não prescreve algo ou menciona marca concorrente sem explicar a causa. Exemplos para responder false: “não prescreve CBD; perguntou preço de outro produto; preço é importante”; “não explicou por que prescreve concorrente, mas confia na nossa marca”; “usa nosso produto em casos leves e outra molécula em casos graves”. Se a farmácia troca por genérico depois de o médico prescrever a marca, isso não é barreira de adoção PELO MÉDICO. Erros de digitação não invalidam uma barreira clara.
Se houver obstáculo, escreva a causa curta e fiel ao texto, sem nomes próprios. Não use categorias predefinidas.
Responda EXCLUSIVAMENTE JSON válido, sem markdown e sem blocos de código: {"tem_barreira_adocao":true ou false,"barreira_bruta":"obstáculo curto" ou null}.
Para false, barreira_bruta deve ser null.
```

Na leitura inicial dos 150 textos, **23** respostas indicaram barreira e **127** não indicaram; todas terminaram com JSON interpretável após aceitar blocos Markdown integrais. Acertos observados: relato de marca “pouco lembrada” com amostras do concorrente; “DODIBE NÃO ESTAVA LEMBRANDO O NOME”; e tratamento “mais difícil devido ao custo”. Negativos adequados: médico já prescrevendo e elogiando a marca; comentário sobre paciente que interrompeu tratamento, sem obstáculo atribuído ao médico.

Erros observados e ajuste: “FOCO EM PREÇO” foi inicialmente tratado como objeção do médico; substituição por genérico **na farmácia após prescrição** foi confundida com não adoção pelo médico. Na revisão de 20 textos, esses dois casos passaram a `false`. Persistiram duas inferências indevidas: prescrever concorrente sem informar o motivo e usar outra molécula para dor de intensidade diferente. O prompt final tornou esses contraexemplos explícitos; ambos passaram a `false` na checagem final de dois textos. As versões anteriores dos prompts permanecem constantes nomeadas no script para auditoria. O piloto indica que a leitura manual continua necessária antes de qualquer escala.

## Custo real do piloto e projeção para decisão

O piloto envolveu **150 textos distintos** e **184 chamadas reais** contando as versões de checagem e ajuste: **122.238 tokens de entrada** e **6.067 de saída** (total **128.305**). A versão inicial de 150 textos consumiu **97.915 entrada / 4.930 saída**. O prompt final acrescentou **115 tokens de entrada por chamada** nos dois mesmos textos usados para comparar versões. Para projeção, usei **767,8 entrada** e **32,9 saída** por comentário, sem preço em dinheiro.

| Base da decisão | Chamadas estimadas | Tokens de entrada | Tokens de saída | Total de tokens |
|---|---:|---:|---:|---:|
| Recorte aprovado, contagem exata | 9.571 | 7.348.295 | 314.567 | 7.662.862 |
| Base completa, extrapolação matemática do excesso da amostra | 4.763.703 | 3.657.412.373 | 156.567.039 | 3.813.979.412 |
| Base completa, desconto de 638/9.940 solicitado | 4.629.816 | 3.554.618.398 | 152.166.619 | 3.706.785.017 |
| Base completa, distintos já medidos por SQL em 2026 | 3.477.987 | 2.670.282.486 | 114.309.839 | 2.784.592.325 |

As **duas bases solicitadas** são o recorte aprovado e a base completa. Dentro da base completa, a linha do desconto de **638/9.940** mostra literalmente a extrapolação pedida, mas ela **superestima a economia da deduplicação**: 638 é o número de visitas em grupos de texto repetido, enquanto apenas 369 visitas são excedentes. A linha do excesso de 369/9.940 corrige essa conta. A linha de **distintos já medidos** usa a contagem real disponível para 2026 e é mais informativa para orçamento desse conjunto. Nenhuma dessas projeções inclui novas iterações de prompt, falhas com cobrança ou eventual agrupamento por modelo.

**Limite desta execução:** nenhum comentário fora dos 150 textos do piloto foi enviado ao modelo nesta passada. A escala do recorte ou da base completa aguarda confirmação após envio desta estimativa ao George e ao Bruno.
