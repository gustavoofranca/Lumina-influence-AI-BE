# Robustez da camada de integração — YouTube, Gemini e mídia

Executado em 28 de agosto de 2026, depois de fechada a bateria do B12. O alvo
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
| Suíte inteira | 230 testes, 86% | **304 testes, 91%** |

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
