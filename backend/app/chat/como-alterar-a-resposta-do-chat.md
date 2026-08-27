# Como alterar a resposta do chat

> Status em 10/08/2026: em uso pelo endpoint `POST /chat/perfil-medico`. Toda alteração de texto, de regra de escrita ou de orientação ao propagandista passa por este documento e por `perfil_medico.py`.

Este arquivo é o manual do padrão da resposta que o propagandista lê no chat do Portal RenovAI. Ele existe porque quem vai mudar uma frase, acrescentar uma orientação ou criar um tipo novo de resposta nem sempre é quem escreveu o código.

Leia até o fim antes da primeira alteração. Depois disso, a seção **Onde fica cada texto** resolve a maioria dos casos sozinha.

## O que a resposta é, e o que ela não é

A resposta **não é escrita por modelo de linguagem**. Ela é montada por código e é sempre igual para o mesmo dado.

O texto inteiro sai de **uma consulta só**, a `SQL_PERFIL`. O fluxo completo do
endpoint faz duas: antes dela roda a `SQL_LOCALIZA`, que descobre de qual médico
a pergunta fala. A segunda é a que alimenta cada frase.

Isso foi decidido por medição em 09/08/2026, com seis casos, três repetições e sete modelos servidos pelo Databricks:

| Variante | Respostas limpas | Casos idênticos nas três repetições |
|---|---:|---:|
| Formatador determinístico, sem LLM | 18 / 18 | 6 / 6 |
| Melhor LLM, `gpt-oss-120b` | 16 / 18 | 0 / 6 |
| `llama-4-maverick`, o que estava configurado | 7 / 18 | 3 / 6 |

Nenhum modelo foi ao mesmo tempo correto e estável, e resposta instável não passa em homologação: o mesmo médico produzia texto diferente a cada execução.

**O LLM continua no desenho, em outro lugar.** Quando o roteador não reconhece a pergunta, o endpoint devolve `FORA_DO_ESCOPO` e o canal encaminha para o Genie. Traduzir pergunta livre para SQL é tarefa de modelo. Escrever a resposta final não é.

## O caminho da pergunta até a tela

```
pergunta do propagandista
        |
        v
  rotear()                    classifica a intenção, sem modelo
        |
        +--> intenção desconhecida --> FORA_DO_ESCOPO --> Genie
        |
        v
  SQL_LOCALIZA                acha o médico dentro do setor da identidade
        |
        +--> zero linhas  --> MEDICO_NAO_ENCONTRADO
        +--> duas ou mais --> MEDICO_AMBIGUO, com a lista para escolher
        |
        v
  SQL_PERFIL                  uma consulta, uma linha, tudo que o texto precisa
        |
        v
  montar_payload()            cards, chips e o texto de cada chip
        |
        v
  PerfilResponse (JSON)
```

O setor **nunca** vem do texto da pergunta quando existe identidade autenticada. O propagandista pode escrever o código de um setor que não é dele, e o backend usa o da sessão. O setor do texto só serve enquanto não há SSO.

## Onde fica cada texto

Tudo está em `perfil_medico.py`. Esta tabela responde a pergunta mais comum, que é "quero mudar aquela frase, onde eu mexo".

| O que aparece na tela | Função que escreve | Chip |
|---|---|---|
| A frase de abertura, acima do card | `bloco_decisao()` | mensagem, sempre visível |
| O card do médico: nome, posição, pontos, selo e resumo | `montar_payload()` | sempre visível |
| O card de participação da Aché | `bloco_ache()` | sempre visível |
| Categorias que o médico mais prescreve, com percentual e produtos | `bloco_prescricao()` | O que mais prescreve? |
| Produto a levar, justificativa da categoria e modo de agir | `bloco_acao()` | O que levar na visita? |
| Ciclos no painel, última visita, amplitude e última prescrição na categoria | `bloco_relacao()` | Como está a relação? |
| Os motivos que sustentam a saída do painel | `bloco_justificativa()` | Por que tirar do painel? |
| A leitura da base em caso de saída | `bloco_leitura()` | dentro da justificativa |

Os nomes dos chips ficam nas constantes `CHIP_VISITA`, `CHIP_PRESCREVE`, `CHIP_RELACAO`, `CHIP_POR_QUE_TIRAR` e `CHIP_MANTER`. Mudar o texto de um chip é mudar a constante, e nada mais.

### Quais chips aparecem em cada recomendação

| Recomendação | Chips oferecidos |
|---|---|
| Inclusão e permanência | O que levar na visita?, O que mais prescreve?, e Como está a relação? só na permanência |
| Saída | Por que tirar do painel?, O que mais prescreve?, Quero manter e visitar |

