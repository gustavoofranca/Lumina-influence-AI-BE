# B12 — Testes de carga

- **Data:** 2026-08-26
- **Ferramenta:** Locust 2.46 · cenários em [`locustfile.py`](locustfile.py)
- **Escopo:** os dois cenários que não passam pelo Gemini. O terceiro
  (`POST /posts/:id/analyze`, requisito p95 ≤ 60s) não foi executado: o free
  tier do modelo permite 20 requisições por dia, o que não sustenta teste de
  carga nenhum.

## Ambientes

| | Aplicação | Banco |
|---|---|---|
| Local | instância isolada em contêiner | PostgreSQL 17 no mesmo host |
| Gerenciado | mesma imagem | Supabase, região `us-west-2` |

Nos dois casos a aplicação roda no **servidor de desenvolvimento do Flask** —
processo único. Isso limita o que os números de vazão significam, e está
discutido em "Limite do arnês", ao final.

## Cenário 1 — baseline em `/dashboard/overview`

### O que a primeira execução mostrou

| Concorrência | Vazão | p50 | p95 |
|---|---|---|---|
| 1 usuário | 0,63 req/s | 89 ms | 110 ms |
| 50 usuários | 9,49 req/s | 3.600 ms | 6.000 ms |

Uma requisição isolada custa 89 ms; cinquenta simultâneas custam 3,6 s. A
degradação é de 40×, e a vazão trava em ~10 req/s — que é exatamente
`1 ÷ 0,105 s`, o comportamento de quem atende uma requisição por vez.

### Curva de saturação (cenário 2)

| Usuários | Vazão | p95 |
|---|---|---|
| 1 | 0,63 req/s | 120 ms |
| 2 | 1,27 req/s | 180 ms |
| 5 | 3,16 req/s | 270 ms |
| 10 | 6,19 req/s | 300 ms |
| 25 | 10,09 req/s | 1.800 ms |
| 50 | 9,64 req/s | 5.900 ms |

Até 10 usuários a vazão cresce proporcionalmente — o sistema ainda não está
saturado, só acompanha o ritmo dos clientes. **O teto aparece em ~10 req/s**:
de 25 para 50 usuários a vazão não sobe (chega a cair), e a latência triplica.
É a assinatura de uma fila crescendo atrás de um recurso único.

Durante a carga, o contêiner da API ficou em **~113% de CPU** e o PostgreSQL em
47%: um núcleo saturado num único processo Python. O banco não era o gargalo.

## O defeito que a carga revelou

A comparação entre ambientes é o que fecha o diagnóstico. Com **um único
usuário**:

| Endpoint | Local | Supabase |
|---|---|---|
| `/dashboard/overview` | 90 ms | **15.100 ms** |
| `/influencers?per_page=20` | — | 1.600 ms |
| `/campaigns?per_page=20` | — | 1.400 ms |
| `/dashboard/network-density` | — | 1.400 ms |

Quinze segundos sem concorrência nenhuma não é latência de rede: uma ida e
volta até `us-west-2` custa ~225 ms. Instrumentando o engine do SQLAlchemy:

```
tempo total: 15,61s · 70 queries · 15,80s dentro do banco
  32x SELECT ... FROM social_accounts
  17x SELECT ... FROM posts
  16x SELECT ... FROM ai_analyses
```

**70 round trips × 225 ms = 15,7 s.** Praticamente todo o tempo era espera de
rede, não processamento.

**Causa raiz:** `top_performing()` percorria os criadores da agência chamando
`_influencer_scorecard()` por criador, e cada chamada disparava três consultas —
posts, análises e `social_accounts` por *lazy load*. Quinze criadores, 45
consultas. O custo do endpoint crescia com o tamanho da agência.

O remédio já existia no próprio código: `influencer_metrics_bulk()` usa
`fetch_posts_by_influencer()` e `fetch_analyses_by_influencer()`, que buscam em
lote. O dashboard simplesmente não os usava. A correção liga esses helpers e
adiciona `selectinload` nas contas sociais.

### Depois da correção

| Medida | Antes | Depois |
|---|---|---|
| Queries por requisição | 70 | **13** |
| `/dashboard/overview` no Supabase, 1 usuário | 15.100 ms | **3.200 ms** |
| Local, 50 usuários — p50 | 3.600 ms | **540 ms** |
| Local, 50 usuários — p95 | 6.000 ms | **1.200 ms** |
| Local, 50 usuários — vazão | 9,49 req/s | **23,22 req/s** |
| Supabase, 5 usuários — p50 | 15.000 ms | **3.800 ms** |

Vazão 2,4× maior e latência 6,6× menor em p50, sem tocar em infraestrutura —
só removendo round trips desnecessários. Um teste em
`tests/test_dashboard.py` passa a falhar se o custo voltar a crescer por
criador.

Os 3,2 s restantes contra o Supabase são as 13 consultas remanescentes vezes a
latência da região. Reduzi-las mais exige consolidar agregações em SQL, o que é
outra ordem de trabalho.

## Limite do arnês

Os números de **vazão** medem o servidor de desenvolvimento do Flask, não a
arquitetura: um processo, um núcleo, sem paralelismo real por causa do GIL. O
`Dockerfile` diz explicitamente "não use em produção", e não há `gunicorn` nem
`waitress` no `requirements.txt`, embora `wsgi.py` e `config.py` já os
antecipem.

Os números de **latência** não sofrem dessa limitação: com 1 usuário não há
fila, e foi assim que o N+1 apareceu.

Para que a vazão signifique alguma coisa, o teste precisa rodar sobre um
servidor WSGI com múltiplos processos. Como o gargalo medido é CPU num processo
único, a expectativa é que a vazão escale aproximadamente com o número de
workers.

## Como reproduzir

```bash
pip install -r requirements.txt

locust -f docs/testes/locustfile.py --host http://localhost:5000 \
       DashboardUser --headless -u 50 -r 10 -t 90s     # baseline
locust -f docs/testes/locustfile.py --host http://localhost:5000 \
       NavegacaoUser --headless -u 50 -r 10 -t 5m      # stress
```
