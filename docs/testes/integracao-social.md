# B8 — Validação da integração com plataforma social contra conta real

- **Data:** 27 de agosto de 2026
- **Plataforma validada:** YouTube (Data API v3 + YouTube Analytics API)
- **Critério da etapa:** conta real vinculada; sync traz posts com orgânico/pago
  separados

## Resultado

| O que o critério pede | Situação | Evidência |
|---|---|---|
| Conta real vinculada por OAuth | **atingido** | canal `UCsveg8W6R9a_daw_FZgEzzQ` vinculado à criadora Ana Paula Souza em 27/08 às 13:54 UTC, com *refresh token* guardado cifrado |
| Sync traz posts da plataforma | **atingido** | `sync_influencer` em `mode: real`, 10 posts criados, período de 16/07/2021 a 11/11/2022 |
| Métricas vindas da API | **atingido** | 130 exibições, 1 curtida e 1 comentário somados — conferem com o canal |
| Orgânico e pago separados | **não atingido, por limite de acesso** | ver [ADR-005](../adr/0005-alcance-organico-e-pago-vem-do-seed.md) |
| Comentários ingeridos | **atingido** | exigiu ampliar o escopo para `youtube.force-ssl` e reconectar a conta; o comentário real do canal foi gravado. Ver [ADR-006](../adr/0006-escopo-de-escrita-para-ler-comentario.md) |

O que a coleta real trouxe por post: identificador na plataforma, título,
data de publicação, URL do vídeo, miniatura, exibições, curtidas e contagem de
comentários. É o que alimenta a análise de IA, que é o objeto do trabalho.

## Método

O teste foi feito ponta a ponta pela interface, não por chamada direta à API:
clique em **Conectar YouTube** na aba Visão Geral do criador, consentimento na
conta Google, retorno ao app, e então `sync_influencer` executado contra o banco
gerenciado. Um post do canal tem alcance zero e outro tem uma única curtida —
os dois casos que costumam expor divisão por zero. Nenhum endpoint falhou:
`GET /influencers/:id`, `/posts`, `/analysis`, `/posts/:id` e
`/dashboard/overview` responderam 200, com `bot_probability` e `sentiment_score`
em `null` para os posts ainda não analisados, como manda a
[ADR-003](../adr/0003-ausencia-de-dado-nunca-vira-zero.md).

## Os quatro erros do caminho, e o que cada um significava

A sequência tem valor de documentação: cada erro veio de uma camada diferente, e
o quarto é uma proteção funcionando.

| Erro | Camada | Causa |
|---|---|---|
| redirecionamento para `/signin/oauth/error` | projeto no Google Cloud | YouTube Data API v3 e YouTube Analytics API não estavam ativadas |
| `403 access_denied` | tela de consentimento | app em modo *Testing* e a conta que ia consentir fora da lista de testadores |
| `invalid_client: The provided client secret is invalid` | credencial do app | `.env` com `YOUTUBE_CLIENT_ID` igual ao do login mas `YOUTUBE_CLIENT_SECRET` diferente; o adaptador prefere o par `YOUTUBE_*` |
| `oauth_state_replayed` | proteção do próprio sistema | recarga da página de callback; o `state` é de uso único, e reusá-lo é exatamente o ataque que a proteção existe para barrar |

O terceiro produziu um **achado de código**: o back-end classificava
`invalid_client` como `platform_token_revoked`, e `sync_influencer` apaga os
tokens da conta ao ver esse erro. Um `.env` com secret errado destruiria a
conexão válida do criador — erro de configuração tratado como revogação do
usuário. Corrigido: o corpo da resposta OAuth passa a ser lido, `invalid_client`
e `unauthorized_client` viram `platform_not_configured` (503) e `invalid_grant`
continua sendo revogação. Quatro testes fixam a distinção, incluindo um que
verifica que o token guardado sobrevive a um erro de credencial.

## O que ficou de fora, e por quê

**Divisão entre alcance orgânico e pago.** A Data API v3 devolve `viewCount`,
que é o total de exibições. A origem paga só existe cruzando com a conta de
anúncios. Decisão registrada na [ADR-005](../adr/0005-alcance-organico-e-pago-vem-do-seed.md):
a divisão exibida pelo sistema é dado de seed, nas três plataformas, e isso
precisa ser declarado ao apresentar a métrica.

**Instagram e TikTok.** Continuam em `platform_not_configured`: exigem callback
em HTTPS público, o que a demonstração local não oferece.

