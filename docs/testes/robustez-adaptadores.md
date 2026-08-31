# Robustez das bordas — integrações, login e filtros de listagem

Executado em 31 de agosto de 2026, depois de fechada a bateria do B12. O alvo
não foi o percentual de cobertura, e sim **onde o sistema fala com o mundo
externo**: os três módulos que traduzem resposta de API de terceiro em tipo
interno eram os de menor rede de proteção da suíte.

## Por que justamente esses três

Todo teste existente substituía a camada de transporte por dublê. As
integrações eram exercitadas por um `FakeAdapter` em `test_integrations.py` e o
Gemini por um cliente falso em `test_analysis.py`. O efeito colateral é que o
código realmente executado em produção — o mapeamento de payload, a tradução de
erro do SDK e a guarda de tamanho do download — nunca era executado por teste
nenhum.

| Módulo | Cobertura antes | Linhas sem teste | Risco que corria |
|---|---|---|---|
| `src/integrations/gemini.py` | 33% | 64 | tradução de erro do SDK: 429 de cota confundido com falha genérica |
| `src/integrations/youtube.py` | 38% | 50 | único adaptador em uso real; é onde vive o mapeamento do alcance |
| `src/integrations/media.py` | 39% | 36 | guarda de 50 MB e limpeza do arquivo temporário |

## Método

Suíte em `tests/test_adaptadores.py`, com dublês que devolvem exatamente
os payloads que as APIs reais devolvem — nenhum teste toca a rede nem consome
cota do Gemini. Para os erros do Gemini são usadas as **classes de exceção reais
do SDK** (`google.genai.errors.ClientError` e `ServerError`), não imitações:
o que se quer verificar é justamente se o `except` do produto casa com o tipo
que o SDK levanta de fato.

Três contratos foram escolhidos por consequência, não por linha descoberta:

1. **O que a ausência de dado produz.** Vídeo com contagem de curtida desativada
   não traz `likeCount`; data de publicação ilegível não pode derrubar a coleta
   inteira; canal sem item não pode virar seguidor zero inventado. É o mesmo
   padrão que a ADR-003 fixou no serviço de métricas, aplicado à borda.
2. **O que o erro externo produz.** Um 403 na busca de vídeos não pode virar
   lista vazia — falha de rede lida como "canal sem post" é ausência
   apresentada como zero, com a agravante de parecer normal na tela.
3. **O que sobra depois da falha.** O arquivo enviado à Files API do Gemini é
   removido mesmo quando a geração falha; o temporário do download é apagado
   quando o vídeo estoura o limite de 50 MB.

## Resultado

| Módulo | Antes | Depois |
|---|---|---|
| `gemini.py` | 33% | **100%** |
| `youtube.py` | 38% | **100%** |
| `media.py` | 39% | **100%** |
| `google_oauth.py` | 60% | **96%** |
| `microsoft_oauth.py` | 44% | **91%** |
| `campaign_service.py` | 75% | **100%** |
| `influencer_service.py` | 83% | **100%** |
| Suíte inteira | 230 testes, 86% | **317 testes, 92%** |

(as rodadas 4 e 5, abaixo, levaram a suíte a 362 testes e 94%)

Nos três primeiros módulos, nenhum defeito novo apareceu: eles se comportaram
como o código prometia em todos os 56 cenários. O ganho é de regressão — o
mapeamento de alcance, em particular, agora tem um teste que falha em voz alta
se alguém transformar `reach_paid = 0` em estimativa sem passar pela ADR-005.

## Segunda rodada: os clientes OAuth do login

Mesma lógica, aplicada ao caminho mais crítico do produto. `test_auth.py` cobre
o nível de rota substituindo `exchange_code` e `fetch_user_info` por dublê, de
modo que o transporte dos dois clientes nunca era exercitado.

**Aqui apareceu um defeito real.** `GoogleOAuthClient.fetch_user_info` lia
`data["sub"]` e `data["email"]` direto do payload. Um userinfo sem esses campos
é resposta possível — basta o usuário não conceder o escopo — e produzia
`KeyError`, ou seja, **500 sem explicação em vez do 502 tipado** que descreve o
que aconteceu. O cliente da Microsoft já tratava o caso equivalente (conta sem
`mail` nem `userPrincipalName`), o que deixa claro que era esquecimento e não
decisão. Corrigido validando os dois campos antes de montar a identidade, no
mesmo formato do erro que a Microsoft já usava.

