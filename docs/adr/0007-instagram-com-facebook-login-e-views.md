# ADR-007 — Instagram pela configuração com Facebook Login, na v25.0, medindo `views`

- **Status:** aceito
- **Data:** 2026-08-31
- **Relacionada:** [ADR-005](0005-alcance-organico-e-pago-vem-do-seed.md), que
  delimita o que a coleta real alcança; [ADR-006](0006-escopo-de-escrita-para-ler-comentario.md),
  que trata do mesmo tipo de custo no YouTube.

## Contexto

O adaptador do Instagram foi escrito cedo, contra a v21.0 da Graph API, e nunca
foi exercido contra a rede real — diferente do YouTube, que a B8 conectou. Ao
preparar a submissão ao App Review da Meta, três problemas apareceram ao mesmo
tempo, e nenhum deles apareceria em teste local: os três só se manifestam quando
existe um token de verdade.

**1. `impressions` foi removida.** A métrica saiu na v22.0, em 21 de abril de
2025, e hoje devolve **erro** — não zero — para mídia criada a partir de 2 de
julho de 2024. O adaptador pedia `insights.metric(reach,impressions,saved,shares)`
numa chamada só: o erro derrubaria a coleta inteira, não apenas a métrica.

**2. O token não é do Instagram.** A configuração *Instagram API with Facebook
Login* é a única que expõe `instagram_manage_insights`; a variante com login
pelo próprio Instagram não tem insights, e sem insights não há auditoria de
alcance — que é o produto. Mas o token que sai desse login é de **usuário do
Facebook**. O adaptador chamava `/me?fields=followers_count` e `/me/media`, e
nenhum dos dois existe nesse nó: `/me` ali é a pessoa, não o perfil.

**3. Faltava um escopo.** `pages_show_list` lista as Páginas e traz o token de
cada uma; é `pages_read_engagement` que autoriza **ler** a Página encontrada.
Sem o segundo, o primeiro passo funciona e o segundo devolve 403 — uma falha que
só apareceria depois do App Review aprovado.

A cobertura do módulo era 0%: toda a suíte o substituía por dublê. Os três
defeitos estavam num código que nenhum teste tocava.

## Alternativas consideradas

**Manter `impressions` e tratar o erro.** Rejeitada: o dado deixaria de existir
de qualquer forma, e o produto ficaria exibindo ausência onde a plataforma já
oferece a substituta.

**Migrar para a variante com Instagram Login**, mais simples de autorizar.
Rejeitada porque não concede `instagram_manage_insights`. O caminho mais fácil
de aprovar é o que entrega menos.

**Subir para a v26.0**, a mais nova (jul/2026). Rejeitada: um mês de vida, e a
entrega não ganha nada com o que ela adiciona.

## Decisão

O adaptador passa a usar a **v25.0** (fev/2026, expira jul/2028): é a primeira
versão posterior à remoção de `impressions` cuja documentação já estabilizou, e
sobrevive com folga ao prazo do trabalho. A v21.0 expira em janeiro de 2027.

A coleta ganha um passo de **descoberta**: `GET /me/accounts` traz as Páginas
com `instagram_business_account` e o token de cada uma; o adaptador escolhe a
primeira Página com Instagram vinculado e usa **o ID daquele perfil e o token
daquela Página** em mídia, insights e comentários. A descoberta é resolvida uma
vez por instância — a mesma atende perfil, mídia e comentários de cada post, e
repeti-la gastaria uma chamada por post do limite da Graph.

As métricas pedidas passam a ser `reach,views,saved,shares`. `views` alimenta o
campo interno `impressions`, que é exatamente o que YouTube e TikTok já gravam
ali: os três passam a guardar a mesma grandeza sob o mesmo nome.

Os escopos passam a ser quatro: `instagram_basic`, `instagram_manage_insights`,
`pages_show_list` e `pages_read_engagement`.

Conta pessoal — que autoriza e não devolve nada — deixa de virar lista vazia e
passa a levantar `AccountNotLinkedError` (422). Página com Instagram mas sem
token na resposta é caso diferente, de escopo faltando, e levanta
`PlatformNotConfiguredError`: as duas situações pedem orientações opostas ao
usuário, e confundi-las mandaria alguém vincular uma conta que já está vinculada.

`media_product_type` passou a separar Reel de vídeo de feed. `media_type` chama
os dois de `VIDEO`, e o benchmarking compara por tipo de post.

## Consequências

- O módulo saiu de 0% para **100% de cobertura**, com 25 testes. Três deles
  travam exatamente os defeitos acima: que `impressions` não é pedida, que `/me`
  não é consultado, e que os quatro escopos estão na URL de autorização.
- A separação entre alcance orgânico e pago **continua indisponível**: ela
  depende da Marketing API, que é outro App Review, mais pesado. A ADR-005 segue
  valendo, e pedir aquelas permissões nesta submissão aumentaria o risco de
  rejeição sem entregar nada que o trabalho precise.
- Números do Instagram podem divergir do que o app nativo mostra. `views` inclui
  replays e unifica formatos; era outra definição antes de abril de 2025. Isso
  está declarado nos Termos de Uso publicados, porque quem compara os dois vai
  notar.
- Nada aqui foi validado contra a rede real — não há App Review aprovado. O que
  existe é a conformidade com a documentação vigente e a suíte que trava cada
  decisão. A validação de verdade só acontece com o app aprovado, e é o próximo
  marco.
