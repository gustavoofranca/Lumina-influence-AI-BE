# ADR-013 — Senha local e marco de sessão

- **Status:** aceito
- **Data:** 2026-10-15
- **Revisa:** ADR-001

## Contexto

Até aqui a autenticação era só OAuth, e a ADR-001 fixou JWT sem revogação: o
logout descarta os tokens no cliente, e o servidor não guarda sessão. Com login
por e-mail e senha aparece um caso que essa decisão não cobre — trocar a senha
porque alguém a descobriu. Se os tokens já emitidos continuarem valendo por
até 30 dias (o refresh), trocar a senha não expulsa o invasor.

## Decisão

1. **Senha local**, com hash Argon2id (`argon2-cffi`, parâmetros padrão) e a
   política do NIST SP 800-63B rev. 4 (spec de 15/10/2026, seção 6).
2. **Marco de sessão por usuário:** `users.sessoes_validas_desde`. Trocar ou
   redefinir a senha grava o instante (truncado no segundo), e
   `require_auth`/`require_refresh` recusam token com `iat` anterior
   (`401 token_revoked`). Não há tabela de sessões: o usuário já é lido do
   banco a cada requisição, e o marco é mais uma coluna dessa mesma leitura.
3. **CSRF não se aplica:** a API autentica por `Authorization: Bearer`, e não
   por cookie. Um site de terceiro não consegue fazer o navegador anexar o
   cabeçalho. O token continua em `sessionStorage` (ADR-001 revisada).

## Consequências

- Revogação é por usuário, não por sessão: trocar a senha encerra todas as
  sessões, inclusive as legítimas em outros aparelhos. A sessão que fez a troca
  recebe um par novo.
- Logout continua sem efeito no servidor (ADR-001).
- A granularidade é de um segundo: um token emitido no mesmo segundo da troca,
  antes dela, continua valendo. É uma janela que ninguém controla na prática.
- O ponto único `concluir_login` é onde o 2FA entra depois (spec, seção 8).
