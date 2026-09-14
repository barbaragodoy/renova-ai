# Frontend do Portal RenovAI

Interface React do `APP_RENOVAI`, seguindo a convenção do monorepo
`AcheInfo_Apps`: cada aplicativo mantém `frontend/` e `backend/` separados.

## Stack

| Camada | Tecnologia |
|---|---|
| Biblioteca | React 19 |
| Build | Vite 6 |
| Linguagem | TypeScript |
| Estilo | Tailwind CSS 4, tokens em `src/styles/theme.css` |
| Ícones | lucide-react |

Vite foi escolhido porque é a mesma ferramenta usada no projeto do Figma Make
de onde vieram os tokens e os componentes, o que reduz adaptação. O build gera
somente arquivos estáticos, sem processo Node em produção, o que preserva a
imagem única de container definida na arquitetura da Aché.

## Identidade visual

Os tokens em `src/styles/theme.css` são cópia fiel do Figma Make
"Integrate Design System", modo Código, versão 21, extraídos em 03/08/2026.

| Token | Valor |
|---|---|
| Cor primária | `#E5177E` |
| Destaque suave | `#fce7f3` |
| Texto secundário | `#6b7280` |
| Cor destrutiva | `#d4183d` |
| Fonte | Inter, pesos 400/500/600/700 |
| Tamanho base | 16px |
| Raio base | `0.625rem` (10px) |

Os protótipos anteriores em HTML (`renovai-demo`, `backend/local_demo`) usam
valores aproximados (`#d4006b`, Quicksand e Mukta) que **não** correspondem ao
design system real. Não os use como referência de cor ou tipografia.

## Rodar em desenvolvimento

Requer Node 20 ou superior.

```bash
cd APP_RENOVAI/frontend
cp .env.example .env
npm install
npm run dev          # http://localhost:3000
```

O backend precisa estar rodando em paralelo:

```bash
# na raiz do APP_RENOVAI
uvicorn backend.app.main:app --reload    # http://localhost:8000
```

O proxy configurado em `vite.config.ts` encaminha `/agente`, `/auth`, `/chat`,
`/gerencial`, `/health`, `/insight-medico`, `/prescricoes`, `/ranking` e
`/recomendacoes` para o backend, evitando CORS e reproduzindo os mesmos
caminhos relativos do container. **Rota nova no backend precisa entrar nessa
lista**, senão o Vite devolve o `index.html` e a chamada falha sem explicação
em desenvolvimento, enquanto continua funcionando no container.

O backend precisa de `AUTH_MODE=senha` e `SESSAO_JWT_SECRET` definidos. Na
imagem única não há CORS, porque portal e API compartilham a origem.

## Build

```bash
npm run build        # gera dist/
```

## Autenticação

O modo é definido por `VITE_AUTH_MODE` e precisa acompanhar `AUTH_MODE` do
backend.

| Modo | Como entra | Situação |
|---|---|---|
| `senha` (padrão) | e-mail corporativo + senha entregue pelo time | modo atual do piloto |
| `entra_id` | conta corporativa Microsoft | destino, ainda não implementado |

Fluxo atual:

1. o usuário informa e-mail corporativo e senha;
2. o front chama `POST /auth/login`;
3. o backend confere o hash e devolve um token de sessão;
4. a sessão guarda nome, setor, e-mail e token, em `sessionStorage`;
5. o token acompanha todas as chamadas seguintes.

A senha não é gravada no navegador e não vai dentro do token. Ela é usada uma
vez no login e descartada.

As rotas de negócio exigem esse token e resolvem a identidade a partir dele. Um
e-mail informado por query é ignorado, então não é possível pedir dados de
outra pessoa mantendo a própria sessão.

### Limitação conhecida

O acesso por senha é temporário, criado para viabilizar o piloto técnico. A
entrada definitiva é pela conta corporativa.

### Caminho para o Entra ID

Três pontos concentram a mudança:

1. `VITE_AUTH_MODE=entra_id` no build do frontend;
2. criar `src/auth/entraId.ts` com a aquisição de token e ligá-lo a
   `configurarProvedorDeToken()` de `src/lib/api.ts`;
3. no backend, `AUTH_MODE=entra_id` junto com `AUTH_REQUIRE_JWT=true`.

Nesse momento `POST /auth/login` passa a responder 404 e a tela de login troca
os dois campos por um botão de acesso corporativo. O layout permanece o mesmo.

## Estrutura

