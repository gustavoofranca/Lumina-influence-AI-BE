# B12 — Verificação de segurança e desempenho

Índice consolidado dos relatórios que a banca pediu explicitamente na
apresentação anterior: segurança, carga e documentação visual da arquitetura.
Cada linha da tabela abaixo tem um relatório próprio com método, dados brutos e
como reproduzir.

- **Período de execução:** 25 a 27 de agosto de 2026
- **Suíte do back-end ao fim da bateria:** 230 testes, 85% de cobertura de `src/`
- **Suíte do back-end em 28/08, após a frente de robustez:** 286 testes, 90%

## Resultado por frente

| # | Frente | Resultado | Relatório |
|---|---|---|---|
| 1 | Análise estática e dependências | 0 achados Medium/High em 6.436 linhas; 8 → 4 vulnerabilidades de dependência, nenhuma alcançável | [`security/analise-estatica.md`](security/analise-estatica.md) |
| 2 | Controle de acesso (IDOR) | 26 endpoints e 6 listagens sondados com identidade de outra agência; **zero vazamento** | [`security/idor.md`](security/idor.md) |
| 3 | Prompt injection contra o modelo real | 7 famílias de ataque, **7 resistiram**; schema íntegro em todas | [`security/prompt-injection.md`](security/prompt-injection.md) |
| 4 | Carga e saturação | satura em ~43 req/s, **zero falhas até 600 usuários**; ganho acumulado de 4,5× | [`testes/carga.md`](testes/carga.md) |
| 5 | Robustez da geração de PDF | 11 cenários adversos, nenhum arquivo corrompido | [`testes/robustez-pdf.md`](testes/robustez-pdf.md) |
| 6 | Documentação visual da arquitetura | 4 diagramas em Mermaid, versionados com o código | [`arquitetura/README.md`](arquitetura/README.md) |
| 7 | Integração social contra conta real (B8) | canal de YouTube vinculado por OAuth, 10 posts e comentário real coletados; limite de alcance pago declarado | [`testes/integracao-social.md`](testes/integracao-social.md) |
| 8 | Verificação de interface pré-entrega | 6 verificações sobre a interface em funcionamento; a última execução achou 1 tela que não renderizava | [`testes/verificacao-pre-entrega.md`](testes/verificacao-pre-entrega.md) |
| 9 | Robustez da camada de integração | 56 cenários sobre YouTube, Gemini e mídia; os três módulos de 33–39% para **100%** | [`testes/robustez-adaptadores.md`](testes/robustez-adaptadores.md) |

As capturas de tela do produto em funcionamento, com legenda pronta para a
escrita, estão em [`capturas/`](capturas/).

Decisões de projeto tomadas durante a bateria estão registradas como ADR em
[`adr/`](adr/). O limite de coleta que a B8 expôs — a divisão entre alcance
orgânico e pago não é concedida pelas APIs sem programa comercial — está na
[ADR-005](adr/0005-alcance-organico-e-pago-vem-do-seed.md).

## O que cada frente encontrou

**Estática (item 1).** `bandit` não apontou nada de severidade média ou alta; os
18 achados Low foram verificados um a um e são falso positivo — URLs de OAuth
lidas como senha e `random` usado só em seed e simulação. `pip-audit` não achou
vulnerabilidade conhecida. No front-end, o `npm audit` caiu de 8 para 4 depois
de corrigir a cadeia de build; as 4 restantes exigem salto de major e nenhuma é
alcançável pelo código do produto — o open redirect do `react-router` depende de
destino controlado pelo atacante, e os 12 pontos de navegação dinâmica do
front-end usam prefixo fixo com ID vindo da API.

**IDOR (item 2).** Cada endpoint foi sondado com três controles: sem token, com
token de outra agência e com identificador inexistente. Nenhum devolveu recurso
alheio. O teste rodou contra uma instância isolada com uma agência sintética
criada e removida ao final; os scripts ficaram em
[`security/scripts/`](security/scripts/).

