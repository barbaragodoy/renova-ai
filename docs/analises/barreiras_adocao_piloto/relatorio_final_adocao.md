# Barreiras de adoção — validações e escala completa do recorte

Execução concluída em 20/09/2026. Este relatório contém exclusivamente a
**Passada 1**, `VISITA_EFETIVA='S'`. Nenhum dado, variável ou resultado da
passada de acesso foi usado.

## Resultado executivo

O recorte aprovado contém **9.940 visitas** e **9.571 comentários distintos**
dos ciclos completos `202607` e `202608`, selecionados por hash determinístico
de `ID`. A extração terminou com decisão para **9.571/9.571 textos**, sem erro
de formato ou chamada pendente.

Foram consolidadas **16 barreiras candidatas**. Como um mesmo
comentário pode declarar mais de uma causa, as frequências das barreiras podem
se sobrepor e não devem ser somadas. A frequência é ponderada pelo número de
visitas reais associado ao texto deduplicado; médicos distintos usam `UFCRM`.

| Barreira candidata | Visitas | Médicos distintos | Comentários distintos | Comparação com 23 positivos originais |
|---|---:|---:|---:|---|
| Baixa lembrança da marca | 374 | 373 | 371 | Já aparecia |
| Preferência terapêutica ou por concorrente já estabelecida | 258 | 258 | 257 | Já aparecia |
| Custo ou baixa acessibilidade financeira | 121 | 121 | 119 | Já aparecia |
| Preferência ou limitação de formulação, apresentação ou posologia | 108 | 108 | 108 | Já aparecia |
| Hábito, protocolo ou diretriz consolidada | 86 | 86 | 83 | Já aparecia |
| Dúvida ou desconhecimento técnico | 61 | 61 | 60 | Já aparecia |
| Falta de experiência ou incorporação à prática | 56 | 56 | 55 | Já aparecia |
| Restrição institucional ou da rede de atendimento | 56 | 56 | 56 | Já aparecia |
| Prescrição por molécula ou genérico em vez da marca | 50 | 50 | 50 | Já aparecia |
| Receio de segurança ou tolerabilidade | 50 | 50 | 50 | Já aparecia |
| Baixa disponibilidade ou desabastecimento | 45 | 45 | 43 | Já aparecia |
| Resistência, percepção ou adesão do paciente | 44 | 43 | 43 | Nova |
| Falta ou desequilíbrio de amostras | 34 | 34 | 34 | Já aparecia |
| Dúvida sobre eficácia, benefício ou evidência | 31 | 31 | 31 | Nova |
| Resistência ou baixo interesse do médico | 30 | 30 | 30 | Nova |
| Restrição clínica específica à adoção | 18 | 18 | 18 | Nova |

## Comparação explícita com as 23 ocorrências do piloto original

As “23 do piloto” eram **23 comentários marcados como positivos**, não 23
categorias consolidadas. Aplicando o mesmo vocabulário pós-extração, as
categorias abaixo já apareciam nessas 23 ocorrências:

- Baixa lembrança da marca
- Preferência terapêutica ou por concorrente já estabelecida
- Custo ou baixa acessibilidade financeira
- Preferência ou limitação de formulação, apresentação ou posologia
- Hábito, protocolo ou diretriz consolidada
- Dúvida ou desconhecimento técnico
- Falta de experiência ou incorporação à prática
- Restrição institucional ou da rede de atendimento
- Prescrição por molécula ou genérico em vez da marca
- Receio de segurança ou tolerabilidade
- Baixa disponibilidade ou desabastecimento
- Falta ou desequilíbrio de amostras

As categorias abaixo só apareceram quando o recorte completo foi processado:

- Resistência, percepção ou adesão do paciente
- Dúvida sobre eficácia, benefício ou evidência
- Resistência ou baixo interesse do médico
- Restrição clínica específica à adoção

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

### Baixa lembrança da marca

- “não lembra da marca nas oportunidades de prescrição”
- “dificuldade em memorizar o nome da marca”
- “falta de lembrança da marca no momento da prescrição”

