# B12 — Análise estática e auditoria de dependências

- **Data:** 2026-08-25
- **Escopo:** back-end (`bandit`, `pip-audit`) e front-end (`npm audit`)

## Ferramentas e versões

| Ferramenta | Versão | Alvo |
|---|---|---|
| bandit | 1.9.4 | `src/` do back-end (6.436 linhas) |
| pip-audit | 2.10.1 | `requirements.txt` resolvido no ambiente |
| npm audit | npm (lockfile v3) | `package.json` do front-end |

## bandit — análise estática de segurança (Python)

**Resultado: 0 achados de severidade Medium ou High.** 18 achados Low, todos
verificados individualmente e classificados como falso positivo:

| Regra | Ocorrências | Verificação |
|---|---|---|
| B105/B106 (hardcoded password) | 14 | Nomes de constantes e URLs de endpoint OAuth (`.../oauth/token`), literais `"access"`/`"refresh"`/`"Bearer"` como tipo de token, e segredos de *fixture de teste* em `TestConfig`. Nenhum segredo de produção no código — todos vêm de variável de ambiente. |
| B311 (PRNG não criptográfico) | 3 | `random` usado só para gerar dados sintéticos: seed (`seed_data.py`), simulação de crescimento de métricas no modo dev (`integration_service._simulate_sync`) e no job `sync_metrics`. Nenhum uso em token, ID ou material criptográfico — esses usam `secrets`/`cryptography`. |
| B110 (try/except/pass) | 1 | `integrations/gemini.py:154` — limpeza do arquivo enviado ao Gemini, dentro de `finally`. Falso positivo quanto a segurança, mas é engolir exceção em silêncio: se a exclusão remota falhar, o arquivo permanece consumindo cota sem registro. **Correção sugerida: trocar `pass` por `logger.warning`.** |

## pip-audit — vulnerabilidades nas dependências Python

**Resultado: `No known vulnerabilities found`.**

## npm audit — vulnerabilidades nas dependências do front-end

8 vulnerabilidades (3 high, 4 moderate, 1 low). A leitura relevante não é o
número, e sim **o que chega ao artefato entregue**:

### Grupo 1 — cadeia de build, não embarcado (6 de 8)

`vite`, `esbuild`, `postcss`, `nanoid`, `@babel/core`. São ferramentas de
compilação: o que vai para o navegador é o bundle estático que elas produzem,
não elas próprias. As falhas descritas (leitura arbitrária de `.map` via
`sourceMappingURL`, servidor de desenvolvimento aceitando requisições
cross-origin) exigem **acesso ao ambiente de desenvolvimento**, não à aplicação
publicada. Superfície real: a máquina do desenvolvedor.

`npm audit fix` resolve este grupo sem mudança incompatível.

### Grupo 2 — embarcado na aplicação (2 de 8)

`react-router` / `react-router-dom` 6.28.0 — open redirect via `<Link>` ou
`useNavigate()` quando o destino começa por `//` ou por barra invertida.

**Verificação de alcançabilidade no código:** foram inspecionados os 12 pontos
do front-end que constroem destino de navegação dinamicamente. Todos são
template literals com prefixo fixo (`/app/influenciadores/${id}`,
`/app/campanhas/${id}`, `/app/configuracoes/${key}`) e o trecho variável é um
identificador vindo da API ou de constante interna de navegação. **Não existe
ponto em que o destino inteiro seja controlado por entrada externa**, que é a
condição necessária para o open redirect. A vulnerabilidade está presente na
dependência e **não é alcançável nesta aplicação**.

A versão corrigida é a 7.18, salto de major com mudança incompatível de API de
rotas. Decisão: **não atualizar antes da entrega**, com base na análise de
alcançabilidade acima; registrar como dívida conhecida.

## Ações derivadas — aplicadas

- [x] `integrations/gemini.py` — a falha ao remover o arquivo enviado ao Gemini
  passou a ser registrada em `logger.warning` com o nome do arquivo, em vez de
  descartada em silêncio. Suíte do back-end: 179 testes passando.
- [x] `npm audit fix` aplicado ao grupo 1. Corrigidos `nanoid`, `postcss` e
  `@babel/core`; só o `package-lock.json` mudou, `package.json` intacto —
  nenhuma mudança incompatível. Verificação: `npm run build` concluído (bundle
  inicial 341 kB, inalterado), servidor de desenvolvimento reiniciado sem erro e
  aplicação carregando com o console limpo.
- [ ] **Dívida aceita até depois da entrega:** restam 4 vulnerabilidades, todas
  exigindo salto de major — `vite`/`esbuild` (cadeia de build, exigiria Vite 8) e
  `react-router`/`react-router-dom` (exigiria a v7, e a falha não é alcançável
  conforme a análise acima).

## Resultado consolidado

| Ferramenta | Antes | Depois |
|---|---|---|
| bandit | 0 Medium/High, 18 Low (falso positivo) | idem |
| pip-audit | 0 | 0 |
| npm audit | 8 (3 high, 4 moderate, 1 low) | 4 (1 high, 3 moderate), nenhuma alcançável em produção |