**Carga (item 4).** O achado mais consequente do B12 não veio da concorrência,
veio de comparar o mesmo endpoint contra o banco local e contra o gerenciado com
**um único usuário**: `/dashboard/overview` levava 15 segundos no Supabase.
Eram 70 consultas por requisição multiplicadas pelo round trip até `us-west-2`.
Sem concorrência não há fila, então a diferença era latência pura — e foi ela
que expôs o N+1. Corrigido para 13 consultas e 3,2 s, com um teste travando o
teto de consultas para impedir regressão. A bateria também mostrou que medir
vazão sobre o servidor de desenvolvimento do Flask descreve o Werkzeug, não a
arquitetura: refeita sobre `gunicorn` com 4 workers, a latência com 50 usuários
caiu de 880 ms para 64 ms.

**PDF (item 5).** Nenhum dos 11 cenários adversos produziu arquivo corrompido.
Acentuação e glifos passam; emoji não, e passou a ser removido antes da
renderização com aviso em log nomeando cada caractere.

**Prompt injection (item 3).** As sete famílias de ataque resistiram. O achado
de método veio de um falso positivo: a primeira execução acusou obediência
porque o marcador da carga aparecia em `key_phrases` — o campo que extrai
frases do conteúdo, sendo que a carga *é* o conteúdo. Repetir a execução
mostrou que a resposta do modelo varia entre rodadas idênticas, o que significa
que teste sobre modelo generativo exige repetição para não produzir achado
inexistente.

## O que a cota do free tier ainda impede

O free tier concede **20 requisições por dia, por projeto e por modelo**
(`quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier`) — não é limite
por minuto, e esperar não resolve. Foi o que atrasou o item 3 em um dia, e é o
que motivou desligar o agendador por padrão (`LUMINA_DISABLE_SCHEDULER=1`),
já que `run_pending_analyses` consumia a cota sozinho nas primeiras horas.

A mesma restrição impede o teste de **carga** sobre `POST /posts/:id/analyze` e
o requisito de p95 ≤ 60 s medido contra o modelo real: 20 requisições diárias
não sustentam bateria de carga nenhuma. O que existe é a medição isolada — a
análise real leva ~25 s contra o banco local e ~50 s contra o gerenciado, dentro
do requisito mas com margem estreita.

## Achados de segurança corrigidos durante a bateria

| Achado | Origem | Situação |
|---|---|---|
| `dev-login` habilitado em staging por herança do default do ambiente | item 2 | corrigido — `DEV_LOGIN_ENABLED = False` fixo em `StagingConfig` e `ProdConfig` |
| Falha ao remover arquivo enviado ao Gemini era descartada em silêncio | item 1 | corrigido — passou a `logger.warning` com o nome do arquivo |
| Sob `gunicorn`, cada worker criava seu próprio APScheduler e todo job rodava 4× | item 4 | corrigido — agendador virou opt-in por `LUMINA_SCHEDULER_ROLE=worker` |

## Dívida aceita até depois da entrega

- 4 vulnerabilidades de dependência no front-end, todas exigindo salto de major
  (`vite`/`esbuild` na cadeia de build, `react-router` no produto). Nenhuma
  alcançável; atualizar a duas semanas da entrega custa mais do que resolve.
- 3 rotas fora do OpenAPI, por decisão: `GET /docs` e `GET /openapi.json`, que
  são a própria documentação, e `POST /auth/dev-login`, atalho de
  desenvolvimento que não deve ser anunciado. As outras 53 estão documentadas.

## Um padrão que atravessou o projeto inteiro

Vale registrar porque não é achado de uma frente só: **ausência de dado
apresentada como zero**. Apareceu em quatro lugares independentes — relatório de
período sem post declarando "0,0% do alcance foi orgânico", tela de análise
caindo em `?? 0` quando o detalhe não trazia métricas, coluna "última análise"
exibindo "31 de dez." porque `new Date(null)` cai no epoch sem lançar erro, e KPI
de engajamento mostrando `0%` ao lado de indicadores em `—`.

Num trabalho sobre auditoria de dado, exibir número inventado como se fosse real
é o pior defeito possível. A regra está na [ADR-002](adr/0002-kpis-financeiros-como-proxies.md):
sem dado, o back-end devolve `null` e a interface mostra ausência.
