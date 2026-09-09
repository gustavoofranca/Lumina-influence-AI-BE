# Autorização — verificação de SEC-03

- **Data:** 2026-09-09
- **Escopo:** as 62 rotas da API e o uso de papel na interface
- **Método:** varredura por AST dos decoradores de cada rota, leitura do corpo
  das que não os têm, e busca por renderização condicional a papel no front

A auditoria de 08/09 declarou esta regra **não verificada**: constatou que
`@require_role` existe e é aplicado, mas conferir rota a rota contra a interface
ficou fora do escopo daquela rodada.

## Lado servidor — conforme

Das 62 rotas, **27 mudam estado**. O resultado bruto da varredura apontou seis
candidatas, e as seis foram lidas uma a uma:

| Rota | O que a varredura viu | O que o código faz |
|---|---|---|
| `POST /auth/dev-login` | sem autenticação | Atalho de demonstração. `DEV_LOGIN_ENABLED = False` em `StagingConfig` **e** em `ProdConfig` — a rota responde 403 fora de desenvolvimento. |
| `POST /auth/refresh` | sem papel | Correto: renovar sessão vale para qualquer autenticado, e `require_refresh` exige que o token seja do tipo certo. |
| `POST /auth/logout` | sem papel | Correto pelo mesmo motivo. |
| `DELETE /users/me` | sem papel | Correto: apagar a própria conta não depende de papel. |
| `PATCH /users/<id>` | sem papel | **Autoriza dentro da função**, e de forma mais fina do que um decorador permitiria: admin *ou* o próprio usuário podem editar, e só admin pode alterar `role`. Não é lacuna — é regra condicional. |
| `POST /reports/preview` | sem papel e sem limite | **Era lacuna.** Ver abaixo. |

Nenhuma rota que muda estado ficou sem autenticação, e nenhuma exigência de
papel está ausente onde deveria existir.

### A lacuna que apareceu: a prévia de relatório

`POST /reports` exige admin ou membro e é limitada a 10 requisições por minuto,
porque gerar relatório é caro. `POST /reports/preview` chama
`build_report_context` — **a mesma função que monta o PDF** — e só não grava o
arquivo. Estava sem limite algum e aberta a qualquer papel, inclusive
`viewer`.

Medido em 09/09: **10 consultas e mediana de 2.044 ms** por chamada, em cinco
execuções. A proteção guardava a porta cara e deixava a vizinha aberta.

**Corrigido:** a prévia ganhou orçamento próprio, `RATE_LIMIT_REPORT_PREVIEW`,
com 30 por minuto — mais folgado que o da geração porque ela é mais barata e é
interativa: o assistente a refaz quando se volta um passo e se muda seção ou
período. O número foi escolhido depois de conferir que o campo de título **não**
fica no passo da prévia, então ela não dispara a cada tecla digitada.

Os baldes são separados, então esgotar a prévia não impede gerar o relatório de
verdade. Há teste cobrindo as duas coisas, validado removendo o decorador — sem
ele, reprova.

## Lado interface — divergência declarada, não corrigida

A interface **não esconde ação por papel**, com uma exceção: `EquipeSection`
usa `usuarioAtual?.role === 'admin'` para gatear a gestão de membros. Em todo o
resto — criar campanha, gerar relatório, excluir criador, conectar conta — o
botão aparece para qualquer papel, e o servidor recusa com 403 no clique.

**Isto não é falha de segurança.** A regra que importa é que o servidor decida,
e ele decide: a interface não é a guarda, é a conveniência. Um cliente
malicioso não usa a interface de qualquer forma.

É defeito de experiência: oferecer uma ação que sempre falha. Corrigi-lo
significa levar a noção de papel a cerca de dez telas, o que é trabalho de
funcionalidade e não de correção — adiado, e registrado aqui para que o texto do
trabalho não afirme controle de acesso na interface, que não existe.

Vale notar que o usuário da demonstração é admin, então o caminho não aparece
numa apresentação.

## O que esta verificação não cobre

- Não foi exercitada uma sessão real de `viewer` contra as 22 telas. A
  conclusão sobre a interface vem da leitura do código: existe exatamente uma
  renderização condicional a papel em todo o `src/`.
- Escopo por agência é assunto de SEC-02 e está coberto em
  [`idor.md`](idor.md), com 26 endpoints e 6 listagens sondados.