A ordem é intencional. Na saída, o que sustenta a decisão vem primeiro, e a orientação de visita só aparece se o propagandista disser que quer manter o médico. A intenção ali é que ele pare de visitar, então a resposta não abre com conselho de visita.

O chip só entra se tiver conteúdo. Médico sem produto recomendado não recebe o chip de visita, recebe um aviso no lugar.

## As regras que não se quebram

Cada uma nasceu de um defeito real, e cada uma tem teste. Se você quebrar alguma, a suíte acusa.

**1. Nenhum texto flexiona gênero.** Nada de "ele", "ela", "o médico", "a médica". Use o nome ou sujeito oculto. A tabela não informa sexo, e a fonte alternativa cobre 39,6% dos médicos e traz o mesmo UFCRM como masculino e feminino ao mesmo tempo.

**2. Nenhum valor cru de coluna aparece na tela.** `ADICIONAR`, `MATCH_DIRETO`, `REC_E_TOP1` e afins são vocabulário interno. A tradução fica em `_STATUS` e nas funções de texto.

**3. Percentual usa vírgula.** `20,8%`, nunca `20.8%`. É o `_pct()`.

**4. Toda afirmação sobre a Aché diz o período.** "neste período", "neste ano" ou "no histórico", conforme a janela lida. Sem essa marca, 1.032.248 linhas afirmavam que o médico não prescreve Aché quando ele prescreveu no ano ou no histórico.

**5. Em saída, nunca elogiar.** As quatro leituras de faixa de participação são escritas para animar, de "há bastante espaço" até "a Aché já é forte aqui". Elogiar um médico que a resposta manda tirar derruba a própria recomendação.

**6. O texto nunca cita o número do corte do painel.** Diga "limite do seu painel ideal". Só 12 dos 2.153 setores têm painel de exatamente 400 médicos, e os reais vão de 251 a 596.

**7. Volume de prescrição não vira texto.** `RX_QTY` é estimativa projetada de base amostral, nunca contagem de receitas, e o comentário da tabela diz isso. Contagem de categorias e de produtos distintos pode ser usada.

**8. A resposta é uma função pura.** Mesmo dado, mesma saída, sempre. Nada de sorteio, de hora do dia ou de chamada externa dentro das funções de texto.

**9. Cada chip viaja com a resposta pronta.** O toque não dispara consulta nem modelo. Um payload completo de médico tem cerca de 2,4 kB, então isso cabe sem esforço. E garante que o chip nunca contradiga o card acima dele.

**10. Toda frase diz de quem ou do que está falando, e se liga à anterior.** Nenhuma frase começa por verbo com sujeito subentendido de outra frase. A versão antiga dizia "Está entre as três categorias de maior volume" sem dizer o que estava, e a resposta virava uma lista de afirmações soltas. O sujeito da frase da categoria é a própria categoria, o da frase de estado é o produto, e as duas se ligam por "Dentro dessa categoria". A regra vale para qualquer frase nova.

**11. A categoria vira singular quando descreve um produto.** As 109 categorias da tabela são substantivos no plural, como "Medicamentos para tratar pressão alta". Um produto é "um anti-hipertensivo", nunca "anti-hipertensivos". Quem faz a flexão é `_singular()`, e quem monta o trecho pronto é `_um_da_categoria()`. Quando o texto não abre com substantivo no plural seguido de "para", a flexão pegaria a expressão inteira, então a função desiste e a frase nomeia a categoria: 93 linhas em 2.548.243.

## Como a janela de tempo funciona

A tabela guarda o retrato do médico em três janelas, e a resposta escolhe uma só.

| Janela | Cobertura dos médicos |
|---|---:|
| Último período | 93,2% |
| Ano vigente | 98,9% |
| Histórico completo | 99,4% |

A escolha é feita no `SQL_PERFIL`: se há categoria no ciclo, usa o ciclo; senão tenta o ano; senão usa o histórico. Ler só o ciclo deixaria 160.773 médicos sem retrato nenhum.

**A regra de ouro é usar a mesma janela para tudo dentro da mesma resposta.** Foi a mistura de janelas que produziu os dois piores defeitos já encontrados aqui: uma lista de categorias com "100% do volume" no primeiro item seguido de outros dois, e um card dizendo que o médico não prescreveu Aché no período enquanto o texto da visita dizia que ele já prescrevia o produto Aché recomendado.

Se você acrescentar uma coluna nova que exista por janela, siga o mesmo `CASE` das demais.

## Os três estados da relação com o produto

Esta é a parte que mais muda a conversa da visita, e ela sai de duas colunas.

