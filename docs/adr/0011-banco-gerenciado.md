# ADR-011 — Banco de dados gerenciado, com o contêiner local como contingência

- **Status:** aceito
- **Data:** 2026-09-08 — registro retroativo de decisão tomada durante o projeto

## Contexto

O sistema é desenvolvido em duas máquinas diferentes e precisa ser apresentado
numa terceira, que não é a de desenvolvimento. Cada instância local de banco é
mais uma cópia a instalar, migrar e povoar — e mais uma oportunidade de a
demonstração rodar contra dados diferentes dos que foram testados.

## Alternativas consideradas

**Instância local em contêiner.** Já existe no `docker-compose.yml` e não
depende de rede. Em troca, cada máquina tem o seu próprio estado: uma migração
aplicada num lugar e não no outro produz divergência silenciosa, e a máquina da
apresentação vira mais um ambiente a preparar.

**Instância gerenciada.** Um único banco para todas as máquinas. Elimina a
instalação e a divergência de estado. Em troca, exige rede e coloca os dados em
infraestrutura de terceiro.

## Decisão

Banco gerenciado no Supabase, mantendo **PostgreSQL** como motor — a decisão é
sobre onde a instância roda, não sobre qual banco é. O contêiner
`lumina-postgres` do `docker-compose.yml` permanece no repositório como
contingência para trabalho sem rede.

O endereço vem de `DATABASE_URL`, variável de ambiente, e nunca do código. Foi o
que permitiu trocar de instância sem alterar uma linha.

## Consequências

- Nenhuma instalação manual de banco. As duas máquinas de desenvolvimento e a
  da apresentação enxergam o mesmo estado, com as mesmas migrações aplicadas.
- **A aplicação passa a depender de rede para subir.** Sem conexão, o
  contêiner local é a saída, e o custo de usá-lo é ter que migrar e semear.
- **Os dados residem em infraestrutura de terceiro.** É isso que torna a
  cifragem dos tokens das APIs sociais em repouso não opcional: eles são
  gravados cifrados com Fernet, e a chave (`FERNET_KEY`) vive fora do provedor,
  em variável de ambiente. Quem tiver acesso ao banco não tem acesso aos
  tokens.
- Há duas instâncias de Postgres possíveis, e confundir uma com a outra já
  custou tempo de diagnóstico. Ao investigar dado ausente, a primeira pergunta
  é contra qual banco a aplicação está falando.
- A latência de cada consulta deixa de ser desprezível. Reforça a atenção a
  consultas N+1, que é justamente a verificação (BE-02) que a auditoria de
  08/09/2026 deixou pendente.
