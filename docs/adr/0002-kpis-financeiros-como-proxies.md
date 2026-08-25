# ADR-002 — KPIs financeiros calculados como proxies declarados

- **Status:** aceito
- **Data:** 2026-08-25

## Contexto

O dashboard promete ROI e CAC por campanha. Ambos exigem dados que o sistema
não tem acesso: receita atribuída e conversões. As plataformas sociais expõem
alcance, impressões e engajamento — não vendas. Integrar checkout ou pixel de
conversão da marca cliente está fora do escopo.

A tensão é entre exibir um número que a agência espera ver e não afirmar uma
medição que não foi feita.

## Alternativas consideradas

**Omitir ROI e CAC.** Íntegro e inútil: são justamente os indicadores que
sustentam a decisão de renovar contrato com um criador, e a ausência deles
esvazia a proposta do produto.

**Pedir que a agência informe a receita manualmente.** Daria ROI real. Depende
de a agência ter e digitar o dado a cada campanha; na prática o campo fica
vazio e o indicador some.

**Derivar de EMV (earned media value).** Atribui um valor de mídia a cada
interação e compara com o orçamento investido. É método corrente em marketing
de influência, calculável com o que já existe no banco, e a premissa fica
explícita num único lugar.

## Decisão

ROI e CAC são proxies derivados de EMV, com a constante de valor por
engajamento centralizada em `metric_service.ENGAGEMENT_VALUE_CENTS`
(R$ 2,50 por interação, faixa de benchmark de criadores mid/premium).

- `EMV = engajamentos totais × valor por engajamento`
- `ROI% = (EMV − custo) / custo × 100`
- `CAC proxy = custo / engajamentos totais` — custo por interação, não por
  cliente adquirido

Sem custo registrado, os dois devolvem `null` em vez de zero: a interface
mostra ausência de dado, não desempenho nulo.

## Consequências

- Os números não são ROI e CAC contábeis. A interface os apresenta como
  estimativa e o CAC leva a dica "custo por interação" para não ser lido como
  custo de aquisição.
- O resultado é sensível a uma constante arbitrária. Comparação entre criadores
  e entre períodos permanece válida, porque todos usam a mesma base; o valor
  absoluto não deve ser levado a uma planilha financeira.
- Substituir o proxy por receita real depois exige mudar um único módulo, já
  que o cálculo não está espalhado pelos endpoints.
- A constante precisa de revisão periódica: valor de mídia por interação varia
  com mercado e nicho.