---

# Remedição — 08/09/2026

As três ferramentas foram executadas de novo, por dois motivos. Primeiro, as
versões das dependências foram fixadas nesta data (regra SEC-19), o que muda o
que `pip-audit` e `npm audit` têm a dizer. Segundo, `bandit` e `pip-audit`
estavam declarados em `requirements.txt` mas **nunca haviam sido instalados na
imagem de desenvolvimento** — ela foi construída antes de a B12 acrescentá-los e
não foi reconstruída desde então. A execução de agora foi feita numa imagem
limpa, construída a partir do arquivo já fixado.

## bandit — 17 achados baixos, nenhum médio ou alto

| | 25/08/2026 | 08/09/2026 |
|---|---|---|
| Linhas analisadas | 6.436 | 7.684 |
| High | 0 | 0 |
| Medium | 0 | 0 |
| Low | 18 | **17** |

**A tabela de resultado consolidado da B12 registra "idem" na linha do bandit, e
está errada.** A queda de 18 para 17 é exatamente a correção que aquela mesma
seção lista como aplicada: o `try/except/pass` de `integrations/gemini.py` virou
`logger.warning`, e o achado B110 deixou de existir. O documento corrigiu o
defeito e não atualizou o número.

Os 17 restantes foram verificados um a um no código desta data, e não herdados
da classificação anterior. Todos são falso positivo:

| Regra | Nº | Onde | Por que não é achado |
|---|---|---|---|
| B105 | 5 | `config.py:150,153,155,168,170` | Literais `test-*` da classe `TestConfig`, fixos de propósito para que a suíte não dependa do `.env` da máquina. Nenhum casa prefixo de credencial real. Exceção registrada no próprio arquivo. |
| B105 | 4 | `google_oauth.py:19`, `microsoft_oauth.py:19`, `tiktok.py:30`, `youtube.py:29` | Constantes `TOKEN_URL` com o endereço público e documentado do endpoint de token de cada provedor. O detector reage ao nome da constante. |
| B105/B106 | 5 | `jwt_utils.py:33,55,88,94,95` | As cadeias `"access"`, `"refresh"` e `"Bearer"` usadas como **tipo** de token, e o nome de uma chave de configuração. Nenhuma é valor de segredo. |
| B311 | 3 | `sync_metrics.py:25`, `seed_data.py:173`, `integration_service.py:338` | `random.Random()` para gerar dado sintético — o seed, a simulação de sincronização e o job de métricas. |

A classificação dos três B311 depende de uma afirmação que foi verificada e não
presumida: **nenhum valor que precisa ser imprevisível usa `random`.** O `state`
do OAuth usa `secrets.token_urlsafe(32)` (`auth_service.py:38`), os
identificadores usam `uuid.uuid4`, e os tokens das APIs sociais em repouso usam
Fernet (`utils/crypto.py`).

## pip-audit — nenhuma vulnerabilidade conhecida

`No known vulnerabilities found`, sobre as 27 dependências agora fixadas em
`==`.

## npm audit — o que é embarcado e o que não é

A B12 argumentou em prosa que a maior parte das vulnerabilidades do front está
na cadeia de compilação e não no que chega ao navegador. Esse argumento agora é
medido, e não apenas afirmado: `npm audit --omit=dev` responde exatamente essa
pergunta.

| Recorte | Crítica | Alta | Moderada | Baixa | Total |
|---|---|---|---|---|---|
| Com dependências de desenvolvimento | 0 | 2 | 3 | 1 | 6 |
| **Apenas o que é embarcado** (`--omit=dev`) | **0** | **0** | **2** | 0 | **2** |

As duas embarcadas são `react-router` e `react-router-dom` — o mesmo open
redirect analisado na B12, cuja alcançabilidade foi descartada ponto a ponto e
cuja correção exige salto para a v7. A dívida segue aceita, pelos mesmos
motivos.

As quatro restantes são de compilação: `vite` e `esbuild` (path traversal no
tratamento de `.map` e o servidor de desenvolvimento aceitando requisições
cross-origin), `browserslist` (crescimento de memória sem limite) e
`postcss-selector-parser` (negação de serviço). Nenhuma sobrevive ao `build`: o
que vai para o navegador é o pacote estático que essas ferramentas produzem.

O total com dependências de desenvolvimento subiu de 4 para 6 desde 25/08 —
`browserslist` e `postcss-selector-parser` são novas. Nenhuma das duas é
embarcada.

## Resultado consolidado — 08/09/2026

| Ferramenta | Resultado | Ação |
|---|---|---|
| bandit | 0 alta, 0 média, 17 baixas, todas verificadas como falso positivo | nenhuma |
| pip-audit | 0 | nenhuma |
| npm audit (embarcado) | 0 crítica, 0 alta, 2 moderadas, nenhuma alcançável | dívida aceita, ver B12 |
| npm audit (com desenvolvimento) | 2 altas, 3 moderadas, 1 baixa, nenhuma embarcada | dívida aceita |
