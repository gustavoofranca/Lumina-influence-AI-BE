# ADR-004 — Callback OAuth das redes sociais autentica pelo state, não pela sessão

- **Status:** aceito
- **Data:** 2026-08-26
- **Relacionada:** [ADR-001](0001-jwt-stateless-sem-revogacao.md), que define o
  JWT stateless usado tanto na sessão quanto no state.

## Contexto

Vincular a conta de rede social de um criador (etapa B8) é um OAuth de três
pernas: o front pede a URL de autorização, o navegador vai ao provedor, o
usuário consente, e o provedor **redireciona o navegador** de volta ao nosso
callback com `code` e `state`.

O callback estava declarado assim:

```python
@bp.get("/<platform>/callback")
@require_auth
def callback(platform):
    ...
    agency_id=current_agency_id(),   # vem do JWT
```

Um redirect do provedor é uma navegação de topo: o navegador não anexa header
`Authorization`. O endpoint devolvia 401 antes de executar qualquer linha, e o
critério de aprovação da B8 — "conta real vinculada" — era inalcançável.

Os 16 testes da etapa passavam porque o cliente de teste enviava o Bearer na
mão, coisa que navegador nenhum faz. O OpenAPI, por sua vez, já descrevia o
endpoint como redirect de navegador, sem exigência de segurança e com resposta
302: a especificação estava certa e a implementação é que tinha divergido.

## Alternativas consideradas

**Cookie de sessão para o callback.** Desenho clássico, mas o front roda em
`:5173` e a API em `:5000`; o `Set-Cookie` sairia numa requisição XHR
cross-origin, exigindo CORS com credenciais e mudança no cliente HTTP inteiro.
Custo alto para um fluxo que já carrega identidade assinada.

**Callback intermediário no front.** O provedor redirecionaria para o front, que
reenviaria `code` e `state` à API com Bearer. Funciona, mas coloca o `code` de
autorização na URL do navegador e no histórico, e duplica o fluxo que o login
já resolve de outro jeito no mesmo projeto.

**Autenticar pelo próprio `state`.** Escolhida. É o desenho que o callback de
login já usa neste repositório, e o `state` foi feito exatamente para isso.

## Decisão

O callback não exige Bearer. A identidade sai do `state`, que é um JWT assinado
com `JWT_SECRET` carregando `inf` (criador), `plat` (plataforma), `ag`
(agência), `exp` de 15 minutos e um `jti`.

Três garantias sustentam a troca:

1. **O state só é emitido autenticado.** `/connect` exige ADMIN ou MEMBER e
   resolve o criador pelo escopo de quem pediu — um usuário não consegue mintar
   state para criador de outra agência.
2. **O state é de uso único.** O `jti` passa a ser gasto em `oauth_states`, a
   mesma tabela que o login usa como registro de nonce. Sem isso, a remoção do
   `@require_auth` deixaria um state vazado reapresentável dentro dos 15
   minutos. Este é o passo que torna a decisão defensável, não um detalhe.
3. **O vínculo é reconferido no momento do callback.** O criador precisa
   pertencer à agência declarada no state **agora**, não só quando o fluxo
   começou.

Com sucesso e `AUTH_SUCCESS_REDIRECT` configurado, o callback redireciona o
navegador de volta à tela do criador. Sem destino configurado, devolve 201 com a
conta — é o que os testes exercitam.

## Consequências

- O endpoint sai da lista de rotas protegidas por Bearer. Quem auditar o
  projeto vai reparar; a resposta é o conjunto das três garantias acima, e o
  paralelo com o callback de login, que nunca exigiu Bearer pelo mesmo motivo.
- O uso único depende do enum `oauth_provider`, que só conhece `google` e
  `microsoft`. O YouTube cabe porque seu provedor OAuth é literalmente
  `accounts.google.com`. Instagram e TikTok exigiriam ampliar o enum — uma
  migration, adiada. Até lá, `consume_state_nonce` **falha fechado** para essas
  plataformas em vez de seguir sem garantia. Elas já não podem iniciar o fluxo
  hoje: sem credencial configurada, `build_auth_url` levanta
  `PlatformNotConfiguredError`.
- A tabela `oauth_states` passa a acumular uma linha por vínculo concluído. O
  job de limpeza que já remove states expirados cobre isso.
- Lição de método que vale registrar na escrita: **teste que fabrica um header
  que o cenário real não produz não prova o cenário real.** Os 16 testes da B8
  estavam verdes sobre um fluxo impossível.
