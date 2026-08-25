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
