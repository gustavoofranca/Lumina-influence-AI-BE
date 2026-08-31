# Testes ponta a ponta da interface

Executado pela primeira vez em 31 de agosto de 2026. Fecha a etapa 2 do plano
de robustez: até aqui, **os 317 testes da suíte eram todos do back-end** e o
front não tinha ferramenta de teste nenhuma.

- **Ferramenta:** Playwright, 32 testes, 2,7 min por execução completa.
- **Onde:** `Lumina-Influence-AI-FE/e2e/`, com `package.json` próprio.
- **Como rodar:** `cd Lumina-Influence-AI-FE/e2e && npm install && npm test`,
  com a stack de pé.

## Por que o front precisava disso

A lacuna não era teórica. Em 27/08 a tela `/app/configuracoes/equipe` ficava
**totalmente em branco** — `refetch is not defined` dentro de um modal — e
`npm run build` passava, porque o bundler resolve identificador desconhecido
como global e só quebra em tempo de execução. Quem achou foi varredura manual.
O primeiro arquivo da suíte automatiza exatamente essa varredura.

## O que cada arquivo trava

| Arquivo | Testes | O que trava |
|---|---|---|
| `rotas.spec.js` | 18 | toda rota renderiza com texto em `main` e console limpo, incluindo as de detalhe com id real |
| `login.spec.js` | 3 | entrada pelo atalho de desenvolvimento, rota protegida sem sessão, e a ADR-001 — sessão sobrevive ao F5, não à aba nova |
| `estado-de-erro.spec.js` | 3 | falha de carregamento aparece como erro com "tentar de novo", **nunca** como "nenhuma análise no histórico" ou campanha sem participante |
| `conta-social.spec.js` | 2 | o estado "conectada" vem do campo `connected` do payload, não da existência do registro |
| `relatorio.spec.js` | 2 | assistente do zero à pré-visualização, e a validação que barra o avanço sem campanha escolhida |
| `tema-e-idioma.spec.js` | 2 | as duas preferências sobrevivem a recarregar e a navegar por URL |
| `modal.spec.js` | 1 | o modal leva o foco para dentro, prende o Tab e devolve ao gatilho ao fechar |
| `teclado.spec.js` | 1 | as abas andam por setas, Home e End, e ocupam uma só parada de tabulação |

Os dois últimos travam o que revisão de olho não vê: foco. Os três primeiros
travam defeitos que **já aconteceram**: a tela em branco, o
estado de erro lido como ausência (corrigido em 31/08) e a conta social cujo
"Desconectar" devolvia 200 sem mudar a tela.

## Decisões de ambiente

**Usa o Chrome já instalado** (`channel: 'chrome'`), em vez dos navegadores do
Playwright — são ~200 MB por navegador, e o que interessa é o mesmo motor em que
o produto é demonstrado.

**Fica fora do `package.json` do front.** O `node_modules` da raiz do repositório
é volume anônimo do container e pertence ao root; instalar ali pelo host falha
com `EACCES`. A suíte tem workspace próprio, o que também mantém a dependência
de teste fora da árvore do produto.

**Um processo só** (`workers: 1`): a API roda em servidor de desenvolvimento de
processo único e o banco é compartilhado. Paralelizar mediria fila.

**Não suja o banco de demonstração:** nenhum teste exporta PDF nem cria campanha.
O assistente de relatório para na pré-visualização.

## Três armadilhas que custaram tempo

1. **Medir logo após o `goto`** lê o DOM antes do primeiro render do React:
   `/cadastro` e a rota 404 acusaram "tela em branco" na primeira execução, com
   zero caractere, e estavam íntegras. Todo teste de renderização passou a usar
   `expect.poll`.
2. **A aba do produto é `role="tab"`, não `button`.** Procurar por `button`
   espera até o timeout — o snapshot de acessibilidade do Playwright é o que
   mostra isso.
3. **O glob de interceptação precisa tolerar a query.** `**/influencers/<id>`
   não casa com `/influencers/<id>?enriched=true`: a rota não era interceptada e
   o teste passava a medir o payload real, dando falso verde.
