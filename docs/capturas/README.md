# Capturas de tela — evidência visual do produto

Conjunto produzido para a escrita, com o sistema rodando contra o banco
gerenciado, uma conta de YouTube real conectada e a análise de IA executada
sobre conteúdo verdadeiro.

- **Primeira versão:** 27 de agosto de 2026
- **Regeração:** 1º de setembro de 2026 — o conjunto envelheceu em quatro dias.
  A landing foi refeita segundo o arquivo do Figma, o tema claro teve contraste
  corrigido em três famílias de componente, e quatro telas passaram a existir.
  Figura que mostra um produto que não existe mais é pior que figura nenhuma.

- **Ambiente:** front em `localhost:5173`, back em `localhost:5000`, banco no
  Supabase (`us-west-2`)
- **Estado:** tema escuro e português, exceto onde indicado
- **Largura:** 1440 px

As legendas abaixo estão escritas para ir direto ao documento, e cada uma diz o
que a figura **prova** — não apenas o que ela mostra.

| # | Arquivo | Legenda sugerida |
|---|---|---|
| 1 | [`01-landing.png`](01-landing.png) | Página pública do produto. A tese aparece na primeira dobra: o alcance orgânico separado do tráfego pago, e um alerta de bot-farm como amostra do diagnóstico. |
| 2 | [`02-login.png`](02-login.png) | Autenticação por OAuth Google. Não há senha própria no sistema — decisão registrada na ADR-001, que também define por que o token vive em `sessionStorage`. |
| 3 | [`03-dashboard.png`](03-dashboard.png) | Painel da agência. Os KPIs financeiros aparecem com travessão quando não há base de cálculo, em vez de zero: é a ADR-002 aplicada na tela. |
| 4 | [`04-influenciadores.png`](04-influenciadores.png) | Listagem de criadores com filtros por plataforma, status e período. |
| 5 | [`05-criador-visao-geral.png`](05-criador-visao-geral.png) | Aba Visão Geral do criador, com o card de contas conectadas. O YouTube aparece coletando; Instagram e TikTok, vinculados sem coleta ativa — a distinção que a etapa B8 tornou visível. |
| 6 | [`06-criador-diagnostico.png`](06-criador-diagnostico.png) | Diagnóstico de IA completo: heatmap de sentimento, integridade de audiência, confiança do modelo por dimensão, transcrição e recomendações priorizadas. |
| 7 | [`07-criador-posts.png`](07-criador-posts.png) | Posts auditados do criador, com risco de bot por publicação. |
| 8 | [`08-campanhas.png`](08-campanhas.png) | Gestão de campanhas, com orçamento e status por campanha. |
| 9 | [`09-campanha-benchmarking.png`](09-campanha-benchmarking.png) | Benchmarking entre criadores da mesma campanha e radar de performance — a comparação que sustenta a decisão de recontratar ou não. |
| 10 | [`10-diagnostico.png`](10-diagnostico.png) | Histórico de auditorias por criador, da mais recente para a mais antiga. |
| 11 | [`11-relatorio-wizard.png`](11-relatorio-wizard.png) | Montagem do relatório em quatro passos: campanha, período e criadores, seções e pré-visualização. |
| 12 | [`12-relatorio-preview.png`](12-relatorio-preview.png) | Pré-visualização em A4 antes da exportação. A tela renderiza o **mesmo contexto** que gera o PDF, então o que se confere aqui é o que se baixa. |
| 13 | [`13-configuracoes-integracoes.png`](13-configuracoes-integracoes.png) | Integrações disponíveis por plataforma. |
| 14 | [`14-tema-claro.png`](14-tema-claro.png) | O mesmo painel no tema claro. A paleta deriva da escura por uma regra única — o fundo do tema escuro vira a tinta —, e as duas passam em contraste AA, agora verificado por teste que mede também os rótulos em SVG. |
| 15 | [`15-privacidade.png`](15-privacidade.png) | Política de privacidade em URL pública, nos dois idiomas. É a primeira página que o revisor do App Review da Meta abre, e cada afirmação dela foi auditada contra o código. |
| 16 | [`16-exclusao-de-dados.png`](16-exclusao-de-dados.png) | Instruções de exclusão de dados. Os três caminhos descritos **existem na interface** — a primeira versão do texto prometia dois que não existiam. |
| 17 | [`17-exclusao-de-criador.png`](17-exclusao-de-criador.png) | Exclusão em cascata de um criador. A confirmação pede o nome digitado porque a ação não tem lixeira: é a diferença entre errar o botão e decidir apagar. |
| 18 | [`18-exclusao-de-conta.png`](18-exclusao-de-conta.png) | Exclusão da própria conta. A tela consulta a prévia e **conta** o que se perde — criadores, campanhas, relatórios, membros — antes de existir botão de confirmar, porque o último administrador leva a agência junto. |

## Como reproduzir

O conjunto inteiro é regerado por um roteiro versionado, e não por 14 navegações
repetidas na mão — foi assim que a figura 12 ficou quatro dias mais velha que as
outras na primeira tentativa: **a captura difícil é a que ninguém refaz.**

```
cd Lumina-Influence-AI-FE/e2e
CAPTURAS=1 npx playwright test capturas.spec.js
```

Fica desligado por padrão (`test.skip` sem a variável), porque capturar não
verifica nada e misturar isso com a suíte faria toda execução escrever em
`docs/`. As figuras 5 e 6 dependem de uma conta social conectada e de uma
análise executada; o caminho está em
[`../testes/integracao-social.md`](../testes/integracao-social.md).

O que **não** é dado real nestas telas está declarado na
[ADR-005](../adr/0005-alcance-organico-e-pago-vem-do-seed.md):
a divisão entre alcance orgânico e pago vem do seed, porque nenhuma das três
plataformas concede essa métrica sem programa comercial.
