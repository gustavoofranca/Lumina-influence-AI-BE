# ADR-001 — Autenticação por JWT stateless, sem revogação no logout

- **Status:** aceito
- **Data:** 2026-08-25

## Contexto

A API é consumida por um SPA e precisa autenticar cada requisição sem manter
sessão no servidor. O produto é um monólito modular com uma única instância em
desenvolvimento, mas o desenho precisa suportar mais de um processo sem
introduzir estado compartilhado.

O ponto em disputa é o `POST /auth/logout`: um token assinado é válido até
expirar, e o servidor não guarda registro de quais foram emitidos. Encerrar
sessão de fato exigiria consultar uma lista de revogados a cada requisição.

## Alternativas consideradas

**Sessão no servidor (cookie + store).** Revogação imediata e simples de
raciocinar. Custa um store compartilhado (Redis ou tabela) consultado em toda
requisição autenticada, e amarra a API a estado de sessão — o oposto do que se
espera de uma API REST consumida por SPA e por jobs.

**Blocklist de tokens revogados.** Mantém o JWT e resolve o logout: cada
requisição verifica se o `jti` está na lista. Reintroduz a leitura por
requisição que o JWT existia para evitar, e exige expiração dos registros para
a lista não crescer sem limite.

**JWT stateless com TTL curto no access token.** Nenhuma leitura extra por
requisição. O logout é responsabilidade do cliente, que descarta os tokens; a
janela de exposição de um token vazado é limitada pelo TTL.

## Decisão

JWT stateless. O access token tem TTL curto e o refresh token, TTL longo.
`POST /auth/logout` responde `204` e não invalida nada no servidor — o cliente
descarta os dois tokens.

O front-end guarda o access token apenas em memória, nunca em `localStorage` ou
`sessionStorage`, o que faz o fechamento da aba encerrar a sessão de fato.

## Consequências

- Um access token copiado antes do logout continua válido até expirar. O TTL
  curto é o que limita o dano; não há como encurtar essa janela sem estado.
- Não há "encerrar sessão em todos os dispositivos". Implementar isso exige a
  blocklist descartada acima — decisão a revisitar se o requisito aparecer.
- Trocar a senha não derruba sessões, porque não há sessão a derrubar. O login
  é OAuth, então não existe senha própria a trocar.
- A API escala horizontalmente sem store compartilhado de sessão.