É o mesmo padrão que atravessa o projeto, na versão de identidade: **ausência de
dado externo tratada como se o dado estivesse lá.**

## Terceira rodada: os filtros de listagem

Mesmo método — testar por consequência — aplicado à camada de consulta.
`campaign_service` e `influencer_service` tinham as funções de filtro sem teste
nenhum: `status`, intervalo de datas e busca por marca nas campanhas, e a faixa
de seguidores nos criadores. Filtro que não filtra (ou que filtra demais) é
invisível até alguém conferir a contagem na tela.

**Segundo defeito real do dia.** A faixa de seguidores somava as contas do
criador numa subquery e fazia `JOIN` com ela. Sendo `INNER JOIN`, **criador sem
nenhuma conta social desaparecia da listagem filtrada** — e zero seguidor
pertence à faixa "menos de 100k". Some da tela justamente quem acabou de ser
cadastrado e ainda precisa ser conectado. Corrigido para `LEFT JOIN` com
`coalesce(total, 0)`.

É a terceira aparição do mesmo padrão em um dia: **ausência tratada como
exclusão**, depois de ausência tratada como zero e de ausência de resposta
tratada como ausência de dado.

Junto foram travados por teste: a soma entre plataformas (quem tem 60k no
Instagram e 60k no TikTok pertence à faixa dos 100k), a validação do período no
`PATCH` de campanha — que precisa olhar o período **resultante do merge**, não
só o campo enviado —, e o id malformado na listagem de contas sociais, que
filtra para conjunto vazio em vez de estourar 500.

`campaign_service` e `influencer_service` ficaram em **100%**; a suíte, em
**317 testes e 92%**.

## Quarta rodada: o adaptador do Instagram

Mesmo método, agora sobre o único adaptador que nunca foi exercido contra a rede
real — e o de pior cobertura que restava: **0%**. O gatilho foi a preparação da
submissão ao App Review da Meta, que obrigou a ler o código linha a linha contra
a documentação vigente da Graph API.

**Três defeitos reais, e nenhum deles apareceria em ambiente local**, porque os
três só se manifestam quando existe um token de verdade:

| Defeito | O que aconteceria em produção |
|---|---|
| Pedia a métrica `impressions`, removida da API em 21/04/2025 | erro — não zero — para toda mídia posterior a 02/07/2024, derrubando a coleta inteira junto com alcance, curtidas e salvamentos |
| Falava com `/me` para perfil e mídia | `/me` num token de usuário do Facebook é a pessoa, não o perfil do Instagram: `followers_count` e `media` não existem nesse nó |
| Faltava o escopo `pages_read_engagement` | a listagem de Páginas funciona e a leitura da Página escolhida devolve 403 |

O terceiro é o mais traiçoeiro: só apareceria **depois** do App Review aprovado,
quando corrigir custa outra fila de revisão.

Junto vieram dois acertos de modelagem. Conta pessoal do Instagram — que
autoriza e não devolve nada — virava lista vazia, que o resto do sistema leria
como "o criador não publicou"; agora levanta `AccountNotLinkedError` (422). E
`media_type` chama Reel e vídeo de feed igualmente de `VIDEO`: quem separa é
`media_product_type`, e o benchmarking compara por tipo de post.

O raciocínio completo — por que a v25.0, por que a configuração com Facebook
Login, por que `views` — está na
[ADR-007](../adr/0007-instagram-com-facebook-login-e-views.md).

| Módulo | Antes | Depois |
|---|---|---|
| `instagram.py` | 0% | **100%** (25 testes) |
| Suíte inteira | 317 testes, 92% | **342 testes, 93%** |

Três testes existem só para impedir a volta de cada defeito: que `impressions`
não aparece entre os campos pedidos, que `/me` não é consultado, e que os quatro
escopos estão na URL de autorização. É a mesma lógica do teste que trava
`reach_paid = 0` — o que se protege não é a linha, é a decisão.

**O que esta rodada não prova:** nenhuma chamada foi feita contra a rede real,
porque não há App Review aprovado. O que existe é conformidade com a
documentação vigente. A validação de verdade é o primeiro sync com o app em
modo Live, e o plano dela está em [`../meta-app-review.md`](../meta-app-review.md).

