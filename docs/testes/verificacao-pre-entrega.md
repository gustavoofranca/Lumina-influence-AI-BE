# Bateria de verificação pré-entrega

Sete verificações que rodam sobre a interface em funcionamento, não sobre o
código. Existem porque cada uma delas **já achou defeito que build, teste
unitário e revisão de olho não pegaram** — a coluna "o que achou" registra o
caso real que justificou incluir a verificação.

Última execução: **28 de agosto de 2026**, sobre 22 rotas do app, as 4 abas do
criador e as 6 seções de configurações, nos dois temas e nos dois idiomas.

## Resultado das duas últimas execuções

| # | Verificação | O que achou historicamente | 27/08 | 28/08 |
|---|---|---|---|---|
| 1 | Tela que não renderiza | `/app/configuracoes/equipe` **em branco** — `refetch` fora de escopo derrubava também Plano e Preferências | 1 defeito, corrigido | 0 em 22 rotas |
| 2 | Contraste WCAG AA | `text-muted` reprovando por 0,05 no tema claro | 0 falhas | 0 falhas |
| 3 | Vazamento de largura em 390px | 4 telas estourando a viewport por falta de `min-w-0` | 0 estouros | 0 em 13 rotas |
| 4 | Botão sem ação atrás | 7 botões mortos, entre eles "Gerar Relatório" e "Abrir auditoria" | 0 | 0 (12 achados, todos na página de showcase) |
| 5 | Texto fora do i18n | "Entrar com Google" em português na tela em inglês; idioma que não persistia | 0 | **2 defeitos, corrigidos** |
| 6 | Teclado e foco | modal que prometia confinar o foco e não confinava; abas com `role="tab"` sem navegação por setas | controles do header aprovados | **rodada inteira: 4 defeitos, corrigidos** |
| 7 | Erro de carregamento lido como ausência | banner de erro com a tabela dizendo "nenhum criador" logo abaixo | — | **4 telas, corrigidas** |

### Os dois achados de 28/08

Ambos na varredura estática do item 5, e ambos do mesmo tipo: rótulo escrito
direto no JSX, sem passar por `t()`.

- **`HistoricoTab.jsx`** — o selo da análise mais recente saía como `Latest`,
  fixo em inglês, na aba Histórico do criador. Agora é
  `influenciador.history.latest` ("Mais recente" / "Latest").
- **`VideoAuditCard.jsx`** — o marcador `AI SCAN` da miniatura do reel estava
  fora do i18n, enquanto todos os rótulos irmãos de identidade visual
  ("DEEP ANALYSIS", "BRAND COHERENCE") já viviam nos dois locales com o mesmo
  valor. Agora é `influenciador.videoAudit.aiScan`, passado como prop ao
  sub-componente — o mesmo caminho que `duration` já usava.

Nenhum dos dois aparecia na varredura dinâmica: o primeiro porque "Latest" é
inglês numa tela que estava em inglês, o segundo porque o termo é idêntico nos
dois idiomas. **A varredura estática e a dinâmica não se substituem.**

### O achado do item 7, em 28/08

A verificação nova desta rodada, tirada da lista de "defeitos que se repetem e
valem procurar por nome". O método: percorrer as chamadas do `useApi`
procurando quem descarta o `error` da tupla, e confirmar cada suspeita
interceptando `window.fetch` no navegador para rejeitar só aquele endpoint.

Sete chamadas descartavam o erro. Com a API fora do ar, quatro telas passavam a
**afirmar fatos sobre o dado que ninguém mediu**:

| Tela | O que dizia com a API em erro |
|---|---|
| Criador → Histórico | "Nenhuma análise no histórico deste criador" — o criador tinha sete |
| Criador → Posts | "Nenhum post analisado para este criador" |
| Criador → Diagnóstico IA | "Indicadores indisponíveis — rode uma análise", mandando gastar cota do Gemini para resolver falha de rede |
| Campanha e assistente de relatório | campanha sem participante; no assistente, "nenhum influenciador vinculado" ao lado da badge "3 criadores" |

