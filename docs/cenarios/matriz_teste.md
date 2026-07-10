# Matriz de Cenários de Teste — RenovAI Local
**Referência:** GEORGE-06 (matrizes de teste) e GEORGE-13 (escopo gerencial)  
**Ciclo de referência nos testes:** `202507`  
**Corte local:** `posicao_ranking <= 100` (equivale a `<= 400` em produção)

---

## Legenda de Status

| Status | Significado |
|---|---|
| `PENDENTE` | Aguardando ação do propagandista ou GD |
| `APLICADA` | Médico entrou ou saiu do painel conforme sugerido |
| `DESCONSIDERADA` | Rep ou GD optou por não seguir a sugestão |
| `EXPIRADA` | Ciclo encerrado sem ação |

---

## Grupo 1 — Resolução de Contexto (`/auth/contexto`)

| ID | Cenário | Entrada | Resultado Esperado | Status HTTP |
|---|---|---|---|---|
| C-CTX-01 | E-mail com 1 cadastro ativo | `ana.silva@ache.com.br` | `SETOR_RESOLVIDO` com matrícula, setor, cod_linha, nome | 200 |
| C-CTX-02 | E-mail não cadastrado | `nao.existe@ache.com.br` | `PROPAGANDISTA_NAO_ENCONTRADO` + mensagem orientativa | 200 |
| C-CTX-03 | E-mail com 2 cadastros ativos (mock) | qualquer e-mail com duplicata | `IDENTIDADE_AMBIGUA` + mensagem orientativa | 200 |
| C-CTX-04 | Rep inativo | e-mail de rep com `ativo=FALSE` | `PROPAGANDISTA_NAO_ENCONTRADO` | 200 |

---

## Grupo 2 — Listas de Recomendação

### 2.1 Entrada no Painel (`GET /recomendacoes/entrada`)

| ID | Cenário | Dados de Entrada | Resultado Esperado | Status `tb_recomendacoes_painel` |
|---|---|---|---|---|
| C-ENT-01 | Propagandista com pendências de entrada | REP001, ciclo 202507 | Lista com ≤ 5 itens, tipo `ENTRADA_PAINEL`, todos `PENDENTE` | `PENDENTE` |
| C-ENT-02 | Propagandista sem pendências de entrada | REP sem candidatos no ranking fora do painel | `total: 0`, lista vazia | — |
| C-ENT-03 | Contexto não resolvido | e-mail inválido | HTTP 403 com status `PROPAGANDISTA_NAO_ENCONTRADO` | — |
| C-ENT-04 | Limite de 5 registros respeitado | REP com 10+ candidatos elegíveis | Retorna exatamente 5 itens ordenados por `soma_pontuacao DESC` | `PENDENTE` |
| C-ENT-05 | Médico já no painel não aparece | REP com médico pos 50 já no painel | Médico ausente da lista de entrada | — |

### 2.2 Revisão do Painel (`GET /recomendacoes/revisao`)

| ID | Cenário | Dados de Entrada | Resultado Esperado | Status `tb_recomendacoes_painel` |
|---|---|---|---|---|
| C-REV-01 | Propagandista com pendências de revisão | REP001, ciclo 202507 | Lista com ≤ 5 itens, tipo `REVISAO_PAINEL`, todos `PENDENTE` | `PENDENTE` |
| C-REV-02 | Médico abaixo do corte no painel | médico pos 101+ no painel | Aparece em revisão com `motivo_revisao = ABAIXO_CORTE` | `PENDENTE` |
| C-REV-03 | Médico sem visita há > 5 meses | médico no painel, última visita jan/2025 | Aparece em revisão com `motivo_revisao = SEM_VISITA_5_MESES` | `PENDENTE` |
| C-REV-04 | Propagandista sem pendências de revisão | REP sem médicos elegíveis para revisão | `total: 0`, lista vazia | — |

---

## Grupo 3 — Desconsiderar (`POST /recomendacoes/desconsiderar`)

| ID | Cenário | Dados de Entrada | Resultado Esperado | Status `tb_recomendacoes_painel` |
|---|---|---|---|---|
| C-DESC-01 | Desconsiderar com sucesso | `id_recomendacao` PENDENTE do próprio rep | `sucesso: true` | `PENDENTE` → `DESCONSIDERADA` |
| C-DESC-02 | Recomendação não encontrada | UUID inexistente | HTTP 404 | — |
| C-DESC-03 | Recomendação de outro propagandista | UUID de REP002 tentado por REP001 | HTTP 403 | inalterado |
| C-DESC-04 | Já desconsiderada | `id_recomendacao` com status `DESCONSIDERADA` | HTTP 409 | inalterado |
| C-DESC-05 | Já aplicada | `id_recomendacao` com status `APLICADA` | HTTP 409 | inalterado |
| C-DESC-06 | Sai da lista após desconsiderar | Desconsiderar + consultar lista | Médico não aparece mais na lista `PENDENTE` | `DESCONSIDERADA` |

---

## Grupo 4 — Jobs de Ciclo

### 4.1 `gerar_recomendacoes`

