# Ações que a interface oferecia e não aconteciam

Frente de 1º de setembro de 2026, aberta por uma observação simples: *aceitar
uma recomendação da IA não fazia nada, e a decisão não era guardada.*

A varredura que se seguiu achou o mesmo padrão em mais três lugares — e os três
tinham o endpoint **pronto no back-end desde a B4 ou a B7**. Não faltava
sistema: faltava o caminho da tela até ele.

## O que havia

| O que a tela oferecia | O que acontecia | Desde quando o back-end sabia fazer |
|---|---|---|
| Aceitar/ignorar recomendação da IA | `useState` local — sumia ao recarregar | não existia; foi construído agora |
| — (não havia botão) | coleta só no agendador, de 6 em 6 horas | `POST /influencers/{id}/sync`, B7 |
| Status do criador no cabeçalho | somente leitura, vinha do seed | `PATCH /influencers/{id}`, B4 |
| — (não havia botão) | campanha não podia ser removida | `DELETE /campaigns/{id}`, B4 |

Vale separar os dois tipos. O primeiro é **mentira de interface**: a tela
mudava de aparência e afirmava que algo tinha acontecido. Os outros três são
**omissão**: a tela não prometia nada, mas deixava o usuário sem um caminho que
o sistema já tinha.

A mentira é o defeito grave, e é da mesma família que atravessa o projeto —
afirmar sobre o que não foi verificado, aqui na versão "afirmar que uma ação
aconteceu". As omissões são mais fáceis de perdoar e mais fáceis de não achar:
ninguém reclama de um botão que não existe.

## Como cada uma foi fechada

### A decisão sobre a recomendação

A recomendação **não tem id próprio**: ela vive dentro do JSON da análise, que
é imutável depois de gerada. A identidade estável do item é o par
`(análise, posição na lista)`, e é isso que a chave única de
`recommendation_decisions` fixa. O índice passou a sair no payload — antes o
front inventava `rec-N`, um identificador que não valia nada fora daquela tela,
e era exatamente por isso que a decisão não tinha onde ser gravada.

Duas escolhas de contrato que valem registro:

- **A decisão volta junto com a recomendação**, e não numa chamada separada.
  Sem isso a tela recarregada volta a oferecer "aceitar" para algo que a agência
  já aceitou.
- **Vem com quem decidiu e quando.** Uma auditoria em que ninguém responde pelo
  aceite não é auditoria. O FK do usuário é `SET NULL`: a decisão sobrevive à
  saída de quem a tomou, porque apagá-la reescreveria o histórico.

### Sincronizar as contas

O resumo é montado **conta a conta**. O back-end responde 200 mesmo quando uma
delas falha, com `status` próprio (`synced`, `simulated`, `not_connected`,
`token_revoked`, `rate_limited`), e um "pronto" único transformaria token
revogado em sucesso.

O modo simulado diz que é simulado: os números crescem sobre dado de exemplo,
sem coleta real. Chamar isso de sincronização seria a mentira mais fácil de
cometer nesta tela, e a mais coerente com tudo que o trabalho critica.

### O status do criador

Era o único julgamento humano que a tela **mostrava sem deixar ninguém
emitir**. O mapa de volta (visual → API) ficou ao lado do mapa de ida, no mesmo
arquivo: dois mapas em arquivos diferentes divergem.

### Excluir campanha

A confirmação declara o que **permanece**: posts e relatórios têm `SET NULL` e
sobrevivem desvinculados. Falar só do que se perde faz o usuário imaginar o
pior — e aqui o pior é falso.

## Três achados de método, todos vindos dos testes

**O SQLite dos testes escondeu um schema errado.** O tipo enum foi criado com
rótulos em minúscula, contra a convenção do resto do schema, e a suíte inteira
passou: o SQLite aceita qualquer texto na coluna. O `INSERT` só estourou em
Postgres, no primeiro clique real. Enum e constraint de banco precisam de
verificação contra o banco de verdade.

**Duas regiões vivas na mesma página.** A página do criador montava dois
`Toast`, e o leitor de tela passava a observar dois nós para o mesmo tipo de
anúncio. Quem achou foi a varredura de semântica, escrita horas antes; ela
ganhou a checagem correspondente.

**Cronômetro contra evento assíncrono, de novo.** Um teste de sincronização
passava sozinho e falhava na suíte inteira: o aviso some em 3,5 s e a asserção
por polling disputava com o auto-fechar. Esperar a **resposta** antes de olhar
o aviso põe os dois na mesma linha do tempo. É a terceira vez que a mesma
armadilha aparece neste projeto com uma roupa diferente.

## O que fica como pergunta

A varredura procurou ação que não acontece. Ela **não** procura dado exibido que
ninguém pode corrigir — nicho e bio do criador, por exemplo, aceitam `PATCH` e
não têm campo na tela. É uma omissão do mesmo tipo, e continua aberta.