## Três pontos que o teste fixou como contrato

**O timeout do Gemini vai em milissegundos.** `GenerateContentConfig` recebe
`http_options.timeout` na casa dos milissegundos; mandar os 90 segundos da
configuração sem multiplicar daria 90 ms e mataria toda análise real, que leva
de 25 s (banco local) a 50 s (Supabase). O teste compara com o valor
configurado, não com um literal.

**Todo alcance do YouTube é declarado orgânico.** A Data API v3 não separa
origem paga sem cruzar com o Google Ads, atrás de conta comercial. As colunas
são `NOT NULL`, então a divisão fica orgânico = total e pago = 0, com o limite
declarado ao apresentar o dado — ADR-005. Há teste dedicado a isso porque é o
ponto do escopo em que a tentação de estimar é maior.

**O login exige os escopos que ele usa.** A URL de autorização do Google pede
`access_type=offline` — sem ele o Google devolve só o access token e a
sincronização agendada morre em uma hora — e a da Microsoft pede `User.Read`,
sem o qual o Graph `/me` responde 403 e o login termina sem identidade. Os dois
são invisíveis até falharem em produção.

## Como reproduzir

    docker run --rm --entrypoint python -v $PWD:/app -w /app -e PYTHONPATH=/app \
      lumina-backend -m pytest -q --cov=src --cov-report=term tests/test_adaptadores.py

Medir com `--cov=src/integrations/gemini.py` devolve `module-not-imported` e
zera o número: o alvo precisa ser `--cov=src`, filtrando a saída.

## Quinta rodada: o adaptador do TikTok

Último módulo de integração sem cobertura própria — estava em 41%. Mesmo
método, e de novo **três defeitos reais**, todos invisíveis sem token de
verdade:

**O erro que chega dentro de um 200.** O TikTok responde `200` mesmo quando
falha: o corpo **sempre** traz um objeto `error`, e `code == "ok"` é o único
valor que significa sucesso. O adaptador conferia apenas o status HTTP. Na
prática, token revogado, cota estourada ou escopo faltando devolviam
`data: {}` — que virava lista vazia, e a tela dizia **"criador sem post"**.

É a mesma família de novo, na variante mais traiçoeira: não é ausência lida
como zero, é **falha lida como ausência**, com a agravante de o HTTP dizer que
deu tudo certo. A leitura do corpo passou a mapear os códigos conhecidos para
os erros tipados que o resto do sistema já trata — inclusive `TokenRevokedError`,
que é o que dispara a limpeza do token e o pedido de reconexão.

**O handle que não era o handle.** `handle` recebia `display_name`, o nome livre
que o criador troca quando quer; o `@` do perfil é `username`, que a Display API
também devolve. Como o handle compõe a chave única
`(influencer_id, platform, handle)`, **uma troca de nome de exibição nasceria
como conta duplicada**, com o histórico partido em duas.

**A página entregue como arquivo de vídeo.** `video_url` recebia `share_url`,
que é a página do TikTok — HTML, não vídeo. O `HttpVideoFetcher` baixaria a
página, gravaria com sufixo `.mp4` e a entregaria ao analisador multimodal. A
Display API **não expõe arquivo baixável**; o campo passou a ficar nulo, e a
análise de vídeo recusa explicitamente em vez de analisar uma página.

Esse terceiro motivou uma guarda no próprio downloader: content-type de texto,
JSON ou XML deixa de ser aceito. A lista é **de exclusão, não de permissão** —
CDN de vídeo costuma servir `application/octet-stream`, e uma lista de
permitidos recusaria download legítimo.

| Módulo | Antes | Depois |
|---|---|---|
| `tiktok.py` | 41% | **100%** |
| `media.py` | 100% | **100%** (2 cenários novos) |
| Suíte inteira | 342 testes, 93% | **362 testes, 94%** |

Com isso, **os cinco adaptadores de integração estão em 100%**. O saldo das duas
últimas rodadas é de **seis defeitos reais** em código que teste de rota
atravessava sem tocar — e nenhum deles apareceria em ambiente local, porque
todos dependem de uma resposta que só a plataforma real produz.
