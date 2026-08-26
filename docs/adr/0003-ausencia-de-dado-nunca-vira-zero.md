# ADR-003 — Ausência de dado é `null`, nunca zero

- **Status:** aceito
- **Data:** 2026-08-26
- **Relacionada:** [ADR-002](0002-kpis-financeiros-como-proxies.md), que aplicou
  este princípio a ROI e CAC antes de ele ser generalizado.

## Contexto

O sistema audita a performance de criadores. A tese do trabalho é que métrica
sem auditoria é prejuízo oculto — e a auditoria começa por não afirmar o que não
foi medido.

Em quatro pontos independentes o sistema apresentava ausência de dado como
desempenho zero:

| Onde | O que dizia | O que era verdade |
|---|---|---|
| Relatório PDF de período sem post | "0,0% do alcance foi orgânico" | nenhum alcance foi medido |
| Tela de análise do criador | engajamento, alcance e sentimento em `0%` | o detalhe não trazia métricas |
| Coluna "última análise" | "31 de dez." | nunca houve análise (`new Date(null)` cai no epoch) |
| KPI de engajamento no dashboard | `0%` ao lado de ROI e CAC em `—` | não havia post no período |

A origem estava em `metric_service`, que mantinha duas convenções a poucas
linhas de distância: `_avg()` — usada pelas agregações de IA — devolvia `None`
sem amostra, enquanto `engagement_rate()` e `reach_split()` devolviam `0.0`. A
mesma tela então exibia sentimento em `—` e engajamento em `0%` para o mesmo
criador sem post, contando a mesma ausência de duas formas.

## Alternativas consideradas

**Manter o zero e documentar.** Nada a implementar, e é o comportamento que a
maioria dos dashboards de mercado tem. Mas é exatamente a opacidade que o
trabalho se propõe a combater: quem lê "0,0% de alcance orgânico" conclui que a
campanha teve alcance ruim, não que não houve campanha.

**Zero no back-end, travessão no front.** A interface decidiria pela ausência
comparando com um sentinela. Transfere para cada componente uma decisão que é do
domínio, e falha no primeiro consumidor novo — o PDF, por exemplo, é renderizado
no servidor e não passa pelo adaptador do front.

**`null` na origem, com a distinção entre soma e razão.** Escolhida.

## Decisão

Toda métrica que é **razão, média ou score** devolve `null` quando não há base
de cálculo. Toda métrica que é **soma** devolve `0`, porque somar nada dá zero
de verdade.

A distinção é o que evita cair no extremo oposto:

- `reach_split()["organic"]` → `0` (soma de alcance)
- `reach_split()["organic_pct"]` → `None` (razão sobre um total inexistente)
- `engagement_rate()` → `None` sem post com alcance
- `resonance_score()` → compõe apenas as parcelas medidas; `None` se nenhuma
- `viral_potential(None)` → `None`, porque a faixa qualitativa deriva do score

Ordenações e agregações passam a tratar `null` explicitamente: quem não foi
medido vai para o fim do ranking e fica fora do cálculo da média, em vez de
entrar como se tivesse pontuado zero.

A formatação para exibição fica no back-end (`_fmt_pct`), num único lugar, para
que PDF e pré-visualização mostrem o mesmo travessão. O valor cru continua no
payload para alimentar gráficos.

## Consequências

- O contrato da API muda: campos que sempre vinham numéricos passam a admitir
  `null`. O único consumidor é o front-end deste projeto, atualizado no mesmo
  passo; o adaptador deixa de fazer `?? 0` e os componentes que formatam
  percentual mostram `—`.
- Um criador recém-cadastrado aparece com métricas vazias em vez de com notas
  ruins. É o comportamento correto e muda a leitura da tela de listagem: ausência
  não compete com desempenho.
- Gráficos passam a receber `null` em vez de zero. O radar abre uma lacuna na
  dimensão não medida em vez de desenhar um vértice na origem — visualmente mais
  honesto, e o Recharts trata isso nativamente.
- O custo é vigilância: toda métrica nova precisa declarar de qual lado da linha
  está. O teste `test_metricas_de_performance_sem_base_vem_nulas` fixa a regra
  para soma e razão, e serve de referência para as próximas.
