# Conformidade entre o documento publicado e o código

As páginas de Política de Privacidade, Termos de Uso e Exclusão de Dados são as
únicas partes do sistema em que **o produto faz afirmações sobre si mesmo para
quem não pode conferi-las**. O usuário lê como compromisso; o revisor do App
Review da Meta lê como declaração; e, diferente de qualquer outra parte do
código, nada falha quando o texto e a implementação divergem.

Esta tabela é a auditoria de cada afirmação contra a implementação que a cumpre,
e o teste que trava a implementação no lugar.

- **Data da auditoria:** 1º de setembro de 2026
- **Documentos auditados:** 12 seções da política, 11 dos termos, 6 da página de
  exclusão
- **Divergências encontradas:** 5 — todas corrigidas, 4 delas construindo o que
  faltava em vez de reescrever o texto

## Como esta auditoria começou

Não foi planejada. As páginas legais foram escritas em 31/08 para a submissão à
Meta, e ao conferir a primeira frase contra o código — "desconectar apaga as
publicações coletadas" — ela era falsa. As duas seguintes também. A partir daí
virou varredura.

O padrão vale registrar porque atravessa o projeto inteiro na sua forma mais
cara: **afirmar sobre algo que ninguém verificou.** Aqui a afirmação é sobre o
próprio sistema, e o custo de errar é um compromisso quebrado com quem confiou.

## Afirmações e onde elas se cumprem

### Política de Privacidade

| § | Afirmação | Onde se cumpre | Teste que trava |
|---|---|---|---|
| 2 | "Não recebemos nem armazenamos a sua senha" | login é só OAuth; `User` não tem campo de senha | `test_auth.py` — os dois provedores |
| 2 | "Tokens de acesso guardados criptografados" | `utils/crypto.py`, Fernet, chave fora do banco | `test_crypto.py` |
| 3 | "Não usamos os dados para treinar modelos, nem permitimos que nossos fornecedores o façam" | **depende do tier do Gemini** — ver abaixo | `test_retencao.py::test_free_tier_em_producao_e_sinalizado_como_nao_conforme` |
| 4 | "o arquivo é enviado, processado e apagado do serviço do Google" | `gemini.py`, `finally: files.delete` | `test_adaptadores.py::test_gemini_multimodal_sempre_remove_o_arquivo_remoto` |
| 7 | "tokens expirados são removidos pela rotina de limpeza" | `jobs/cleanup_expired_tokens.py::purge_dead_social_tokens` | 4 testes, um por estado de token |
| 7 | "registro de uso descartado em até 90 dias" | `purge_old_usage_logs`, janela em `RETENTION_DAYS` | `test_a_janela_de_retencao_vem_da_configuracao` |
| 8 | "os caminhos de exclusão estão na plataforma" | 3 caminhos na interface | `test_exclusao_do_titular.py` (13) + 4 ponta a ponta |
| 9 | "todo tráfego usa HTTPS" | HSTS em `_register_security_headers`, só sobre TLS | `test_hardening.py` |
| 9 | "acesso limitado pela agência, verificado por testes a cada mudança" | `utils/authz.py` | 26 endpoints e 6 listagens sondados — [`security/idor.md`](security/idor.md) |

### Termos de Uso

| § | Afirmação | Situação |
|---|---|---|
| 5 | "as métricas podem divergir do app nativo" | verdadeiro e **necessário** — `views` substituiu `impressions` com outra definição ([ADR-007](adr/0007-instagram-com-facebook-login-e-views.md)) |
| 5 | "a separação orgânico/pago não é medida pela API pública" | verdadeiro ([ADR-005](adr/0005-alcance-organico-e-pago-vem-do-seed.md)); declarado também na interface |
| 5 | "os diagnósticos são apoio à decisão, não garantia" | verdadeiro; nenhuma decisão automatizada é tomada sobre pessoas |

## As cinco divergências

| # | O que o texto afirmava | O que havia | Como foi resolvido |
|---|---|---|---|
| 1 | desconectar apaga as publicações | só apagava os tokens | **construído**: virou escolha na hora de desconectar |
| 2 | "excluir criador" é caminho na interface | endpoint existia, tela não oferecia | **construído**, com confirmação digitada |
| 3 | "excluir minha conta" é caminho na interface | back-end fazia *soft delete* e proibia auto-remoção | **construído**: `DELETE /users/me` |
| 4 | tokens expirados são removidos pela limpeza | o job só removia `OAuthState` | **construído**: purga de credencial morta |
| 5 | registros descartados em até 90 dias | não havia descarte nenhum | **construído** para o que guardamos; **texto corrigido** para o que não controlamos |

Quatro das cinco viraram produto. A quinta é a mais instrutiva pelo motivo
oposto: os registros de execução vão para a saída padrão do servidor e são
retidos pelo ambiente de hospedagem. Prometer descarte do que não controlamos
seria promessa vazia, então o texto passou a **declarar o limite** em vez de
esconder. Nem toda divergência se resolve construindo.

## O compromisso que depende de configuração

O §3 é diferente dos outros: ele não depende de código nosso, e sim do **tier da
API do Gemini**. No free tier o Google pode usar o conteúdo enviado para
melhorar seus produtos; no tier pago, não. A chave é a mesma nos dois, e não há
como descobrir o tier a partir dela.

Um compromisso publicado que depende de alguém lembrar de uma variável de
ambiente não é compromisso, é intenção. Então:

- `GEMINI_PAID_TIER` é declaração explícita, com o motivo escrito ao lado no
  `.env.example`;
- fora de desenvolvimento, com chave configurada e sem a declaração, **o boot
  emite aviso** nomeando a contradição;
- `/api/v1/health` publica `model_privacy: compliant | free_tier_warning`,
  porque uma linha de log do boot ninguém relê.

Em dev e em teste o free tier é aceitável: os dados são de seed, e o
compromisso é com gente real.

Vale notar que sair do free tier resolve **duas** coisas ao mesmo tempo — este
compromisso e o 429 que ameaça a apresentação —, por menos de dois dólares até a
entrega final. A conta está em [`cota-e-custo-gemini.md`](cota-e-custo-gemini.md).

## A lição de método

**Documentação que descreve comportamento é código sem teste.** Ou se verifica
contra a implementação antes de publicar, ou se prende a implementação com um
teste que cite o documento — foi o que se fez em
`test_disconnect_preserva_o_historico_ja_coletado` e em todo o
`test_retencao.py`, cujas docstrings dizem qual frase de qual documento cada
asserção sustenta.

A generalização que este projeto sugere: **todo compromisso publicado deveria
ter um endereço no código.** Ou um teste que falhe quando ele deixar de valer,
ou uma verificação em tempo de execução que reclame. Sem isso, o documento
envelhece em silêncio — e o silêncio é justamente o problema que o trabalho
inteiro persegue.
