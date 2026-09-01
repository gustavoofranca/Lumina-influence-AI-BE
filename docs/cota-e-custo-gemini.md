# Cota e custo do Gemini

O free tier foi o maior limitador operacional do projeto: **20 requisições por
dia, por projeto e por modelo** (`quotaId:
GenerateRequestsPerDayPerProjectPerModel-FreeTier`). Não é limite por minuto —
esperar não resolve, a janela só reabre no dia seguinte.

Ele já custou um dia de atraso no teste de prompt injection, motivou desligar o
agendador por padrão (`LUMINA_DISABLE_SCHEDULER=1`, porque
`run_pending_analyses` consumia a cota sozinho de madrugada) e impede o teste de
carga sobre `POST /posts/:id/analyze`.

O risco que importa agora é outro: **um 429 no meio da apresentação.** Vinte
requisições acabam depressa quando várias pessoas mexem no sistema ao mesmo
tempo, e a banca não vai ver a diferença entre cota esgotada e sistema quebrado.

## Quanto custaria sair do free tier

Não é estimativa: o sistema registra o consumo de cada análise em
`api_usage_logs`, e são estes os números medidos até 31/08/2026.

| Medida | Valor |
|---|---|
| Análises reais executadas | 36 |
| Tokens no total | 90.468 |
| Média por análise | **2.513 tokens** |
| Maior análise registrada | 2.875 tokens |

O preço do `gemini-3.6-flash` no tier pago é **US$ 0,75 por milhão de tokens de
entrada e US$ 3,75 por milhão de saída** (até 31/12/2026; dobra em 01/01/2027).
O log guarda o total, sem separar entrada de saída, então o cálculo abaixo
assume o pior caso — **tudo cobrado como saída**:

| Cenário | Tokens | Custo máximo |
|---|---|---|
| Uma análise | 2.513 | **US$ 0,009** (~R$ 0,05) |
| As 36 análises já feitas | 90.468 | **US$ 0,34** |
| 200 análises até a entrega final | ~503.000 | **US$ 1,89** |
| Um dia de apresentação com 50 análises | ~126.000 | **US$ 0,47** |

O custo real fica **abaixo de um quinto disso**, porque a maior parte dos tokens
de uma análise é entrada (prompt, legenda e comentários), cobrada a um quinto do
preço da saída.

**A conclusão é que o problema nunca foi preço, foi cota.** Trocar o free tier
pelo Tier 1 resolve o 429 por menos de dois dólares até o fim do projeto.

## Não existe plano mensal

Vale registrar porque a pergunta é natural e a resposta é contraintuitiva: **a
API do Gemini não tem assinatura.** Os "tiers" não são planos que se compra —
são faixas de limite que o projeto sobe sozinho conforme o gasto acumulado.

| Tier | Como se chega | Teto de gasto |
|---|---|---|
| Free | projeto ativo | — (mas 20 requisições/dia) |
| Tier 1 | **vincular uma conta de faturamento** | US$ 250/mês |
| Tier 2 | US$ 100 acumulados, há 3+ dias | US$ 2.000/mês |
| Tier 3 | US$ 1.000 acumulados, há 30+ dias | US$ 20.000+/mês |

Desde 23/03/2026 há duas formas de pagar. **Postpay** cobra no fim do mês, sem
mínimo. **Prepay** exige comprar crédito antes, a partir de **US$ 10**, que
expira em 12 meses. Para este projeto os dois servem: o Postpay não tem piso, e
os US$ 10 do Prepay cobrem a entrega final com folga — é o teto rígido para quem
prefere não deixar cartão exposto a consumo variável.

O teto de US$ 250/mês do Tier 1 é a rede de segurança: mesmo um laço acidental
não passa dali.

**Atenção ao calendário:** o preço dobra em **1º de janeiro de 2027**, para
US$ 1,50 / US$ 7,50. Uma entrega final até dezembro fica na faixa barata. Vários
sites de terceiros já publicam o valor dobrado como se fosse o atual — é o preço
de 2027, não o de hoje.

## Como sair do free tier

1. Abrir [aistudio.google.com](https://aistudio.google.com) com a conta dona da
   chave.
2. **Get API key → o projeto da Lumina → Set up billing**, e vincular uma conta
   de faturamento do Google Cloud com cartão. Vincular já basta para o Tier 1 —
   não é preciso gastar nada antes.
3. Conferir em [aistudio.google.com/rate-limit](https://aistudio.google.com/rate-limit)
   que o projeto aparece como **Tier 1**. A promoção costuma valer na hora.
4. A chave em `GEMINI_API_KEY` **continua a mesma** — o tier é do projeto, não da
   chave. Não há mudança de código.
5. Definir um **orçamento com alerta** no Google Cloud Billing (US$ 5 já é
   folgado) para que um laço acidental não vire cobrança surpresa.

Vale conferir também: no free tier o Google pode usar os dados enviados para
melhorar seus produtos; **no tier pago, não.** Como o sistema envia legenda e
comentários de criadores reais, isso é argumento de privacidade além de
disponibilidade — e a Política de Privacidade publicada afirma que os dados não
são usados para treinar modelo, o que só é verdade fora do free tier.

Depois de habilitar, declare `GEMINI_PAID_TIER=true` no `.env`. Sem isso o boot
continua reclamando e o `/health` segue publicando `model_privacy:
free_tier_warning` — a verificação existe justamente porque o tier não é
detectável pela chave. Ver [`conformidade-publicada.md`](conformidade-publicada.md).

## O que estes números não cobrem

As 36 análises medidas são **de texto**. A análise multimodal envia o vídeo para
a Files API, e vídeo consome tokens em outra ordem de grandeza — um minuto de
vídeo passa da casa dos 10 mil tokens. Nenhuma análise com vídeo entrou nesta
amostra, então o custo dela **não está medido**, apenas o de texto. Antes de
demonstrar a auditoria de vídeo, vale rodar uma e ler o `tokens_used` que ela
gravar.
