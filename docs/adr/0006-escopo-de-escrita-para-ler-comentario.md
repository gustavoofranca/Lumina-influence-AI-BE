# ADR-006 — Aceitar `youtube.force-ssl` para ler comentários

- **Status:** aceito
- **Data:** 2026-08-27
- **Relacionada:** [ADR-005](0005-alcance-organico-e-pago-vem-do-seed.md), que
  delimita o que a coleta real alcança nas plataformas.

## Contexto

A análise de sentimento é o núcleo do sistema: ela lê os comentários de um post
e produz índice de sentimento, coerência com a marca e probabilidade de bot. Com
uma conta real de YouTube conectada na B8, a ingestão de comentários trouxe zero
— o canal tem um comentário e nenhum foi gravado.

A causa é de autorização, não de código: `commentThreads.list` responde
`403 insufficient authentication scopes` para um token que carrega apenas
`youtube.readonly`. A documentação da YouTube Data API v3 exige
`https://www.googleapis.com/auth/youtube.force-ssl` para esse recurso.

O escopo é sensível pelo que **permite**, não pelo que o sistema faz com ele. A
descrição que o usuário lê na tela de consentimento é: *"See, edit, and
permanently delete your YouTube videos, ratings, comments and captions"*.

## Alternativas consideradas

**Manter apenas leitura e alimentar o sentimento com o seed.** É a alternativa
coerente com a ADR-005 — uma justificativa técnica única cobriria alcance pago,
Instagram, TikTok e comentários. Rejeitada porque deixa a demonstração sem o
caminho completo: um criador com conta real conectada teria post real e análise
sobre comentário fictício, e é justamente a análise que o trabalho defende.

**Pedir `force-ssl` só no momento de coletar comentários**, com consentimento
incremental. O Google suporta, mas exige um segundo fluxo de autorização e uma
tela explicando por que a permissão aumentou. Custo de implementação e de
interface que a entrega de 11–17/09/2026 não comporta.

**Aceitar `force-ssl` no consentimento único, declarando o limite.** Escolhida.

## Decisão

O app passa a pedir três escopos: `youtube.readonly`, `yt-analytics.readonly` e
`youtube.force-ssl`. A lista fica travada pelo teste
`test_url_de_autorizacao_pede_o_escopo_que_le_comentario`, que também garante a
ausência de `youtube.upload` — para que a lista não cresça por descuido de quem
mexer no console depois.

O sistema **não exerce escrita alguma** com esse escopo: o `YouTubeAdapter` só
faz `GET` em `search`, `videos` e `commentThreads`. Nenhum caminho de código
publica, edita ou remove conteúdo do canal, e nenhum deve passar a fazer isso
sem revisar esta ADR.

## Consequências

- A tela de consentimento passa a anunciar permissão de edição e exclusão. Quem
  conecta um canal está concedendo mais do que o sistema usa, e isso precisa ser
  dito na apresentação — é um custo assumido, não um detalhe.
- Contas conectadas antes desta mudança **continuam sem o escopo**: o token foi
  emitido para a lista antiga. É preciso desconectar e reconectar a conta para
  que o consentimento inclua `force-ssl`.
- Publicar o app fora do modo *Testing* passaria a exigir verificação do Google
  para escopo sensível, com revisão de política de privacidade e demonstração de
  uso. Fora do escopo da entrega, que roda em `localhost` com testadores
  cadastrados.
- Se um dia a coleta de comentários deixar de ser necessária, o escopo deve sair
  junto: permissão que não se usa é superfície de risco sem contrapartida.
