# ADR-012 — O histórico publicado não é reescrito

- **Status:** aceito
- **Data:** 2026-09-08

## Contexto

A auditoria de 08/09/2026 verificou a regra GIT-01, que proíbe rastro de
ferramenta de assistência no repositório, e encontrou **uma única ocorrência**
em toda a história dos dois repositórios: o corpo do commit `32001ed`
("docs: corrige o README com o estado real do back-end", 26/08/2026) menciona um
arquivo `claude.md` ao listar o que estava errado no README.

A frase descreve um link quebrado apontando para um arquivo que o `.gitignore`
bloqueia. É relato de higiene de repositório, não afirmação sobre o processo de
desenvolvimento.

## Alternativas consideradas

**Reescrever a mensagem.** Um `rebase` interativo ou um `filter-branch` sobre um
commit de duas semanas atrás. Elimina a ocorrência.

**Manter e registrar.** A ocorrência permanece; a decisão fica documentada para
que a próxima auditoria não a reabra às cegas.

## Decisão

Manter a mensagem como está.

Reescrever o commit `32001ed` recalcula o hash de todos os commits posteriores.
Isso exige `git push --force` sobre um histórico já publicado, e o projeto é
desenvolvido em **duas máquinas**: a segunda continuaria com a linha antiga, e o
próximo `pull` de lá produziria divergência a resolver à mão, a poucos dias da
entrega.

O risco operacional é concreto e a mitigação é textual. Não compensa.

## Consequências

- A ocorrência de GIT-01 permanece no histórico, agora como decisão registrada
  em vez de achado pendente.
- A regra continua valendo integralmente daqui para a frente: nenhuma mensagem
  nova, comentário, README ou documento versionado menciona ferramenta de
  assistência.
- Fica registrada, junto, a resolução do conflito entre GIT-01 e GIT-02 que a
  mesma auditoria expôs: as entradas do `.gitignore` que bloqueiam artefatos
  dessas ferramentas **precisam** nomeá-las, e é a GIT-02 que as exige. Entrada
  de `.gitignore` é configuração de ferramenta, não prosa sobre o processo.
  GIT-01 aplica-se a texto em prosa.