## Comentários: dois defeitos em série

O canal tem um comentário e a primeira ingestão trouxe zero. Foram duas causas
sobrepostas, e a segunda só apareceu depois de resolver a primeira.

As duas passaram despercebidas pelo mesmo motivo: a exceção era registrada em
`debug` e engolida como best-effort, então um criador conectado ficava sem base
de comentário sem nada denunciar a causa. O aviso virou `logger.warning`
nomeando conta, post e motivo — e foi ele que expôs a segunda causa.

**Escopo.** `commentThreads.list` respondeu `403 insufficient authentication
scopes`. O recurso exige `youtube.force-ssl`, e o app pedia apenas
`youtube.readonly`. O `force-ssl` concede leitura **e escrita** — editar e
apagar vídeos, avaliações, comentários e legendas. A permissão foi aceita com a
justificativa registrada na
[ADR-006](../adr/0006-escopo-de-escrita-para-ler-comentario.md): o sistema não
exerce escrita alguma, e a lista de escopos ficou travada por teste, incluindo a
ausência de `youtube.upload`.

**Ingestão só na criação.** Com o escopo novo e a conta reconectada, o sync
seguiu trazendo zero comentários: `_ingest_comments` era chamado apenas no ramo
que cria o post. Um post já coletado ficava com a amostra congelada no primeiro
sync — e como o sentimento da análise vem dos comentários, a leitura
envelheceria sem que nada mudasse na tela. A coleta passou a rodar também nos
posts atualizados, pulando o que já está gravado pelo `platform_comment_id`.
Depois disso, o comentário real do canal foi gravado.

**O que o aviso novo revelou no caminho:** um dos dez vídeos devolve 403 porque
o criador **desativou comentários** nele. É estado normal, não falha — sai como
`info`, enquanto escopo faltando e token revogado seguem em `warning`, para que
o log não grite por escolha do criador.


## O ciclo completo, com dado real de ponta a ponta

Com a conta conectada, o sistema foi levado até o fim do seu propósito: análise
de IA sobre um post verdadeiro do canal, com o comentário verdadeiro que a
plataforma devolveu.

| Medida | Valor |
|---|---|
| Tempo da análise (`POST /posts/:id/analyze`, contra o banco gerenciado) | **30,7 s** — dentro do requisito de p95 ≤ 60 s |
| Modelo | `gemini-3.6-flash` |
| Coerência com a marca | **0** |
| Probabilidade de bot | 65% |
| Sentimento | neutro (100% neutro na distribuição) |

O resultado é a melhor evidência de que a análise reage ao conteúdo, e não a um
mock: a criadora está cadastrada no nicho **Beauty & Skincare**, e o canal
conectado publica gameplay. O modelo devolveu coerência de marca **zero** e duas
recomendações de alta prioridade — "realinhar perfil e nicho do influenciador",
justificada com "o conteúdo postado e os comentários tratam de games […],
totalmente irrelevantes para o nicho de Beauty & Skincare", e moderação de
comentários. As `key_phrases` extraídas vieram do título do vídeo e do
comentário real, não do seed.

Vale notar a distinção da [ADR-003](../adr/0003-ausencia-de-dado-nunca-vira-zero.md)
funcionando na direção oposta: aqui o zero de coerência é **medido**, e por isso
é exibido como zero. O que a ADR proíbe é o zero que substitui a ausência.

## Como reproduzir

Pré-requisitos no projeto do Google Cloud, hoje chamado **Google Auth Platform**:
YouTube Data API v3 e YouTube Analytics API ativadas na Biblioteca; escopos
`youtube.readonly`, `yt-analytics.readonly` e `youtube.force-ssl` em
**Data Access** — ampliar o escopo não altera token já emitido, então a conta
precisa ser reconectada; a conta que vai
consentir cadastrada em **Audience → Test users** enquanto o app estiver em
*Testing*; e a URI exata
`http://localhost:5000/api/v1/integrations/youtube/callback` registrada em
**Clients**.

No `.env`, deixar `YOUTUBE_CLIENT_ID` e `YOUTUBE_CLIENT_SECRET` **vazios** para
reaproveitar o par `GOOGLE_*` do login — dois pares para o mesmo client foi a
origem do terceiro erro. Mudança em `.env` exige recriar o container
(`docker compose up -d --force-recreate backend`), porque `docker restart`
reaproveita o `env_file` lido na criação.