É a família do zero versus nulo da ADR-003, aplicada a recurso: **ausência de
resposta apresentada como ausência de dado.** Corrigido em `7f00fcb` (FE), com
o banner de erro **substituindo** o conteúdo que falhou — estado vazio embaixo
de banner de erro é a mesma afirmação falsa, só que acompanhada.

O filtro de campanhas do dashboard ficou de fora de propósito: falha ali deixa
o seletor sem opção, o que não afirma nada sobre o dado.

**Detalhe de método:** o `Skeleton` de carregamento não tem texto nenhum, então
medir "0 caractere" numa área em carregamento parece tela quebrada. No passo 2
do assistente de relatório a lista só aparece depois de ~5 s contra o Supabase.
Espere o dado antes de concluir qualquer coisa.

### A verificação 6 rodada por inteiro (28/08)

Era a única das sete que nunca tinha sido feita além dos controles do cabeçalho.
Método: percorrer todo elemento focável de cada tela medindo quatro coisas —
nome acessível, alcance por foco, anel de foco visível e alvo de toque de 24px
(WCAG 2.5.8).

**Resultado:** nome acessível e anel de foco passaram em tudo, no app e na
landing. Os quatro defeitos foram:

| Defeito | Consequência |
|---|---|
| `Modal` com `aria-modal="true"` sem confinar o foco | O Tab passeava pela página atrás do overlay: quatro formulários inalcançáveis por teclado |
| `Tabs` com `role="tab"` sem setas nem foco itinerante | O papel promete navegação por setas; o leitor anuncia "use as setas" e elas não faziam nada |
| `role="button"` no `<tr>` da tabela | Apagava a semântica de linha: sumia o "linha 3 de 12" e a leitura do cabeçalho junto da célula |
| 8 alvos abaixo de 24px na landing, 2 no design system | Toque impreciso em tela pequena |

Os dois primeiros ganharam teste ponta a ponta próprio, porque revisão de olho
não vê foco.

**Armadilha de medição:** âncora inline envolvendo botão mede a altura da linha,
não a do botão. "Nova Campanha" aparecia como alvo de 20px e o alvo real é 40px.

### Três pontos cegos das próprias verificações, achados em 28/08

Uma varredura estática de código, feita em paralelo, achou defeito que as sete
verificações não pegavam **por limite de método** — e vale mais registrar o
limite que o defeito:

1. **Contraste não enxerga SVG.** A verificação 2 percorre nós de texto lendo
   `color`; texto de SVG usa `fill`. Os 10 rótulos de eixo dos gráficos saíam a
   **2,4:1** no tema claro e passaram limpos em duas execuções. Ao medir
   contraste, percorra também `svg text`.
2. **Nada sem texto é medido.** O `Skeleton` usava cinza fixo e, no tema claro,
   toda tela em carregamento virava uma grade de retângulos escuros. É
   `aria-hidden` e não tem texto, então nenhuma das sete o alcançava. O que pega
   é **capturar a tela no meio do carregamento**, segurando a resposta da API.
3. **A varredura de i18n só olha JSX.** Texto dentro de handler
   (`setToast({ message: 'Download iniciado' })`) não aparece entre `>texto<`
   nem em atributo, e sobreviveu a duas auditorias de idioma.

Os dois scripts do item 4 e da parte estática do item 5 ficaram versionados em
[`scripts/`](scripts/) — rodar é `python3 scripts/botao_morto.py <caminho>/src`
e `python3 scripts/texto_fora_do_i18n.py <caminho>/src`, apontando para o
front-end.

## Como rodar cada uma

Todas rodam no navegador, com a stack de pé e um usuário autenticado.

### 1. Tela que não renderiza

