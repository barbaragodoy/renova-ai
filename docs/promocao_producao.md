# Checklist de Promoção para Produção — RenovAI
**Ambiente origem:** Local (PostgreSQL + Docker + Claude/OpenAI)  
**Ambiente destino:** Aché — Azure Databricks + Genie + Entra ID  
**Última atualização:** 2026-07-07

---

## Princípio geral

> **O código não muda. A configuração muda.**  
> Todos os contratos (schemas Pydantic), regras de negócio, routers, jobs e testes
> são idênticos em local e produção. A diferença está nas variáveis de ambiente,
> nos providers (LLM, banco, auth) e nas credenciais.

---

## 1. Banco de Dados

| Item | Local | Produção | Responsável |
|---|---|---|---|
| Provider | PostgreSQL 15 via Docker | Azure Databricks SQL Warehouse (2XS para POC) | **Flávio** (infra) |
| Variável | `DATABASE_URL=postgresql://...` | `DATABASE_URL=databricks+connector://...` (JDBC) | **Flávio** |
| Driver | `psycopg2` / `SQLAlchemy` | `databricks-sql-connector` + `SQLAlchemy` via dialect `databricks` | **Colin** (backend) |
| Schema | Tabelas criadas pelos scripts `01_*.sql` | Catálogo `dmn_inteligencia_dados_prd`, schema `renovai` no Unity Catalog | **Flávio** + **Caio** (dados) |
| DDL | `data/scripts/01_create_tables.sql` | Aplicado via Databricks migrations ou Delta Lake DDL | **Caio** |
| Views gerenciais | `08_create_views_gerencial.sql` | Recriadas no catálogo de produção | **Caio** |

### Checklist banco
- [ ] Confirmar acesso ao catálogo `dmn_inteligencia_dados_prd` com o Service Principal (**Flávio**)
- [ ] Validar que o Databricks SQL Warehouse 2XS suporta a carga de requisições POC (estimativa: ~50 req/h) (**Flávio**)
- [ ] Confirmar grão e PK das tabelas de produção coincidem com o DDL local (**Caio**)
- [ ] Confirmar que `tb_hierarquia_gd` existe em produção ou tem equivalente (HUGO-08 — **Caio**)
- [ ] Configurar pool de conexões adequado para Databricks (evitar cold start do warehouse) (**Colin**)
- [ ] Validar rate limit do SQL Warehouse 2XS para POC (max concurrent queries) (**Flávio**)

---

## 2. LLM / Genie

| Item | Local | Produção | Responsável |
|---|---|---|---|
| Provider | `LLM_PROVIDER=claude` (ou `openai`/`gemini`) | `LLM_PROVIDER=genie` | **Colin** |
| Implementação | `llm/claude_provider.py` etc. | Novo `llm/genie_provider.py` (Databricks SDK) | **Colin** |
| Autenticação | Chave de API no `.env` | Service Principal no Key Vault | **Flávio** |
| Intent rules | `genie/intent_rules.json` (local) | Mesmo arquivo — alinhado com Pavan | **Colin** + **Caio** |
| Prompt schema | `nl_to_sql.py` — `SCHEMA_RESUMIDO` | Atualizar com schema real do Unity Catalog | **Colin** + **Caio** |

### Implementação do `GeniProvider` (a criar)
```python
# backend/app/llm/genie_provider.py (esboço)
from databricks.sdk import WorkspaceClient
from backend.app.llm.adapter import LLMAdapter

class GenieProvider(LLMAdapter):
    def __init__(self, settings):
        self._client = WorkspaceClient(
            host=settings.databricks_host,
            token=settings.databricks_token,  # ou SP credentials
        )
        self._space_id = settings.genie_space_id

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        # Chamar Databricks Genie via API REST ou SDK
        ...
```

### Variáveis adicionais para Genie
```env
DATABRICKS_HOST=https://<workspace>.azuredatabricks.net
DATABRICKS_TOKEN=<service-principal-token>
GENIE_SPACE_ID=<id-do-space-genie>
```

### Checklist LLM/Genie
- [ ] Implementar `llm/genie_provider.py` com Databricks SDK (**Colin**)
- [ ] Registrar `genie` como provider válido no factory `get_llm_provider()` (**Colin**)
- [ ] Validar que `intent_rules.json` está alinhado com critérios revisados por **Pavan** (**Caio** + **Colin**)
- [ ] Atualizar `SCHEMA_RESUMIDO` em `nl_to_sql.py` com o schema real do Unity Catalog (**Colin**)
- [ ] Validar timeout do Genie (produção pode ser mais lento; ajustar `LLM_TIMEOUT_SECONDS`) (**Colin**)

---

## 3. Autenticação

