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

O proxy configurado em `vite.config.ts` encaminha `/auth`, `/recomendacoes`,
`/prescricoes`, `/insight-medico`, `/gerencial` e `/health` para o backend,
evitando CORS e reproduzindo os mesmos caminhos relativos do container.

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
│   ├── App.tsx
│   ├── auth/modo.ts            seleção do modo de autenticação
│   ├── auth/sessao.ts          sessão do navegador
│   ├── components/ui/          componentes base
│   ├── lib/api.ts              cliente HTTP e contratos
│   ├── pages/Login.tsx         identificação do propagandista
│   └── styles/                 tokens e estilos globais
```

## Pendências conhecidas

> **Não tratar como pronto para produção.** O portal está publicado em
> homologação para validação técnica. Há itens bloqueantes em aberto.

Bloqueantes:

- **Sessão expirada não é tratada.** O token vale 60 minutos, mas a interface
  não guarda essa validade. Depois do prazo, a tela segue mostrando o usuário
  como autenticado e as chamadas falham sem devolver ao login. Precisa guardar
  a expiração, limpar a sessão ao receber 401 e avisar a pessoa.
- Migração da autenticação para o Entra ID, já mapeada acima.

Demais itens:

- Contraste do botão primário levemente abaixo do mínimo de acessibilidade,
  a ser tratado na revisão do design system.
- Tema escuro e paleta de gráfico ainda no padrão genérico do shadcn/ui.
- Escala de espaçamento e sombra ainda não confirmadas no design system.
- Telas de Recomendações, Home conversacional e Usuário ainda não construídas.