A mais importante, e a que quase não se faz. Uma tela quebrada **passa em
silêncio por todas as outras verificações**, porque contraste, i18n e botão
morto leem um DOM que não existe.

Instale um coletor antes de navegar e percorra as rotas medindo o texto
renderizado:

```js
window.__erros = [];
addEventListener('error', e => __erros.push([location.pathname, e.message]));
const orig = console.error;
console.error = (...a) => { __erros.push([location.pathname, a.join(' ')]); orig(...a); };
// para cada rota: navegar, esperar >= 2s, medir
document.querySelector('main').innerText.trim().length
```

Tela viva tem centenas de caracteres; quebrada tem zero. **Espere pelo menos
2 segundos por rota** — a tela do criador faz quatro requisições e mede zero em
1,5 s, o que gera falso positivo garantido.

**Não meça dentro de um `<iframe>`** para poupar navegações: em 28/08 a mesma
rota `/app/influenciadores` mediu 0 caractere no iframe e 839 na aba real. Um
atalho de método que inventa tela quebrada é pior que a varredura manual que
ele substitui.

### 2. Contraste

Percorra os nós de texto, suba a árvore até achar fundo opaco (alpha > 0,85),
calcule a razão e compare com 4,5 (ou 3,0 para ≥24px, ou ≥18,66px em negrito).
Ignore `color: rgba(0,0,0,0)` — é texto com gradiente, e logotipo é isento.
Descarte também o que está sobre miniatura escura translúcida, senão o selo
branco sobre imagem aparece como falha.

**Troque de tema pelo botão da interface**, nunca por script: o efeito do React
reaplica o estado por cima e a medição sai contaminada.

O selo de duração sobre a miniatura do reel (`00:42`, branco sobre
`neutral-950/70`) reaparece como falha a cada execução no tema claro: o fundo
translúcido não passa do corte de 0,85 e a subida na árvore acaba no cartão
claro. É o falso positivo previsto acima, não defeito.

### 3. Vazamento de largura

Emule 390px e meça **`window.innerWidth`**, não `scrollWidth`: quando o conteúdo
não cabe, o navegador expande a viewport de layout, e aí "tudo cabe" pela
medida errada. Se `innerWidth > 392`, alguma coisa estourou.

### 4. Botão sem ação

Duas varreduras, porque o produto usa os dois: `<button` nativo e o `<Button>`
do design system. Descarte os envoltos em `<Link>`/`<a>` e os `disabled` com
aviso ao lado. A tag do componente é **multilinha e contém chaves**, então casar
`[^>]*>` quebra em `onClick={() => …}` — percorra contando `{`/`}` até o `>` de
profundidade zero.

### 5. Texto fora do i18n

Estático: literal entre `>texto<` e nos atributos que o usuário lê
(`placeholder`, `title`, `aria-label`, `alt`, `label`).

Dinâmico: rodar a interface em um idioma e procurar o outro no DOM, com lista de
exceções para os termos de identidade visual ("Growth Trajectory", "Network
Resonance") e para **conteúdo de dado** — nome de criador, legenda de post e
texto gerado pelo modelo não são interface.

E comparar os dois arquivos de tradução por chave: nenhuma pode faltar de um
lado, e valores idênticos nos dois merecem uma olhada.

### 6. Teclado e foco

Para cada controle novo: tem nome acessível que descreve a **ação**, é alcançável
por Tab, mostra foco visível, tem alvo de toque de pelo menos 24px e responde ao
Enter.

## O que esta bateria não cobre

- **Fluxo com efeito real**: conectar conta social, gerar PDF e rodar análise
  passam por serviços externos e estão verificados em
  [`integracao-social.md`](integracao-social.md) e
  [`robustez-pdf.md`](robustez-pdf.md).
- **Carga e concorrência**: [`carga.md`](carga.md).
- **Regressão de regra de negócio**: é o papel da suíte do back-end, com 286
  testes.
