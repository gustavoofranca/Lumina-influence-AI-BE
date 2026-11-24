# ADR-014 — Segundo fator por app autenticador (TOTP)

- **Status:** aceito
- **Data:** 2026-10-19
- **Complementa:** ADR-013

## Contexto

Com a senha local (ADR-013), uma senha vazada passou a bastar para entrar. A
conta de maior estrago é a do administrador da agência: ela administra a
equipe, vê os dados de todos os criadores, desconecta redes, apaga histórico e
muda o CNPJ. O OWASP recomenda exigir MFA de administradores, e o NIST SP
800-63B-4 (final, 31/07/2025) define o nível AAL2 como senha mais um segundo
fator.

## Decisão

1. **Fator:** TOTP (RFC 6238) — SHA-1, 6 dígitos, passo de 30 s, segredo de
   160 bits —, que todos os apps autenticadores aceitam. Calculado com a
   biblioteca padrão e provado pelos vetores do Apêndice B da RFC.
2. **Obrigatório para administrador, opcional para os demais**, imposto pelo
   servidor: `auth_service.concluir_login` devolve um ticket no lugar da sessão
   — de desafio para quem tem 2FA, de ativação para o administrador sem ele.
   Todos os caminhos de entrada passam por ali (senha, Google, Microsoft,
   confirmação de e-mail); só o atalho de desenvolvimento fica de fora.
3. **Ticket** é um `AuthToken` (ADR-013) com finalidade própria: só o hash no
   banco, uso único atômico, 5 min para o desafio e 15 para a ativação.
4. **Verificação** (NIST §3.1.5.2): cada código vale uma vez — o último passo
   aceito é gravado com UPDATE condicional —, janela de ±1 passo, e limite de
   5 falhas a cada 15 minutos por conta. O segredo fica cifrado com a
   `FERNET_KEY`.
5. **Recuperação:** 10 códigos de uso único, guardados como HMAC com chave
   derivada da `FERNET_KEY`, e o comando `flask users reset-2fa` como último
   recurso, só no terminal do servidor.
6. **Ações sensíveis** — trocar a senha, gerar novos códigos, desligar o 2FA
   — exigem um código válido, e mudanças no 2FA geram aviso por e-mail
   (OWASP MFA Cheat Sheet).
7. **Ativar encerra as outras sessões** pelo marco da ADR-013: uma sessão
   aberta com a senha roubada não sobrevive à ativação.

## Alternativas recusadas

- **SMS:** restrito pelo NIST (§3.1.3.3) e desaconselhado pelo OWASP para
  aplicação com dado pessoal.
- **Código por e-mail:** o NIST proíbe e-mail como autenticação fora de banda
  (§3.1.3.1), e o e-mail já é o canal de "esqueci a senha" — quem o invade
  teria os dois fatores.
- **"Lembrar este dispositivo":** pede cookie de longa duração; fica para
  depois, se o uso pedir.

## Consequências

- O NIST pede que o AAL2 **ofereça** uma opção resistente a phishing (§2.2),
  e TOTP não é. Passkey (WebAuthn) é a próxima etapa natural.
- A conta nova pelo Google ou pelo cadastro nasce administradora e passa pela
  ativação antes de entrar pela primeira vez.
- Perder o celular e os códigos exige o comando no servidor: não há caminho
  de recuperação pela tela, de propósito.
