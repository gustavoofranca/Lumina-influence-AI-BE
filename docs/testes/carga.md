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

## Sobre servidor WSGI — por que a primeira rodada não bastava

Os números acima medem o servidor de desenvolvimento do Flask: um processo, um
núcleo, sem paralelismo real por causa do GIL. Vazão medida assim descreve o
Werkzeug, não a arquitetura. Os de **latência** não sofrem disso — com 1 usuário
não há fila, e foi assim que o N+1 apareceu.

O `gunicorn` foi então adicionado ao `requirements.txt` e as medições refeitas
sobre ele. O contêiner de desenvolvimento continua subindo com `flask run`.

### Vazão por número de workers (50 usuários simultâneos)

| Workers | Vazão | p50 | p95 | p99 |
|---|---|---|---|---|
| 1 | 21,02 req/s | 880 ms | 1.400 ms | 1.600 ms |
| 2 | 29,92 req/s | 120 ms | 450 ms | 560 ms |
| 4 | 31,48 req/s | 64 ms | 180 ms | 360 ms |
| 8 | 31,89 req/s | 65 ms | 130 ms | 260 ms |

A latência despenca de 880 ms para 64 ms entre 1 e 4 workers. A vazão, porém,
estaciona em ~32 req/s — e **isso é limite do teste, não do servidor**: 50
usuários com pausa de 1 a 2 segundos geram no máximo `50 ÷ 1,5 ≈ 33 req/s`. A
partir de 4 workers o sistema deixou de estar saturado e passou a apenas
acompanhar a demanda oferecida.

### Ponto de saturação real (4 workers)

Empurrando a concorrência até a degradação:

| Usuários | Vazão | p50 | p95 | p99 | Falhas |
|---|---|---|---|---|---|
| 50 | 31,83 req/s | 65 ms | 140 ms | 690 ms | 0 |
| 150 | 43,13 req/s | 1.900 ms | 2.600 ms | 2.800 ms | 0 |
| 300 | 43,23 req/s | 5.200 ms | 5.800 ms | 5.900 ms | 0 |
| 600 | 38,02 req/s | 12.000 ms | 13.000 ms | 13.000 ms | 0 |

**Saturação em ~43 req/s.** Entre 150 e 300 usuários a vazão não sobe mais e a
latência cresce proporcionalmente à fila; em 600 a vazão começa a cair, sinal de
congestionamento. Nenhuma requisição falhou em nenhum patamar — o sistema
degrada em tempo de resposta, não em erro, que é o comportamento desejável.

Durante a saturação o contêiner ficou em ~290% de CPU (de 400% possíveis com 4
workers) e os processos do PostgreSQL entre 16% e 25%. A escalada de 1 para 4
workers rendeu ~2×, não 4×: os workers passam parte do tempo esperando o banco,
não calculando. Vale registrar que neste arnês o tráfego até o PostgreSQL passa
pelo gateway do host, o que acrescenta um custo que não existiria num
`docker compose` único.

### Ganho acumulado

| | Vazão | p95 |
|---|---|---|
| Servidor de dev, antes da correção do N+1 | 9,5 req/s | 6.000 ms |
| Servidor de dev, depois da correção | 23,2 req/s | 1.200 ms |
| gunicorn, 4 workers | 43,2 req/s | 2.600 ms (em 150 usuários) |

Quatro vezes e meia a vazão inicial. Metade veio de remover round trips, metade
de usar processos em vez de um só.

### Cenário 2 — tráfego misto

Uma sessão real não bate num endpoint só. `NavegacaoUser` reproduz a mistura,
com peso proporcional ao uso esperado: dashboard, listagem de criadores, a mesma
listagem enriquecida, campanhas e densidade de rede. 150 usuários, 4 workers,
90 segundos.

| Endpoint | Requisições | p50 | p95 | Vazão |
|---|---|---|---|---|
| `/dashboard/overview` | 1.983 | 290 ms | 820 ms | 22,2 req/s |
| `/influencers` | 1.437 | 210 ms | 690 ms | 16,1 req/s |
| `/campaigns` | 983 | 200 ms | 630 ms | 11,0 req/s |
| `/influencers?enriched=true` | 962 | 240 ms | 810 ms | 10,8 req/s |
| `/dashboard/network-density` | 451 | 200 ms | 650 ms | 5,1 req/s |
| **Agregado** | **5.816** | **240 ms** | **740 ms** | **65,1 req/s** |

**Zero falhas.** A vazão agregada é maior que a do cenário isolado (65 contra 43
req/s) porque a mistura inclui endpoints mais baratos que o dashboard.

Vale destacar `/influencers?enriched=true`: essa rota já tinha sido corrigida de
um N+1 antes desta bateria, e sob carga ela se mantém no mesmo patamar das
demais — a busca em lote continua valendo com concorrência, não só numa
requisição isolada.

## Achado — o scheduler não sobrevive a múltiplos workers

Subir a aplicação sob gunicorn expôs um problema que o servidor de
desenvolvimento escondia. Com 4 workers e o scheduler habilitado:

```
workers do gunicorn:               4
schedulers iniciados:              4
registros de run_pending_analyses: 4
```

Cada worker é um processo e cria sua própria instância do APScheduler. **Todo
job agendado passa a rodar uma vez por worker.**

Isso é grave num ponto específico: `run_pending_analyses` roda a cada 30 minutos
consumindo cota do Gemini, e o free tier permite 20 requisições por dia. Com 4
workers, o consumo quadruplica — a cota diária se esgota em minutos.

Não é defeito introduzido pelo gunicorn: é uma consequência de manter o
agendador em processo (`APScheduler in-process`, decisão da B7) num deploy com
mais de um processo.

**Corrigido.** Sob servidor WSGI o agendador deixou de iniciar sozinho: agora é
opt-in, e exatamente um processo assume o papel declarando
`LUMINA_SCHEDULER_ROLE=worker`. Um lock compartilhado resolveria também, mas
exigiria coordenação entre processos que este monólito não tem — e orquestração
está fora do escopo do trabalho. Designar um processo é a saída mais simples que
resolve. Em `flask run`, onde há um processo só, nada muda.

## Como reproduzir

```bash
pip install -r requirements.txt

# aplicação sob servidor WSGI de produção
LUMINA_DISABLE_SCHEDULER=1 gunicorn -w 4 -b 0.0.0.0:5000 wsgi:app

locust -f docs/testes/locustfile.py --host http://localhost:5000 \
       DashboardUser --headless -u 50 -r 25 -t 50s     # baseline
locust -f docs/testes/locustfile.py --host http://localhost:5000 \
       DashboardUser --headless -u 300 -r 100 -t 50s   # saturação
locust -f docs/testes/locustfile.py --host http://localhost:5000 \
       NavegacaoUser --headless -u 150 -r 50 -t 5m     # stress, tráfego misto
```
