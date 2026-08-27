# ADR-005 — A separação entre alcance orgânico e pago vem do seed, não das APIs

- **Status:** aceito
- **Data:** 2026-08-27
- **Relacionada:** [ADR-003](0003-ausencia-de-dado-nunca-vira-zero.md), cujo
  princípio esta decisão contraria conscientemente num ponto delimitado.

## Contexto

O critério de aprovação da etapa B8 é "conta real vinculada; sync traz posts com
orgânico/pago separados". A vinculação e a coleta foram atingidas: uma conta de
YouTube foi conectada por OAuth e o `sync_influencer` gravou dez posts reais do
canal, com exibições, curtidas e comentários vindos da plataforma.

A separação entre alcance orgânico e pago **não foi**, e a razão não é de
implementação — é de acesso.

| Plataforma | O que a API concede | O que falta para separar |
|---|---|---|
| YouTube | `statistics.viewCount` da Data API v3: total de exibições | a origem paga só aparece cruzando com Google Ads; a Analytics API não devolve `adType` para canal sem campanha vinculada |
| Instagram / Meta | alcance total em `/insights` | métrica de alcance pago exige a **Marketing API**, com App Review e Business Verification |
| TikTok | alcance total | separação só na API de anúncios, sujeita a aprovação comercial |

Nos três casos a barreira é aprovação de conta comercial junto à plataforma, com
prazo indeterminado e requisito de domínio público em HTTPS — fora do que a
entrega de 11–17/09/2026 comporta.

Enquanto isso, o `YouTubeAdapter` gravava `reach_organic = views` e
`reach_paid = 0` fixos. Isso faz o sistema **afirmar 100% de alcance orgânico**
para um criador sincronizado de verdade, sem ter medido a divisão — o mesmo
defeito que a ADR-003 eliminou em quatro pontos, reaparecendo pela porta do dado
real.

## Alternativas consideradas

**Migration tornando `reach_organic`, `reach_paid` e `shares` anuláveis.** É o
que a ADR-003 pede: sem saber o pago, também não se sabe o orgânico, e ambos
sairiam `null` com `reach_total = views`. Rejeitada por prazo — as colunas são
`NOT NULL` (`src/models/post.py:65-71`), a migration alcança seed, relatório
PDF, benchmarking e dashboard, e a decisão de não migrar schema antes da entrega
já estava tomada.

**Não gravar os três campos no sync real**, deixando o default do banco. Mais
barato, mas o resultado na tela é idêntico: zero exibido como se fosse medido,
agora sem nem o registro de que foi decidido assim.

**Declarar o limite e manter o seed como fonte da divisão.** Escolhida.

## Decisão

A divisão entre alcance orgânico e pago exibida pelo sistema é **dado de seed**,
não coleta. Vale para as três plataformas, pela mesma razão: a métrica está
atrás de programa comercial da plataforma, não atrás de código.

O que vem de coleta real, quando há conta conectada, é o que a API concede sem
programa comercial: exibições, curtidas, comentários, inscritos e o conteúdo dos
posts — que é o que alimenta a análise de IA, o objeto do trabalho.

Esta decisão fica **restrita à divisão de alcance**. A ADR-003 continua valendo
para toda métrica derivada: `organic_pct` sobre um total inexistente permanece
`null`, e um criador sem post continua sem exibir percentual algum.

## Consequências

- A demonstração e a escrita precisam declarar o limite ao apresentar a divisão
  de alcance. Apresentá-la como coleta seria afirmar medição que não houve — e o
  trabalho é sobre não fazer isso.
- Um criador com conta real conectada exibe alcance pago zerado. É o custo
  aceito, e o único ponto do sistema onde ausência aparece como zero por decisão
  registrada, em vez de por descuido.
- A dívida está delimitada: quando houver App Review aprovado ou conta de
  anúncios vinculada, o campo passa a vir da API sem mudança de contrato — a
  coluna já existe e já é preenchida.
- `shares` tem a mesma natureza no YouTube: a Data API v3 não expõe
  compartilhamento. Segue em zero pela mesma razão.
