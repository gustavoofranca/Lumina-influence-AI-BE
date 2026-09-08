# ADR-009 — UUID v4 como chave primária

- **Status:** aceito
- **Data:** 2026-09-08 — registro retroativo de decisão tomada no início do projeto

## Contexto

O identificador de todo recurso do sistema aparece na URL da API
(`GET /api/v1/influencers/{id}`) e, por consequência, na URL do front. Quem usa
o produto vê esses identificadores; quem tem uma conta de agência pode tentar
usar os das outras.

O sistema é multiagência: os dados de uma agência não podem ser alcançáveis por
outra. A autorização por escopo é o que garante isso, e o formato da chave é o
que define o que um atacante ganha ao tentar.

## Alternativas consideradas

**Inteiro sequencial.** O padrão do Postgres, compacto e ordenável. Duas
propriedades indesejadas vêm de graça com ele. A primeira é a enumeração:
`/influencers/1`, `/influencers/2`, `/influencers/3` é um laço de três linhas, e
qualquer falha de escopo vira vazamento do banco inteiro em vez de um registro.
A segunda é o vazamento de cardinalidade: o id 4.217 informa a qualquer cliente
quantos criadores o sistema tem, o que é informação de negócio que ninguém
decidiu publicar.

**UUID v4.** Aleatório, sem ordem e sem cardinalidade. Custa 16 bytes contra 4,
e o índice não fica agrupado por ordem de inserção.

**UUID v7.** Ordenável por tempo, o que devolve a localidade no índice. Não foi
adotado porque reintroduz, de forma atenuada, o vazamento que a decisão quer
eliminar: dois ids revelam qual registro é mais antigo.

## Decisão

UUID v4 como chave primária em todas as tabelas — as catorze do esquema, sem
exceção. Gerado no lado da aplicação, com `default=uuid.uuid4` no
`mapped_column`, e não por função do banco.

Gerar em Python é deliberado: o objeto tem id antes do `flush`, o que permite
montar grafos de objetos relacionados antes de qualquer ida ao banco, e o
comportamento é idêntico em Postgres e no SQLite dos testes.

## Consequências

- Enumerar recursos deixa de ser viável. Isso **não substitui** a verificação de
  escopo — a autorização continua sendo a defesa, e o `get_scoped_or_404` é
  quem a aplica. O UUID é a segunda camada: torna o palpite inútil.
- A chave é quatro vezes maior, e cada chave estrangeira paga o mesmo. Com o
  volume deste sistema, o custo é irrelevante.
- O índice primário não tem localidade temporal: inserções caem em posições
  espalhadas da árvore. Sentiria-se com escrita intensa e sustentada, que não é
  o perfil de uso.
- Não há ordenação implícita por id. Toda listagem ordena por coluna explícita,
  quase sempre `created_at` — o que é melhor de qualquer forma, porque a ordem
  passa a ser uma decisão visível no código.
- O identificador é opaco para quem lê. Um id em log ou em relatório de erro não
  diz de que registro se trata sem consulta ao banco — e é justamente essa
  propriedade que permite registrar o id no log no lugar do e-mail (ver o
  tratamento de SEC-15).