| Estado | Como é detectado | O que a resposta orienta |
|---|---|---|
| Manutenção | prescreve o produto na janela lida | confirmar o que funciona e abrir espaço para outro da linha |
| Reativação | já prescreveu alguma vez, mas não na janela | entender o que mudou antes de propor de novo |
| Introdução | nunca prescreveu | visita de primeira apresentação |

Os textos ficam no dicionário `_CONVERSA`. Para mudar a orientação de um estado, mude a frase ali, e só ali. Cada frase tem `{produto}` no lugar do nome, e o sujeito é sempre o produto, nunca o médico: a tabela não traz o gênero, e o estado do produto vem de uma leitura sem período, diferente da janela que sustenta a frase da categoria. Se as duas frases dividissem o mesmo sujeito, a segunda pareceria falar do mesmo período da primeira.

### A ordem das frases no chip de visita

`bloco_acao()` monta até cinco frases, sempre nesta ordem:

1. O que levar, com a categoria no singular e a linha. Vem de `_um_da_categoria()`.
2. Onde essa categoria está no que o médico prescreve, com o período. Vem de `_JUSTIFICATIVA` e `_classe()`.
3. Como está a relação com aquele produto, ligada à frase anterior por "Dentro dessa categoria". Vem de `_CONVERSA`.
4. Os outros produtos da mesma linha, abertos por "Ainda na sua linha". Vem de `_outros_produtos()`.
5. O produto Aché de outra linha, quando existir e for mesmo outro. Vem de `_outra_linha()`.

Na frase 4, o produto que repete a categoria do recomendado sai marcado com "também", porque sem isso a lista parecia abrir uma alternativa nova quando estava repetindo a categoria da linha de cima. Acontece em 478.039 das 2.437.460 linhas com segundo produto.

Distribuição medida em 10/08/2026, sobre 2.548.243 pares de médico e produto recomendado: 1.860.339 nunca prescreveram, 164.970 prescrevem na janela e 522.934 prescreveram e pararam. Antes de a coluna de período existir, a resposta afirmava manutenção para os dois últimos grupos juntos, ou seja, errava em 76% das vezes em que dizia isso.

## Os quatro motivos de saída do painel

| Critério | Linhas | Frase de abertura |
|---|---:|---|
| Caiu no ranking | 106.730 | passou do limite do painel ideal |
| Dentro do limite, sem visita há N meses | 15.876 | diz o número de meses |
| Caiu no ranking **e** sem visita | 4.110 | diz os dois motivos |
| Dentro do limite, sem nenhuma visita registrada | 978 | não inventa meses |

O quarto critério da lista existe no dado e ficou meses sendo lido como se fosse o primeiro, o que apagava o segundo motivo. A ordem do `CASE` em `SQL_PERFIL` importa: o caso combinado precisa ser testado antes dos isolados.

**Os dois primeiros são opostos e a resposta erra se tratá-los igual.** Quem sai por ranking está sempre além do limite. Quem sai por falta de visita está dentro dele, às vezes na primeira posição do setor. Chamar de fraco quem é o primeiro do setor é falso, e o propagandista percebe.

## Passo a passo: mudar uma frase

1. Ache a função na tabela de **Onde fica cada texto**.
2. Mude a frase.
3. Rode `pytest test_perfil_medico.py -q`. Se algum teste quebrar, leia o nome dele: ele diz qual decisão a frase antiga sustentava.
4. Se a decisão mudou de verdade, ajuste o teste junto e explique no comentário por quê.
5. Gere a prévia e olhe na tela antes de dar o assunto por encerrado.

## Passo a passo: acrescentar uma orientação nova

Exemplo: você quer dizer algo quando o médico prescreve muitas categorias diferentes.

1. Confira se a coluna existe na tabela e qual a cobertura dela. A seção **O que a tabela ainda oferece** lista o que está disponível e sem uso.
2. Acrescente a coluna no `SQL_PERFIL`. Se ela existir por janela, siga o mesmo `CASE` das outras.
3. Escreva a frase na função do bloco onde ela deve aparecer.
4. **Faça a linha sumir quando o dado faltar.** Nenhuma frase pode aparecer vazia ou com `None`.
5. Escreva o teste, com um caso que tem o dado e um que não tem.
6. Gere a prévia e confira.

## Passo a passo: criar um chip novo

1. Crie a constante `CHIP_ALGUMA_COISA` junto das outras.
2. Escreva a função `bloco_alguma_coisa(d)` que devolve o texto, e `""` quando não se aplica.
3. Em `montar_payload()`, acrescente o chip na lista quando o bloco tiver conteúdo, e a resposta no dicionário `respostas`.
4. O payload só manda resposta de chip que aparece. Isso é garantido por teste, não mexa nessa parte sem motivo.