### Preferência terapêutica ou por concorrente já estabelecida

- “prescreve concorrente devido a campanha promocional de compre um ganhe outro”
- “médico tem hábito de prescrever pela substância ou marca concorrente, precisa associar a marca”
- “dá preferência ao concorrente Puran em vez de Levoid em casos de hipotireoidismo”

### Custo ou baixa acessibilidade financeira

- “custo alto dificulta prescrição para população carente”
- “custo elevado do produto pode afetar adesão do paciente”
- “concorrente considerado mais acessível (preço)”

### Preferência ou limitação de formulação, apresentação ou posologia

- “prefere fórmulas isoladas e clean label, não gosta de combinadas”
- “Preferia a apresentação líquida para titular dose em pacientes novos e idosos com dificuldade de deglutição, e questiona a mudança para tablete”
- “ausência da apresentação de 60 mg, considerada diferencial importante”

### Hábito, protocolo ou diretriz consolidada

- “médicos seguem protocolo antigo de suplementação”
- “não tem hábito de prescrever a dose de 38mcg, prescreve 25mcg e 50mcg”
- “produto ainda não está no hábito de prescrição do médico”

### Dúvida ou desconhecimento técnico

- “médica precisa ser lembrada mais vezes e demonstra pouco conhecimento dos produtos”
- “confusão na prescrição pela quantidade de marcas e indicações da família de produtos”
- “precisa entender melhor o mecanismo do produto antes de adotar”

### Falta de experiência ou incorporação à prática

- “não tem muita experiência com o produto”
- “marca ainda não está incorporada na prática diária do médico”
- “ainda não tem experiência prática com canabidiol e não teve oportunidade de usar o produto na prática clínica”

### Restrição institucional ou da rede de atendimento

- “sistema hospitalar exige prescrição por molécula, dificultando uso do nome comercial”
- “na UBS não pode prescrever a marca”
- “prescrição segue normas da rede, priorizando moléculas disponíveis (FP) em vez do produto”

### Prescrição por molécula ou genérico em vez da marca

- “Prescreve apenas moléculas devido ao custo”
- “não tem costume de colocar a marca no receituário”
- “Prescreve pela substância, não pela marca, e precisa de amostras para lembrar da marca”

### Receio de segurança ou tolerabilidade

- “objeção ao uso em pacientes com intolerância à lactose”
- “pacientes sensíveis apresentam reações adversas exacerbadas a esse medicamento, levando a uso mais restrito”
- “preocupação com a quantidade de lactose na losartana”

### Baixa disponibilidade ou desabastecimento

- “preocupação com falta do produto impede retomar a prescrição”
- “farmácias desabastecidas do produto, dificultando pacientes obterem a medicação prescrita”
- “pacientes não encontraram o produto disponível e compraram concorrente”

### Resistência, percepção ou adesão do paciente

- “pacientes já se automedicam com amoxicilina/clavulanato antes da consulta, levando a preferir outras opções”
- “Pacientes resistem à forma líquida, dificultando adesão”
- “dificuldade de adesão das pacientes ao tratamento”

### Falta ou desequilíbrio de amostras

- “Não prescreve os antibióticos porque não recebe amostras, enquanto recebe de concorrentes”
- “concorrente deixa mais amostras, o que leva a prescrever mais o concorrente”
- “maior volume de amostras do concorrente influencia preferência por ele em vez da duloxetina”

### Dúvida sobre eficácia, benefício ou evidência

- “não tem muita confiança ainda no produto no Brasil”
- “Percepção de falta de estudos robustos sobre canabidiol em psiquiatria”
- “considera que a droga não atinge outras partes do corpo e falta estudo específico/robusto”

### Resistência ou baixo interesse do médico

- “não gosta da classe do produto”
- “médico fechado a mudar prescrição, alega que produto tem atuação apenas de concorrência”
- “médica ainda sem certeza se vai prescrever o produto”

### Restrição clínica específica à adoção