| ID | Cenário | Condição | Resultado Esperado | Job |
|---|---|---|---|---|
| C-JOB-01 | Médico novo elegível para entrada | pos ≤ 100, fora do painel | Insere ENTRADA_PAINEL PENDENTE | `gerar_recomendacoes` |
| C-JOB-02 | Médico recorrente (já recomendado no ciclo) | mesmo ufcrm + rep_matricula + tipo + ciclo | Incrementa `qtd_vezes_recomendado`, não duplica | `gerar_recomendacoes` |
| C-JOB-03 | Médico abaixo do corte no painel → revisão | pos > 100, ativo no painel | Insere REVISAO_PAINEL com `motivo = ABAIXO_CORTE` | `gerar_recomendacoes` |
| C-JOB-04 | Médico sem visita → revisão | no painel, última visita > 5 meses atrás | Insere REVISAO_PAINEL com `motivo = SEM_VISITA_5_MESES` | `gerar_recomendacoes` |

### 4.2 `atualizar_status`

| ID | Cenário | Condição | Resultado Esperado | Job |
|---|---|---|---|---|
| C-JOB-05 | ENTRADA_PAINEL aplicada | médico entrou no painel no dia seguinte | Status → `APLICADA` | `atualizar_status` |
| C-JOB-06 | REVISAO_PAINEL aplicada | médico saiu do painel | Status → `APLICADA` | `atualizar_status` |
| C-JOB-07 | Médico ainda pendente | sem mudança de painel | Status permanece `PENDENTE`, `data_ultima_verificacao` atualizado | `atualizar_status` |

### 4.3 `novo_ciclo`

| ID | Cenário | Condição | Resultado Esperado | Job |
|---|---|---|---|---|
| C-JOB-08 | Expiração de PENDENTE | Transição 202507 → 202508 | PENDENTE do 202507 → `EXPIRADA` | `novo_ciclo` |
| C-JOB-09 | Geração para novo ciclo | Após expiração | Novos registros PENDENTE no 202508 | `novo_ciclo` → `gerar_recomendacoes` |
| C-JOB-10 | Médico desconsiderado volta no ciclo novo | DESCONSIDERADA no 202507 | Pode gerar novo PENDENTE no 202508 (histórico independente) | `novo_ciclo` |

---

## Grupo 5 — Visão Gerencial

| ID | Cenário | Dados de Entrada | Resultado Esperado | Status HTTP |
|---|---|---|---|---|
| C-GD-01 | GD consulta indicadores do seu escopo | `gd_email=marcos.vieira@ache.com.br` | Métricas dos reps REP001–REP003 | 200 |
| C-GD-02 | GD lista propagandistas do seu escopo | mesmo GD | Lista com REP001, REP002, REP003 e contagens | 200 |
| C-GD-03 | GD acessa recomendações de rep no escopo | REP001 pertence ao GD001 | Lista retornada | 200 |
| C-GD-04 | GD tenta acessar rep fora do escopo | REP007 não pertence ao GD001 | HTTP 403 | 403 |
| C-GD-05 | E-mail de GD inválido | e-mail sem registro em `tb_hierarquia_gd` | HTTP 403 | 403 |
| C-GD-06 | Filtro por tipo na visão gerencial | `tipo=REVISAO_PAINEL` | Apenas REVISAO_PAINEL retornado | 200 |
| C-GD-07 | Filtro por status na visão gerencial | `status=DESCONSIDERADA` | Apenas DESCONSIDERADA retornado | 200 |
| C-GD-08 | `motivo_desconsideracao` acessível ao GD | recomendação DESCONSIDERADA com motivo | Campo retornado no payload | 200 |

---

## Grupo 6 — Motor NL-to-SQL (`/prescricoes/consultar`)

| ID | Cenário | Pergunta | Contexto | Resultado Esperado | Status |
|---|---|---|---|---|---|
| C-NL-01 | Pergunta operacional com filtro de setor | "Quais médicos prescreveram mais Venlaxin?" | setor=SP_INTERIOR | SQL com `WHERE setor = 'SP_INTERIOR'`, resposta em PT | OK |
| C-NL-02 | Pergunta de total geral sem filtro | "Qual o total geral de prescrições no Brasil?" | qualquer setor | Intent=TOTAL_GERAL; SQL sem filtro de setor | OK |
| C-NL-03 | Período explícito respeitado | "Prescriptions no 1º trimestre" | qualquer | SQL com filtro de data do 1º trimestre | OK |
| C-NL-04 | Sem período → YTD aplicado | "Quantas prescrições de Lisinopril?" | qualquer | SQL com `data_prescricao >= {ano}-01-01` | OK |
| C-NL-05 | Propagandista não encontrado | qualquer pergunta | e-mail inválido | HTTP 403, contexto não resolvido | — |
| C-NL-06 | LLM timeout | qualquer pergunta | válido | HTTP 504, código `GENIE_TIMEOUT` | — |
| C-NL-07 | LLM retorna resposta vazia | qualquer pergunta | válido | HTTP 502, código `EMPTY_RESPONSE` | — |
| C-NL-08 | Erro ao executar SQL gerado | SQL sintaticamente inválido gerado pelo LLM | válido | HTTP 502, código `GENIE_ERROR` | — |

---

## Cobertura por Tarefa

| Tarefa | Cenários cobertos |
|---|---|
| GEORGE-06 | C-CTX, C-ENT, C-REV, C-DESC, C-JOB |
| GEORGE-13 | C-GD |
| BARBARA-02 | C-CTX |
| BARBARA-04/05 | C-ENT, C-REV |
| BARBARA-06 | C-DESC |
| BARBARA-03/07 | C-NL |
| HUGO-04/05 | C-JOB-01 a 04 |
| HUGO-06 | C-JOB-05 a 07 |
| HUGO-07 | C-JOB-08 a 10 |
