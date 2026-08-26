# B12 — Teste de IDOR (Insecure Direct Object Reference)

- **Data:** 2026-08-25
- **Objetivo:** validar empiricamente a linha *Information Disclosure* da
  modelagem STRIDE — autenticar como a agência A e tentar alcançar recursos da
  agência B em todos os endpoints que recebem identificador.

## Ambiente

O teste rodou contra uma instância isolada da API (porta 5001) apontada ao
**PostgreSQL local**, e não à instância gerenciada. A autorização é lógica de
aplicação e independe do SGBD, então a evidência é a mesma; a escolha evita
inserir uma agência sintética na base usada para demonstração. O scheduler foi
desligado (`LUMINA_DISABLE_SCHEDULER=1`) e a chave do Gemini removida do
ambiente, para o teste não consumir cota.

Foi criada uma agência B com um recurso de cada tipo (usuário, influenciador,
conta social, post, campanha e relatório) pelo script
[`scripts/idor_setup.py`](scripts/idor_setup.py). Ao final, a agência e todos os
seus registros dependentes foram removidos e o banco voltou à contagem original
(1 agência, 197 posts).

## Metodologia — três controles por endpoint

Um 404 isolado não prova isolamento: pode significar apenas que a rota não
existe. Por isso cada endpoint foi exercitado três vezes:

| Controle | Requisição | Esperado | O que prova |
|---|---|---|---|
| 1 | sem token, id de B | `401` | a rota existe e exige autenticação — o 404 do controle 2 não é erro de roteamento |
| 2 | token de A, id de B | `403` ou `404` | **o teste de IDOR** |
| 3 | token de A, id de A | `2xx` | controle positivo: o endpoint de fato serve o recurso quando o dono pede |

O controle 3 só se aplica a `GET`: rodá-lo em `PATCH`/`DELETE` destruiria os
dados da própria agência A.

## Resultado — recursos individuais

**26 casos, 26 aprovados, 0 falhas.** Todos os endpoints com identificador
responderam `401` sem token, `404` para o recurso da outra agência e `2xx` para
o recurso próprio.

| Método | Endpoint | s/ token | A→B | A→A |
|---|---|---|---|---|
| GET | `/agencies/{id}` | 401 | 404 | 200 |
| PATCH | `/agencies/{id}` | 401 | 404 | — |
| DELETE | `/agencies/{id}` | 401 | 404 | — |
| GET | `/agencies/{id}/usage` | 401 | 404 | 200 |
| GET | `/users/{id}` | 401 | 404 | 200 |
| PATCH | `/users/{id}` | 401 | 404 | — |
| DELETE | `/users/{id}` | 401 | 404 | — |
| GET | `/influencers/{id}` | 401 | 404 | 200 |
| PATCH | `/influencers/{id}` | 401 | 404 | — |
| DELETE | `/influencers/{id}` | 401 | 404 | — |
| GET | `/influencers/{id}/analysis` | 401 | 404 | 200 |
| GET | `/influencers/{id}/posts` | 401 | 404 | 200 |
| POST | `/influencers/{id}/sync` | 401 | 404 | — |
| GET | `/social-accounts/{id}` | 401 | 404 | 200 |
| PATCH | `/social-accounts/{id}` | 401 | 404 | — |
| DELETE | `/social-accounts/{id}` | 401 | 404 | — |
| POST | `/integrations/instagram/disconnect/{id}` | 401 | 404 | — |
| GET | `/campaigns/{id}` | 401 | 404 | 200 |
| PATCH | `/campaigns/{id}` | 401 | 404 | — |
| DELETE | `/campaigns/{id}` | 401 | 404 | — |
| GET | `/campaigns/{id}/benchmarking` | 401 | 404 | 200 |
| GET | `/posts/{id}` | 401 | 404 | 200 |
| GET | `/posts/{id}/analyses` | 401 | 404 | 200 |
| POST | `/posts/{id}/analyze` | 401 | 404 | — |
| GET | `/reports/{id}` | 401 | 404 | 200 |
| GET | `/reports/{id}/download` | 401 | 404 | 200 |

Reprodução: [`scripts/idor_sweep.py`](scripts/idor_sweep.py).

### Por que 404 e não 403

A negativa uniforme é `404`, não `403`, e isso é deliberado: `403` confirmaria
que o identificador existe em alguma agência, o que já é divulgação de
informação. A decisão está centralizada em `utils/authz.get_scoped_or_404`, que
filtra por id **e** por agência na mesma query — o registro de outra agência
nunca chega a ser carregado.

## Resultado — listagens

O acesso direto é só metade da superfície: uma listagem que devolvesse recursos
alheios vazaria o mesmo dado sem precisar de identificador. Verificado com o
token de A que o recurso correspondente de B não aparece:

| Listagem | Itens devolvidos a A | Recurso de B presente |
|---|---|---|
| `/influencers` | 15 | não |
| `/campaigns` | 6 | não |
| `/users` | 7 | não |
| `/social-accounts` | 27 | não |
| `/reports` | 6 | não |
| `/agencies` | 1 | não |

**6 listagens, 0 vazamentos.** Reprodução:
[`scripts/idor_listas.py`](scripts/idor_listas.py).

## Achado colateral — `dev-login` habilitado em staging

`POST /auth/dev-login` emite um par de tokens para qualquer usuário seedado, sem
passar por OAuth. Ele é protegido por `DEV_LOGIN_ENABLED`, que `ProdConfig`
fixa em `False` no código — não dá para religar por variável de ambiente, o que
está correto.

`StagingConfig`, porém, herda o default de `Config`, que lê a variável de
ambiente com fallback `"true"`. Em staging, esquecer de declarar
`DEV_LOGIN_ENABLED=false` deixa exposto um endpoint que emite JWT de
administrador sem credencial nenhuma — *Spoofing* e *Elevation of Privilege* na
modelagem STRIDE, na mesma linha de gravidade que o IDOR que este teste
descartou.

**Corrigido.** `StagingConfig` passou a fixar `DEV_LOGIN_ENABLED = False` no
código, como `ProdConfig` já fazia — o atalho vale agora só em `DevConfig` e
`TestConfig`. Um teste parametrizado cobre os dois ambientes e declara
`DEV_LOGIN_ENABLED=true` no ambiente antes de verificar, garantindo que
nenhuma variável religue o atalho. Verificado que o teste falha sem a correção.

## Conclusão

Nenhuma referência direta insegura foi encontrada em 26 endpoints e 6 listagens.
O isolamento entre agências não depende de o desenvolvedor lembrar de filtrar em
cada rota: está concentrado em um helper único, e é isso que sustenta o
resultado. A ameaça de *Information Disclosure* modelada no STRIDE está
mitigada e verificada. A exposição do `dev-login` em staging, encontrada no
caminho, foi corrigida e coberta por teste.