```text
frontend/
├── index.html
├── vite.config.ts
├── src/
│   ├── main.tsx
│   ├── App.tsx                 abas, sessão e navegação
│   ├── auth/modo.ts            seleção do modo de autenticação
│   ├── auth/sessao.ts          sessão do navegador e validade do token
│   ├── components/ui/          componentes base
│   ├── components/CardMemoriaDeVisitas.tsx   memória de visitas, chat e ranking
│   ├── lib/api.ts              cliente HTTP e contratos
│   ├── pages/Login.tsx         identificação do propagandista
│   ├── pages/Chat.tsx          conversa, cards e blocos da resposta
│   ├── pages/Ranking.tsx       ranking do setor e gaveta de detalhes
│   ├── pages/Recomendacoes.tsx entrada, exclusão e arquivadas
│   ├── pages/Usuario.tsx       perfil, foto e dados do propagandista
│   └── styles/                 tokens e estilos globais
```

As quatro abas são montadas de forma preguiçosa e **não são desmontadas ao
trocar de aba**: o portal é usado em pé, alternando o tempo todo, e recomeçar
a carga a cada volta seria pagar a rede de novo. Quem mexer em estado de aba
precisa considerar que ele sobrevive à navegação e só morre no logout.

O texto das respostas do chat **não é escrito aqui**. Ele chega pronto do
backend, montado por código em `backend/app/chat/perfil_medico.py`. Como
alterar qualquer frase está em
`backend/app/chat/como-alterar-a-resposta-do-chat.md`.

## Protótipo de referência

Figma Make `cuZGbZpvR0aBJhixqBnYYB` ("Teste PED 2.0"). É a fonte do desenho,
não do conteúdo: o texto das respostas vem do backend.

O protótipo tem cinco abas; o portal tem quatro. **Comunicados ficou fora do
escopo por decisão de George em 10/08/2026** e não é esquecimento.

O que existe no protótipo e não foi construído, tudo decisão registrada e não
pendência técnica:

| No protótipo | Situação |
|---|---|
| Aba Comunicados | fora do escopo desde 10/08/2026 |
| Polegar para cima e para baixo na resposta | não construído; a avaliação do piloto é por formulário |
| Microfone na conversa | ditado por voz é frente separada, análise de 07/08/2026 |
| Sino de notificações | depende de Comunicados |
| Cards `rec-list`, `comunicado-card` e afins no chat | o chat responde perfil de médico; lista de recomendação é a aba própria |

**Divergências deliberadas do protótipo.** Cada tela documenta as suas no
próprio arquivo, com data e motivo: `Chat.tsx` lista quatro, `Ranking.tsx`
lista cinco. Antes de "corrigir" a tela para ficar igual ao protótipo, leia o
cabeçalho do arquivo. As mais recentes, de 03/09/2026:

- a aba usa "Recomendações" por extenso, e não o `shortLabel` "Recom." do
  protótipo;
- a última visita aparece dentro do card do médico, e não como bloco separado
  da mensagem;
- a pontuação é exibida sem casas decimais em todo o portal.


## Pendências conhecidas

> **Não tratar como pronto para produção.** O portal está publicado em
> homologação para validação técnica. Há itens bloqueantes em aberto.

Bloqueantes:

- Migração da autenticação para o Entra ID, já mapeada acima.

Demais itens:

- **Sem camada de teste no frontend.** Não há vitest nem testing-library, e
  `npm run lint` é só `tsc -b --noEmit`. O backend tem suíte de testes; o
  front não tem nenhuma. Primeira coisa a montar em desenvolvimento novo.
- **Sem ESLint.** O projeto depende do compilador do TypeScript para checagem,
  o que não pega erro de regra de hook nem de acessibilidade.
- Contraste do botão primário levemente abaixo do mínimo de acessibilidade,
  a ser tratado na revisão do design system.
- Tema escuro e paleta de gráfico ainda no padrão genérico do shadcn/ui.
- Escala de espaçamento e sombra ainda não confirmadas no design system.
- `Recomendacoes.tsx` e `Ranking.tsx` passam de 900 linhas cada e concentram
  tela, estado e formatação no mesmo arquivo. Candidatos naturais a quebra
  quando alguém for mexer neles.

### Resolvido em 03/09/2026

- **Sessão expirada.** A validade do token agora é guardada em `expiraEm` e
  conferida na leitura da sessão, e o cliente HTTP trata o 401 de qualquer
  rota de negócio devolvendo a pessoa ao login com aviso, inclusive no envio
  de foto, que não passa por `request` porque manda FormData. O 401 do próprio
  login não entra nesse caminho, porque ele não leva token.
- **Proxy incompleto.** `/chat`, `/agente` e `/ranking` não eram encaminhados,
  então conversa e ranking não funcionavam com `npm run dev`.
