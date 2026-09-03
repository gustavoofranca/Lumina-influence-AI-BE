# ADR-001 — Autenticação por JWT stateless, sem revogação no logout

- **Status:** aceito
- **Data:** 2026-08-25
- **Revisado em:** 2026-08-26 — armazenamento do token no cliente (ver
  "Revisão: sessionStorage", ao final)

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

O front-end guarda o access token em `sessionStorage` — nunca em
`localStorage` —, o que faz o fechamento da aba encerrar a sessão de fato.

## Consequências

- Um access token copiado antes do logout continua válido até expirar. O TTL
  curto é o que limita o dano; não há como encurtar essa janela sem estado.
- Não há "encerrar sessão em todos os dispositivos". Implementar isso exige a
  blocklist descartada acima — decisão a revisitar se o requisito aparecer.
- Trocar a senha não derruba sessões, porque não há sessão a derrubar. O login
  é OAuth, então não existe senha própria a trocar.
- A API escala horizontalmente sem store compartilhado de sessão.

## Revisão: sessionStorage (2026-08-26)

A decisão original mandava guardar o access token **apenas em memória**,
excluindo `localStorage` e `sessionStorage`. A consequência prática apareceu no
uso: **qualquer F5 desloga o usuário**, porque recarregar a página descarta a
memória do JavaScript.

A restrição era mais forte que a justificativa que a sustentava. O que a decisão
precisa garantir é que **fechar a aba encerre a sessão** — é isso que limita a
janela de um token que não pode ser revogado. `sessionStorage` entrega
exatamente essa propriedade: o conteúdo vive enquanto a aba viver e é descartado
quando ela fecha, sem sobreviver entre sessões do navegador. `localStorage`, sim,
quebraria a premissa, porque persiste indefinidamente.

**Decisão revisada:** o access token passa a ser guardado em `sessionStorage`.
`localStorage` continua vedado.

Consequências que mudam:

- Recarregar a página deixa de encerrar a sessão.
- O token fica legível por JavaScript da própria origem, como já ficava em
  memória — um XSS que execute na página tem acesso nos dois casos. O
  `sessionStorage` não piora esse cenário; o que o pioraria seria persistir
  entre sessões.
- Abas diferentes têm sessões independentes, porque `sessionStorage` é por aba.

O que não muda: o TTL curto do access token continua sendo o limite de exposição,
e o logout continua sendo responsabilidade do cliente.

## Segunda revisão: o refresh token entra na mesma gaveta (2026-09-03)

A revisão de agosto resolveu o F5 e deixou um buraco maior de pé: **o front
nunca guardava o refresh token.** O par vinha completo do login — no corpo da
resposta do `dev-login` e no fragmento do retorno OAuth — e o cliente lia só o
`access_token`, descartando o outro.

O efeito era o pior possível para uma demonstração. O access token vale 1 hora;
passada ela, a primeira requisição levava 401, o `onUnauthorized` limpava a
sessão e o usuário aparecia na tela de login no meio do que estava fazendo, sem
mensagem. A função `refresh()` existia em `services/auth.js`, ninguém a
importava, e do jeito que estava escrita não teria funcionado: mandava
`auth: false`, e `require_refresh` lê o token do cabeçalho `Authorization`.

**Decisão:** o refresh token passa a ser guardado em `sessionStorage`, ao lado
do access token, e um 401 numa requisição autenticada dispara uma tentativa de
renovação antes de derrubar a sessão.

O raciocínio é o mesmo da primeira revisão, e leva ao mesmo lugar. O que esta
ADR precisa garantir é que **fechar a aba encerre a sessão** — é isso que limita
a janela de um token que não pode ser revogado. Guardar um refresh token de 30
dias em `localStorage` quebraria a premissa de um jeito muito mais grave que o
access token quebraria, porque a janela deixaria de ser de uma hora e passaria a
ser de um mês, em disco. `sessionStorage` mantém a propriedade: o par inteiro
morre com a aba.

Consequências:

- A sessão dura até a aba fechar, e não mais uma hora.
- Uma renovação por vez. Quatro requisições que expiram juntas — o que a tela do
  criador faz ao abrir — pediriam quatro renovações, e as três últimas usariam
  um refresh token já trocado.
- Uma tentativa por requisição. Se o token novo também for recusado, a sessão
  cai, e é isso que se espera: insistir viraria laço.
- Falha de rede durante a renovação **não** derruba a sessão. Rede fora não é
  sessão inválida, e tratar as duas igual desconectaria o usuário no túnel.
- A superfície de um XSS cresce: quem executar na página passa a poder pegar
  também o refresh token, e com ele emitir pares novos até o fim dos 30 dias.
  Continua valendo o que a decisão original diz — sem estado no servidor, não há
  como revogar. Esta é a troca aceita, e é o argumento mais forte que existe
  para uma blocklist, se o requisito voltar.