| Item | Local | Produção | Responsável |
|---|---|---|---|
| Provider | Auth0 free tier | Microsoft Entra ID (SSO) | **Flávio** (infra) |
| Variável | `AUTH0_DOMAIN`, `AUTH0_AUDIENCE` | `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET` | **Flávio** |
| Validação de token | JWT RS256 via Auth0 JWKS | JWT RS256 via Entra ID JWKS endpoint | **Colin** |
| Claim de e-mail | `email` no JWT Auth0 | `preferred_username` ou `upn` no JWT Entra ID — **verificar claim** | **Colin** + **Flávio** |
| Lookup de propagandista | `resolver_contexto(email)` → `tb_propagandistas.rep_email` | Mesmo fluxo, e-mail corporativo Aché | **Colin** |

### Checklist autenticação
- [ ] Confirmar qual claim JWT do Entra ID contém o e-mail corporativo (`preferred_username` x `upn`) (**Flávio**)
- [ ] Atualizar `auth/context.py` para ler o claim correto do Entra ID (**Colin**)
- [ ] Registrar o aplicativo no Entra ID com redirect URIs do frontend (**Flávio**)
- [ ] Validar que os e-mails em `tb_propagandistas.rep_email` coincidem com o UPN do Entra ID (**Caio**)

---

## 4. Secrets e Infraestrutura

| Item | Local | Produção | Responsável |
|---|---|---|---|
| Secrets | `.env` na máquina do dev | Azure Key Vault + referências em App Service / AKS | **Flávio** |
| Deploy | `uvicorn` manual / Docker Compose | Container FastAPI no Azure Container Apps ou AKS | **Flávio** + **Colin** |
| CI/CD | Não configurado | Pipeline Azure DevOps ou GitHub Actions | **Flávio** |
| Logging | `logging` padrão Python | Azure Monitor / Application Insights | **Flávio** |

### Checklist infra
- [ ] Migrar todas as variáveis do `.env` para Key Vault (sem nenhuma secret em código) (**Flávio**)
- [ ] Configurar Managed Identity para o container acessar Key Vault sem token hard-coded (**Flávio**)
- [ ] Criar pipeline de CI que executa `pytest` antes do deploy (**Flávio** + **Colin**)
- [ ] Configurar Application Insights para capturar os logs do middleware `log_requests` em `main.py` (**Flávio**)

---

## 5. O que NÃO muda (código e contratos)

Os itens abaixo são **idênticos em local e produção** e não precisam de nenhuma alteração:

| Artefato | Motivo |
|---|---|
| `backend/app/routers/` — todos os endpoints | Lógica de negócio e validações independem de provider |
| `backend/app/schemas/` — Pydantic | Contrato com o frontend imutável |
| `backend/app/auth/context.py` — `resolver_contexto()` | Lógica de resolução baseada em `tb_propagandistas` |
| `backend/app/jobs/` — todos os jobs | Regras de geração, expiração e atualização de status |
| `backend/app/genie/nl_to_sql.py` — fluxo NL→SQL | Substitui apenas o provider via factory |
| `backend/app/genie/intent_rules.json` | Único ponto de configuração de intent (após alinhamento com Pavan) |
| `backend/app/tests/` — todos os testes | Testes mockados rodam em CI sem dependências externas |
| `docs/cenarios/` — matriz e golden set | Referência de validação funcional |

---

## 6. Sequência de Promoção Recomendada

```
1. [Flávio]  Provisionar SQL Warehouse 2XS e confirmar acesso ao catálogo
2. [Caio]    Validar schema de produção e criar tb_hierarquia_gd equivalente (HUGO-08)
3. [Colin]   Implementar GeniProvider + registrar no factory
4. [Flávio]  Configurar Key Vault e Managed Identity
5. [Flávio]  Configurar Entra ID e confirmar claim de e-mail
6. [Colin]   Atualizar claim de e-mail em auth/context.py
7. [Caio+Colin] Alinhar intent_rules.json com Pavan
8. [Colin]   Atualizar SCHEMA_RESUMIDO com schema real do Unity Catalog
9. [Flávio]  Deploy do container FastAPI
10. [Todos]  Rodar golden set e matriz de testes contra produção
11. [Caio]   Executar gerar_recomendacoes para o ciclo vigente em produção
12. [Todos]  Validar endpoints com dados reais — ir/não ir para usuários piloto
```

---

## 7. Riscos e Pontos em Aberto

| Risco | Mitigação | Responsável |
|---|---|---|
| Rate limit do SQL Warehouse 2XS | Medir na POC; escalar para Small se necessário | **Flávio** |
| Genie API indisponível / timeout | `GENIE_TIMEOUT` já mapeado; fallback de mensagem amigável implementado | **Colin** |
| `tb_hierarquia_gd` sem equivalente em produção | Confirmar com Caio (HUGO-08); criar tabela ou mapeamento no Unity Catalog | **Caio** |
| Claim de e-mail divergente no Entra ID | Testar com usuário real antes do piloto; campo configurável | **Flávio** + **Colin** |
| `intent_rules.json` desatualizado | Revisar com Pavan antes do go-live; único arquivo a mudar | **Caio** |
| Critério de desempate de sugestões | A definir com Caio (consta em CLAUDE.md como ponto simulado) | **Caio** |
| Perfis autorizados além do GD | A definir; impacta endpoints gerenciais | **Caio** + **Colin** |
