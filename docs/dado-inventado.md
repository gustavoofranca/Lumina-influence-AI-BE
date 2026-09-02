# Dado inventado: inventário e o que virou medição

Levantamento de 2 de setembro de 2026, feito para responder a uma pergunta
direta: *o que ainda usa dado mockado e pode passar a ter função real?*

O front-end saiu limpo — nenhum dado fictício, apenas configuração (itens de
menu, abas, idiomas). Tudo que a tela mostra vem da API. O que havia estava no
back-end, e em duas formas bem diferentes.

## As duas formas

**Dado de demonstração** é o seed: agência, criadores, campanhas, publicações e
comentários gerados por proporção. Não é defeito e não deve virar real — é o
que faz a aplicação ter o que mostrar sem depender de contas conectadas.

**Dado inventado** é outra coisa: um número apresentado como medido que não foi
medido. Aqui não importa se o ambiente é de demonstração; a tela afirma algo
sobre o dado, e a afirmação é falsa.

O inventário separou os dois, e o segundo grupo tinha dois casos — os dois
corrigidos no mesmo dia.

## Caso 1: retenção que existia em todo lugar, menos na coleta

`avg_watch_time` e `retention_rate` estavam no modelo, no schema, no tipo
normalizado e no serviço de persistência desde a B7. O painel já os consumia
para montar o destaque de retenção. O escopo `yt-analytics.readonly` já estava
concedido desde a B8.

**Ninguém os coletava.** Para a conta real conectada, chegavam sempre nulos;
para as de demonstração, vinham inventados pelo seed —
`uniform(0.35, 0.85)`. Não era lacuna de escopo nem de modelagem: era um fio
solto entre duas pontas prontas.

A YouTube Analytics API é um host próprio, não um recurso da Data API v3, e é a
única que entrega os dois. Uma requisição por coleta resolve, com
`dimensions=video` — sem isso a API agrega todos os vídeos numa linha e a
retenção de um vídeo passa a ser a média do canal.

Três decisões que valem registro:

- **Best-effort.** A API responde 403 para canal sem relatório de proprietário
  e omite a linha de vídeo recém-publicado. Nenhum dos dois é motivo para
  perder a coleta: a retenção é enfeite do painel, o alcance é o produto.
- **Nulo, nunca zero.** Retenção zero afirma "ninguém assistiu"; ausência de
  medição não afirma nada (ADR-003).
- **Leitura pela ordem declarada** em `columnHeaders`, e não por posição fixa.
  Assumir posição quebraria em silêncio se a API acrescentasse coluna, e o erro
  seria trocar duração por percentual — que passa por plausível.

## Caso 2: precisão inventada no cartão que mais promete rigor

O cartão de integridade de audiência mostrava **três** percentuais — orgânico,
suspeito, bot — e o modelo devolvia **um**: `bot_probability`. Os outros dois
saíam de:

```python
suspicious_pct = round(bot * 0.6, 1)
bots_pct = round(bot * 0.4, 1)
```

Duas constantes que ninguém justificou, num cartão chamado "integridade".

Este é o caso mais desconfortável do projeto inteiro, e por isso vale a pena
contá-lo: o defeito não era exibir um número errado, era **exibir três números
onde só havia um**. Nenhuma verificação pega isso — o valor é plausível, a soma
fecha 100, o gráfico desenha bonito. O que denuncia é ler o código que produz o
número, não a tela que o mostra.

A correção foi pedir ao modelo a segunda faixa como grandeza própria, com a
regra que as separa escrita no prompt: automação clara de um lado, dúvida não
conclusiva do outro. Sem essa distinção, "suspeito" e "bot" viram sinônimos na
cabeça do modelo e os dois números voltam a dizer a mesma coisa — o problema
anterior com outra roupa.

**A coluna é nullable de propósito.** Análise gerada antes da mudança não mediu
a faixa, e preenchê-la com qualquer valor reintroduziria exatamente a invenção
removida. Ela sai `null`, o cartão desenha **duas** fatias, e uma linha diz que
a terceira não foi medida — omitir em silêncio deixaria o cartão com cara de
completo, e o usuário somaria dois números achando que fecham a audiência.

Faixas que somam mais de 100 omitem a composição inteira. Normalizar inventaria
uma divisão.

## O que continua vindo do seed, e por quê

| O que | Por que não vira real | Decisão |
|---|---|---|
| Alcance orgânico × pago | exige Marketing API (Meta) ou Ads (Google), atrás de programa comercial e de outro App Review | [ADR-005](adr/0005-alcance-organico-e-pago-vem-do-seed.md) |
| ROI e CAC | exigiriam dado de conversão que a plataforma não coleta | [ADR-002](adr/0002-kpis-financeiros-como-proxies.md) |
| Métricas das publicações de demonstração | é o dado de demonstração; torná-lo real significaria conectar 13 contas | — |
| Crescimento do sync simulado | modo de demonstração, agora **declarado na tela**: o resumo diz "modo demonstração" em vez de "sincronizado" | — |

Os dois primeiros são limites declarados, com decisão registrada e defensáveis.
O que os torna defensáveis não é a decisão em si — é a tela dizer que aquele
número vem do seed.

## A lição que fica

As duas formas de dado falso pedem tratamentos opostos. Dado de demonstração
precisa ser **rotulado**; dado inventado precisa ser **removido**.

E o inventado não se acha olhando a tela: o número é plausível, a soma fecha, o
gráfico desenha. Achou-se lendo o código que produz o número e perguntando de
onde vem cada parcela. É a mesma leitura que achou os defeitos dos adaptadores
e as afirmações falsas dos documentos publicados — e é a única varredura deste
projeto que não deu para automatizar.