## Onde a tela entra nisso

A tela é `frontend/src/pages/Chat.tsx`, e ela **não escreve frase de conteúdo
nenhuma**. Ela recebe o payload e desenha, na ordem em que o backend mandou.
Se um texto está errado na tela, o lugar de corrigir é aqui no backend, nunca
lá.

O que a tela decide, e só isso:

| Decisão | Onde |
|---|---|
| Como cada tipo de card é desenhado | `CardMedico`, e o bloco de `insight` e `info-banner` |
| Como a lista com `- ` vira lista de verdade | o componente `Texto` |
| O que acontece ao tocar num chip | `tocarNoChip` |
| Onde a conversa mora no portal | a aba Home, em `App.tsx` |

O toque num chip **não dispara requisição**: a resposta já veio no mesmo
payload. A única exceção é a lista de desambiguação, onde o toque monta uma
pergunta nova, porque a resposta daquele médico ainda não foi buscada.

O contrato tipado fica em `frontend/src/lib/api.ts`. Coluna nova que apareça na
resposta precisa entrar lá também, senão o TypeScript não a enxerga.

## Como ver o resultado antes de subir

A pasta `preview/` gera um HTML de arquivo único que desenha a conversa com dado real, na moldura de um celular e com as cores do portal.

```bash
cd preview
python gerar_preview.py
```

O arquivo `resposta-ao-propagandista.html` abre no navegador, tem seletor de setor, os chips funcionando e um botão que mostra a linha da tabela e o payload por trás da conversa.

**A pasta inteira está fora do versionamento**, porque o HTML gerado traz nome e CRM de médico real. Ela é descartável de propósito: serve para conferir texto na tela, não é a tela do portal e não usa o design system do Figma Design.

Vale o hábito: quase todos os defeitos corrigidos neste módulo apareceram olhando a prévia, não lendo o código.

## Como rodar os testes

```bash
pip install -r requirements.txt
pytest test_perfil_medico.py -q     # 50 testes, sem credencial e sem rede
pytest -q                           # a pasta inteira
```

Os casos de referência no topo do arquivo de teste são cópias fiéis do que a consulta devolveu em datas registradas. Eles travam comportamento, não medem integração.

**Um cuidado.** Como são cópias congeladas, eles não percebem quando a tabela muda. Depois de qualquer reconstrução da `tb_perfil_medico_setor`, gere a prévia e compare, ou os testes vão continuar verdes enquanto a resposta real mudou.

## O que a tabela ainda oferece e não é usado

Colunas disponíveis em `acheinfo_dev.renovai.tb_perfil_medico_setor` que hoje não entram em texto nenhum. Elas são o primeiro lugar a olhar quando alguém pedir uma informação nova.

`CICLO_REFERENCIA`, `FLAG_NO_PAINEL`, `CICLO_RX_TOTAL`, `CICLO_RX_ACHE`, `YTD_RX_TOTAL`, `YTD_RX_ACHE`, `GERAL_RX_TOTAL`, `GERAL_RX_ACHE`, `YTD_QTD_CATEGORIAS`, `GERAL_QTD_CATEGORIAS`, `GERAL_QTD_PRODUTOS`, `CATEGORIA_ESTA_NO_TOP3`, `PRODUTO_RECOMENDADO_ACHE_CATEGORIA`, `PERIODO_PRESCRICAO_USADO`, `DT_GERACAO`.

Lembre da regra 7 antes de usar as de volume.

## O que não fazer

- Não escreva a resposta final com modelo de linguagem. A medição está no começo deste arquivo.
- Não misture janelas dentro da mesma resposta.
- Não cite o número do corte do painel.
- Não escolha um médico em silêncio quando a busca devolver mais de um. Dentro do mesmo setor, 856 CRMs sem UF e 2.394 nomes apontam para mais de uma pessoa.
- Não leia o setor do corpo da requisição quando houver identidade autenticada.
- Não versione a pasta `preview/`.
- Não conclua que está pronto sem ter olhado a prévia.

## Onde as decisões ficam registradas

O histórico de cada decisão de texto está no diário do projeto, em `brain/daily/`, e o desenho da tabela está em `brain/projeto-ped-2.0/02-analises-tecnicas/perfil-medico-por-setor-2026-08-08.md`. Os comentários dentro de `perfil_medico.py` carregam o número que sustenta cada regra, e devem ser mantidos assim: comentário sem número envelhece e ninguém sabe se ainda vale.
