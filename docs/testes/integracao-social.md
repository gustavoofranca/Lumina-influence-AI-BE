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
| Comentários ingeridos | **não atingido, por escopo** | ver "O que ficou de fora", abaixo |

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

**Comentários.** O canal tem um comentário e a ingestão trouxe zero. A causa foi
`403 insufficient authentication scopes`: `commentThreads.list` exige o escopo
`youtube.force-ssl`, e o app pede apenas `youtube.readonly`. O `force-ssl` é
escopo de leitura **e escrita** — permite editar e apagar vídeos, avaliações,
comentários e legendas do canal. Pedir permissão de escrita num sistema que só
audita é decisão de produto, não de implementação, e está em aberto.

A falha era invisível: a exceção era registrada em `debug` e engolida como
best-effort, então um criador conectado ficava sem base de comentário — que é o
que alimenta o sentimento da análise — sem nada denunciar a causa. Passou a
`logger.warning` nomeando conta, post e motivo, com teste fixando o
comportamento.

**Instagram e TikTok.** Continuam em `platform_not_configured`: exigem callback
em HTTPS público, o que a demonstração local não oferece.

## Como reproduzir

Pré-requisitos no projeto do Google Cloud, hoje chamado **Google Auth Platform**:
YouTube Data API v3 e YouTube Analytics API ativadas na Biblioteca; escopos
`youtube.readonly` e `yt-analytics.readonly` em **Data Access**; a conta que vai
consentir cadastrada em **Audience → Test users** enquanto o app estiver em
*Testing*; e a URI exata
`http://localhost:5000/api/v1/integrations/youtube/callback` registrada em
**Clients**.

No `.env`, deixar `YOUTUBE_CLIENT_ID` e `YOUTUBE_CLIENT_SECRET` **vazios** para
reaproveitar o par `GOOGLE_*` do login — dois pares para o mesmo client foi a
origem do terceiro erro. Mudança em `.env` exige recriar o container
(`docker compose up -d --force-recreate backend`), porque `docker restart`
reaproveita o `env_file` lido na criação.
