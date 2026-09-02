# B12 — Verificação de segurança e desempenho

Índice consolidado dos relatórios que a banca pediu explicitamente na
apresentação anterior: segurança, carga e documentação visual da arquitetura.
Cada linha da tabela abaixo tem um relatório próprio com método, dados brutos e
como reproduzir.

- **Período de execução:** 25 a 27 de agosto de 2026
- **Suíte do back-end ao fim da bateria:** 230 testes, 85% de cobertura de `src/`
- **Suíte do back-end em 02/09:** 438 testes, 95%
- **Suíte de interface:** 70 testes ponta a ponta em Playwright

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
| 9 | Robustez das bordas | 133 cenários sobre integrações, login e filtros de listagem; **9 defeitos achados e corrigidos**; os 5 adaptadores em 100% | [`testes/robustez-adaptadores.md`](testes/robustez-adaptadores.md) |
| 10 | Testes ponta a ponta da interface | 46 testes em Playwright cobrindo rotas, login, estado de erro, conta social, relatório, tema, idioma, foco, páginas legais e os três caminhos de exclusão | [`testes/e2e-front.md`](testes/e2e-front.md) |
| 11 | Preparação do App Review da Meta | 7 requisitos de código cumpridos; 3 defeitos que causariam rejeição, corrigidos | [`meta-app-review.md`](meta-app-review.md) |
| 12 | Conformidade entre documento publicado e código | 29 afirmações auditadas; **5 divergências, 4 resolvidas construindo** | [`conformidade-publicada.md`](conformidade-publicada.md) |
| 14 | Dado inventado × dado de demonstração | 2 casos de precisão inventada, ambos convertidos em medição | [`dado-inventado.md`](dado-inventado.md) |
| 13 | Ações que a interface oferecia e não aconteciam | 1 mentira de interface, 4 endpoints prontos sem caminho na tela e 1 lacuna de back-end | [`acoes-que-nao-aconteciam.md`](acoes-que-nao-aconteciam.md) |

Para escrever: [`resultados-consolidados.md`](resultados-consolidados.md) reúne
cada número medido, o método que o produziu e o relatório de origem — mais os
limites que o texto precisa declarar.

As capturas de tela do produto em funcionamento, com legenda pronta para a
escrita, estão em [`capturas/`](capturas/).

Decisões de projeto tomadas durante a bateria estão registradas como ADR em
[`adr/`](adr/). O limite de coleta que a B8 expôs — a divisão entre alcance
orgânico e pago não é concedida pelas APIs sem programa comercial — está na
[ADR-005](adr/0005-alcance-organico-e-pago-vem-do-seed.md); a escolha de
configuração, versão e métrica do Instagram, na
[ADR-007](adr/0007-instagram-com-facebook-login-e-views.md).

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

O custo de sair dessa cota foi medido a partir de `api_usage_logs` e está em
[`cota-e-custo-gemini.md`](cota-e-custo-gemini.md): o limite nunca foi de preço.

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

**Bordas (item 9), rodadas 4 e 5.** Ler os dois adaptadores nunca exercidos
contra a rede real — Instagram e TikTok — contra a documentação vigente achou
**seis defeitos**, nenhum deles visível em ambiente local: todos dependem de uma
resposta que só a plataforma real produz. O mais representativo é do TikTok, que
responde `200` mesmo quando falha, com o erro dentro do corpo: token revogado
virava lista vazia e a tela dizia "criador sem post".

**App Review da Meta (item 11).** Preparar a submissão obrigou a ler o adaptador
do Instagram contra a documentação vigente, e achou três defeitos que nenhum
teste local pegaria — todos dependem de um token real. O mais grave: o código
pedia `impressions`, removida da API em abril de 2025, que hoje devolve **erro**
e derrubaria a coleta inteira do criador conectado. Os outros dois foram falar
com o nó errado da Graph (`/me`, que num token de Facebook é a pessoa e não o
perfil do Instagram) e um escopo faltando, que só falharia **depois** da
aprovação. Junto entraram as três páginas públicas que o revisor abre antes de
olhar o app — política de privacidade, termos e exclusão de dados, nos dois
idiomas —, cujos links no rodapé apontavam para `#`.

**Conformidade publicada (item 12).** As páginas legais são a única parte do
sistema em que o produto **afirma coisas sobre si mesmo para quem não pode
conferi-las** — e, diferente de qualquer outra parte do código, nada falha
quando o texto e a implementação divergem. Auditar as 29 afirmações contra o
código achou 5 divergências. Quatro viraram produto (a escolha de apagar o
histórico ao desconectar, os dois caminhos de exclusão que faltavam, e a purga
de credencial morta); a quinta virou limite declarado, porque prometer descarte
de registro que o ambiente de hospedagem retém seria promessa vazia.

O caso mais instrutivo não é de código nosso: a política afirma que os dados não
treinam modelo, o que é verdade no tier pago do Gemini e falso no free tier, sem
diferença detectável na chave. Um compromisso que depende de alguém lembrar de
uma variável de ambiente não é compromisso — então o boot passou a reclamar e o
`/health` a publicar `model_privacy`.

## Um padrão que atravessou o projeto inteiro

Vale registrar porque não é achado de uma frente só: **ausência de dado
apresentada como zero**. Apareceu em quatro lugares independentes — relatório de
período sem post declarando "0,0% do alcance foi orgânico", tela de análise
caindo em `?? 0` quando o detalhe não trazia métricas, coluna "última análise"
exibindo "31 de dez." porque `new Date(null)` cai no epoch sem lançar erro, e KPI
de engajamento mostrando `0%` ao lado de indicadores em `—`.

Depois apareceu em mais três formas: **ausência de resposta** lida como ausência
de dado (quatro telas afirmando "nenhum registro" com a API fora do ar),
**ausência tratada como exclusão** (criador sem conta social sumindo do filtro de
seguidores, porque a soma era `INNER JOIN`) e, em 31/08, **conta não vinculada
lida como criador sem publicação** — o Instagram devolvia lista vazia para conta
pessoal, e o resto do sistema não tem como distinguir "não publicou" de "não
temos acesso".

Num trabalho sobre auditoria de dado, exibir número inventado como se fosse real
é o pior defeito possível. A regra está na [ADR-002](adr/0002-kpis-financeiros-como-proxies.md):
sem dado, o back-end devolve `null` e a interface mostra ausência. A variante da
borda é a mesma coisa: **quando o sistema não sabe, ele precisa dizer que não
sabe** — daí o `AccountNotLinkedError` em vez da lista vazia.
