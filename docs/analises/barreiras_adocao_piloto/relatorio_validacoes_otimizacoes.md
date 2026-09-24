# Validação das otimizações antes da escala — barreiras de adoção

Execução de 20/09/2026, exclusivamente sobre `VISITA_EFETIVA='S'`. O
gabarito contém as últimas decisões individuais validadas dos mesmos 150
comentários do piloto: 19 com barreira e 131 sem barreira.

## 1. Sonnet em lotes de 20

Foram feitas oito chamadas ao `databricks-claude-sonnet-5`: sete lotes de 20
e um lote final de 10. A primeira tentativa mostrou que o teto local de 1.200
tokens truncava sete arrays; ela foi preservada no rastro. A repetição com
teto de 4.000 tokens completou os oito JSONs e é a base da comparação.

O lote divergiu do gabarito em **8 de 150 resultados (5,33%)**: **7 falsos
negativos** e **1 falso positivo**. As divergências ocorreram nas posições 1,
4, 6, 12, 13 (duas ocorrências), 15 e 20. Nas posições 1–10 foram 3/80
(3,75%); nas posições 11–20, 5/70 (7,14%). Há mais erros na segunda metade,
mas não há degradação monotônica: também ocorreram erros no começo e no meio.

Entre os quatro casos limítrofes, três concordaram e o caso de molécula
diferente conforme intensidade da dor virou falso positivo na posição 20.
Os sete falsos negativos incluem baixa lembrança de marca, preferência já
estabelecida e falta de familiaridade clínica.

**Decisão:** otimização reprovada. A escala usa chamadas individuais.

## 2. llama-4-maverick como filtro binário

O endpoint disponível no workspace é `databricks-llama-4-maverick`. As 150
respostas tiveram JSON válido. Houve **138 concordâncias em 150 (92,00%)**,
com **9 falsos negativos** e **3 falsos positivos**.

Nos quatro casos difíceis, houve **3 concordâncias em 4 (75,00%)**. O modelo
marcou indevidamente como barreira o uso de molécula diferente em dor mais
intensa. Também perdeu obstáculos de baixa lembrança, desconhecimento de
marca e protocolo/diretriz preferido.

**Decisão:** otimização reprovada. O Maverick não será usado para filtrar a
escala.

## 3. Corte de comentários com menos de 20 caracteres

Foi lida uma amostra determinística de **30** dos 99 textos distintos abaixo
de 20 caracteres. Nenhum contém barreira curta de adoção. A inspeção
complementar dos outros 69 também não encontrou barreira. Alguns textos
curtos têm conteúdo factual sem obstáculo, como solicitação de produto,
compromisso de prescrição ou médico não localizado; por isso o corte serve
somente para evitar a chamada ao modelo e não para fundir as categorias de
qualidade.

**Decisão:** otimização aprovada. Os 99 textos abaixo de 20 caracteres serão
decididos sem chamada ao modelo, preservando separadamente
`SEM_CONTEUDO_REAL` e `COM_CONTEUDO_SEM_BARREIRA`.

## Classificação manual dos mais frequentes

Os **250 textos mais frequentes**, representando **600 visitas**, foram lidos
individualmente. O arquivo `classificacoes_manuais.jsonl` registra texto,
hash, frequência, decisão, barreira bruta e justificativa. Resultado: 133
`SEM_CONTEUDO_REAL`, 109 `COM_CONTEUDO_SEM_BARREIRA` e 8 `COM_BARREIRA`.

## Método escolhido para a escala

- Aplicar diretamente as 250 decisões manuais.
- Não chamar o modelo para textos abaixo de 20 caracteres, conforme a revisão.
- Reaproveitar as decisões individuais validadas do piloto quando aplicável.
- Chamar somente `databricks-claude-sonnet-5`, individualmente, com o prompt
  final para os demais textos.

O universo tem 9.571 comentários distintos. Depois da união entre os 250
manuais e os 99 textos curtos (25 aparecem nos dois grupos), restam 9.247
textos elegíveis a Sonnet. Desses, 146 já têm decisão individual validada no
piloto; portanto a escala exige 9.101 chamadas novas.

## Consumo das validações

- Sonnet em lote, repetição válida: 29.319 tokens de entrada e 10.908 de saída.
- Maverick: 51.692 tokens de entrada e 1.650 de saída.
- A tentativa Sonnet truncada permanece registrada separadamente e consumiu
  29.319 tokens de entrada e 8.918 de saída.

Arquivos de auditoria com comentário bruto são ignorados pelo Git por conterem
dados de visita. Os resumos e este relatório não misturam dados da passada N.
