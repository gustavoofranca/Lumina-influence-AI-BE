# B12 — Robustez da geração de PDF

- **Data:** 2026-08-26
- **Motivo:** a banca apontou "PDFs quebrados" na apresentação anterior. O
  objetivo aqui é exercitar a geração em cenários adversos e registrar o que
  aguenta e o que não aguenta.

## Ambiente e método

Onze cenários rodaram o caminho real de produção
(`build_report_context` → template → `xhtml2pdf`) numa instância isolada
apontada ao PostgreSQL local. Cada PDF gerado foi verificado três vezes:

1. **bytes** — começa com `%PDF` e tem tamanho plausível
2. **texto** — extraído com `pdftotext` e comparado com o esperado
3. **visual** — páginas críticas rasterizadas com `pdftoppm` e inspecionadas

O terceiro passo não é zelo excessivo: a extração de texto reporta
`Preparado pa ra` e `Orçament o`, com espaço no meio da palavra, em toda label
com `letter-spacing`. Na imagem renderizada as duas aparecem corretas — é
artefato do extrator, não defeito do PDF. Sem olhar a página, isso teria virado
um bug inexistente no relatório.

Os relatórios criados foram apagados do banco e do disco ao final.

## Resultado

| Cenário | Resultado | Páginas |
|---|---|---|
| Acentuação pesada (`ç ã õ é ü ñ`, travessão, aspas curvas) | ok | 6 |
| Título no limite do schema (200 caracteres) | ok | 6 |
| Glifos especiais (`▲ ✓ → € ½ ≤ ≥ • ®`) | ok | 6 |
| Emoji no título | ok, com ressalva | 6 |
| Período sem nenhum post | ok, **com problema de conteúdo** | 6 |
| Período de um único dia | ok | 6 |
| Período de dois anos | ok | 6 |
| Nenhuma seção selecionada | ok | 1 |
| Uma única seção | ok | 2 |
| Título vazio | ok | 6 |
| `period_end` anterior a `period_start` | recusado com `ValidationError` | — |

**Nenhum cenário produziu PDF corrompido, truncado ou ilegível.** A tabela de
benchmarking, a parte mais densa do documento, renderiza alinhada e sem estouro
de coluna. O template não usa `<img>`, então o modo de falha "imagem ausente"
não existe neste gerador.

## Achado 1 — ausência de dado é apresentada como desempenho zero

O relatório de um período sem posts é gerado sem erro, mas afirma:

> Esta auditoria cobre 4 criadores da campanha NovaTech Pro. Em média, **0.0%**
> do alcance foi orgânico e o índice de sentimento ficou em **0.0%**. Alcance
> total auditado: **0** em **0** posts.

Os cartões de KPI repetem `0` e `0.0%`, e a tabela de benchmarking sai com
cabeçalho e nenhuma linha.

O problema não é técnico, é de leitura: `0.0% de alcance orgânico` afirma uma
medição — que a campanha teve desempenho péssimo — quando o correto seria
declarar que não há o que medir no período. Um relatório entregue à marca
contratante nessas condições sustenta uma conclusão falsa sobre o criador.

Isso contradiz uma decisão já tomada no próprio projeto. A
[ADR-002](../adr/0002-kpis-financeiros-como-proxies.md) estabelece, para ROI e
CAC, que "sem custo registrado, os dois devolvem `null` em vez de zero: a
interface mostra ausência de dado, não desempenho nulo". O mesmo princípio não
foi aplicado ao PDF.

**Corrigido.** O contexto do relatório passou a carregar `summary.has_data`
(verdadeiro quando há post no período) e cada KPI passou a declarar
`depends_on_posts`. Com isso:

- o sumário, sem dado, declara a ausência em vez de afirmar percentuais;
- os três KPIs medidos saem como `—`; a contagem de criadores continua sendo
  exibida, porque é fato do elenco da campanha e não medição do período;
- as tabelas de trajetória e de benchmarking trazem linha de estado vazio no
  lugar do cabeçalho solto e das linhas de zero.

Cinco testes cobrem o comportamento nos dois sentidos — com e sem post no
período —, e o relatório com dados foi conferido para garantir que os números
continuam saindo iguais.

**Também corrigido:** a seção "Diagnóstico de IA" e as "Recomendações"
continuavam sendo exibidas num período sem posts, porque agregam as análises do
criador sem filtrar por janela. Um relatório que acabou de declarar não ter dado
no período não pode, três páginas depois, diagnosticar esse mesmo período. As
duas seções passam a trazer estado vazio, coerentes com o resto do documento. O
relatório é period-scoped: é a capa que promete um intervalo.

## Achado 2 — emoji vira quadrado preto

Emoji no título renderiza como `■`. A fonte embarcada pelo `xhtml2pdf` não tem
esses glifos, e não há fallback. Nenhum outro símbolo testado falhou — apenas
emoji.

Severidade baixa: exige que alguém digite emoji no título do relatório. Mas é
plausível, já que o título é campo livre preenchido pela agência.

**Corrigido.** Embarcar uma fonte com cobertura de emoji pesaria em todo PDF
gerado, para atender um caso raro. O caractere passa a ser removido antes da
renderização — mas **nunca em silêncio**: `strip_unsupported_glyphs` registra em
log um aviso com o nome Unicode de cada caractere retirado, para o problema não
se esconder de quem gerou o documento. Acentuação e símbolos tipográficos, que
têm glifo, seguem intocados — há teste para os dois casos.

## Observação de método

A primeira execução usou nomes de seção inventados (`summary`, `benchmarking`,
`sentiment`) e gerou PDFs de duas páginas em que faltavam as seções principais —
o que parecia um bug grave de renderização. As chaves reais são `kpis`,
`growth`, `benchmark`, `diagnostic` e `recommendations`.

Vale registrar por que o engano passou: `ReportCreateIn` valida as chaves e
recusa seção inválida, mas `generate_report` filtra silenciosamente com
`[s for s in sections if s in SECTION_KEYS]`. Quem chama o service direto — um
job futuro, um comando de CLI — recebe um PDF sem as seções pedidas e nenhum
aviso. O mesmo vale para o título: o comprimento é limitado no schema, e uma
chamada direta ao service com título acima de 200 caracteres estoura em
`DataError` cru do banco, não em erro de validação.

Nenhum dos dois é alcançável pela API hoje. Ficam registrados porque a proteção
mora inteira na borda: qualquer novo caminho que não passe pelo schema perde as
duas garantias de uma vez.