- “não inicia tratamento para asma, apenas resgate na emergência, pois entende pacientes já diagnosticados por outro médico”
- “não costuma iniciar tratamento para ansiedade e depressão, limitando oportunidade para Exodus”
- “não prescreve de primeira, reserva para casos refratários, priorizando repositor de flora antes”

## Padrões fora da lista de adoção

- **Baixa oportunidade clínica ou desalinhamento com o perfil atendido**: 75 visitas e 75 médicos distintos.
- **Substituição da marca após a prescrição na farmácia**: 8 visitas e 8 médicos distintos.
- **Limitação do contexto da visita, sem barreira de adoção**: 2 visitas e 2 médicos distintos.

Esses padrões ficam no rastro de auditoria, mas não entram na lista de
barreiras de adoção: baixa oportunidade ou perfil de pacientes é contexto
clínico, conforme a regra explícita do prompt; troca feita pela farmácia
acontece depois de o médico prescrever; tempo/abertura da visita não demonstra
obstáculo do médico para adotar.

## Qualidade e ausência de barreira

| Classe | Comentários distintos | Visitas |
|---|---:|---:|
| `SEM_CONTEUDO_REAL` | 199 | 399 |
| `COM_CONTEUDO_SEM_BARREIRA` | 8.327 | 8.488 |
| `COM_BARREIRA` (saída bruta antes das exclusões de agrupamento) | 1.045 | 1.053 |

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
Você analisa somente comentários de VISITAS REALIZADAS (VISITA_EFETIVA=S).
Descubra se o texto relata obstáculo concreto para o médico adotar ou prescrever uma marca/produto apresentado.
Exemplos: médico não lembra a marca nas oportunidades, declara preferência por concorrente com motivo, considera custo alto, tem dúvida ou receio de eficácia/segurança, ainda não tem experiência clínica e isso impede a adoção.
Não transforme simples ação do propagandista (reforço, apresentação, foco em preço, amostra), característica de paciente, oportunidade positiva, elogio de custo-benefício ou ausência neutra de feedback em barreira.
Não deduza barreira só porque o texto não informa prescrição, diz que o médico não prescreve algo ou menciona marca concorrente sem explicar a causa. Exemplos para responder false: “não prescreve CBD; perguntou preço de outro produto; preço é importante”; “não explicou por que prescreve concorrente, mas confia na nossa marca”; “usa nosso produto em casos leves e outra molécula em casos graves”. Se a farmácia troca por genérico depois de o médico prescrever a marca, isso não é barreira de adoção PELO MÉDICO. Erros de digitação não invalidam uma barreira clara.
Se houver obstáculo, escreva a causa curta e fiel ao texto, sem nomes próprios. Não use categorias predefinidas.
Responda EXCLUSIVAMENTE JSON válido, sem markdown e sem blocos de código: {"tem_barreira_adocao":true ou false,"barreira_bruta":"obstáculo curto" ou null}.
Para false, barreira_bruta deve ser null.
```

## Consumo real em tokens

| Etapa | Chamadas | Entrada | Saída | Total |
|---|---:|---:|---:|---:|
| Escala Sonnet individual, incluindo retries cobrados | 10.660 | 6.998.350 | 305.255 | 7.303.605 |
| Validação Sonnet em lote, tentativa truncada | 8 | 29.319 | 8.918 | 38.237 |
| Validação Sonnet em lote, JSON completo | 8 | 29.319 | 10.908 | 40.227 |
| Validação Maverick | 150 | 51.692 | 1.650 | 53.342 |
| **Total desta execução** | **10.826** | **7.108.680** | **326.731** | **7.435.411** |

As 10.660 chamadas da escala incluem 9.101 primeiras tentativas, 1.531
retries após HTTP 429/erro de formato, 27 retries com teto maior e 1 retry
final. Chamadas HTTP 429 registraram usage zero. O total não inclui o piloto
original, executado antes desta validação.

## Separação de dados

Todos os scripts, variáveis e artefatos citados usam somente a passada de
adoção (`S`). Nenhum dado da passada de acesso (`N`) foi lido, agregado ou
incluído neste relatório.
