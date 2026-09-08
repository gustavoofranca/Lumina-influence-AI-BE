# ADR-010 — Estratégia em três camadas funcionais

- **Status:** aceito
- **Data:** 2026-09-08 — registro retroativo de decisão tomada no início do projeto

## Contexto

O produto depende de dados que não são dele. Instagram, TikTok e YouTube só
liberam acesso pleno às suas APIs depois de aprovar a aplicação, e a aprovação
tem prazo que não está sob controle de quem desenvolve — o App Review da Meta é
o caso extremo, com exigência de vídeo de demonstração e política publicada.

Um trabalho com data de entrega marcada não pode ter o seu funcionamento
condicionado a uma resposta de terceiro que pode chegar depois da apresentação,
ou não chegar.

## Alternativas consideradas

**Esperar a aprovação.** Constrói-se contra a API real e a demonstração só
existe se a liberação vier a tempo. Todo o risco do projeto fica concentrado
numa decisão externa.

**Simular tudo.** Nada depende de terceiro e nada prova que a integração
funciona. O trabalho passa a ser sobre uma interface, não sobre um sistema.

**Camadas independentes.** Separar o que o sistema faz em níveis que funcionam
sozinhos, de modo que a ausência de um não impeça os outros.

## Decisão

Três camadas funcionais, cada uma completa por si:

**Camada 1 — dados semeados.** Banco povoado por fixtures realistas de
criadores, campanhas, posts, comentários e análises. Todos os endpoints, todas
as telas e todos os cálculos funcionam sobre eles. Esta camada não depende de
nada externo e é a que garante que o sistema é demonstrável em qualquer
cenário.

**Camada 2 — APIs sociais.** OAuth com Instagram, TikTok e YouTube. A
sincronização usa a API real quando há token válido para a conta e recorre à
simulação quando não há. A decisão é por conta, em tempo de execução, não por
configuração global.

**Camada 3 — IA real.** O Gemini analisa texto e vídeo e persiste o
diagnóstico. É a camada que não se simula, porque é o núcleo da proposta do
trabalho.

Os adaptadores em `integrations/` são o que torna isso possível: a camada de
serviços chama sempre a mesma interface, e a escolha entre chamada real e
simulação fica dentro do adaptador.

## Consequências

- O sistema é demonstrável integralmente sem nenhuma aprovação de terceiro.
- Uma aprovação que chegue depois não exige mudança de arquitetura: a conta
  ganha token e a camada 2 passa a usar a API real para ela.
- **A separação entre alcance orgânico e pago opera sobre dado semeado enquanto
  a aprovação não vier.** É requisito do trabalho e está implementado, mas a
  fonte é a camada 1, não a plataforma. A ADR-005 registra esse ponto em
  detalhe, e o texto do trabalho precisa dizê-lo com a mesma clareza — número
  que parece medido e não é seria o pior defeito possível numa ferramenta de
  auditoria.
- Cada camada precisa de teste próprio, e a fronteira entre elas precisa de
  teste que prove que a queda de uma não derruba a outra.
- Há custo de complexidade: dois caminhos de código por integração, ambos a
  manter.
