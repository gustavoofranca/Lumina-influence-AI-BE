# Submissão ao App Review da Meta

Dossiê da preparação para pedir **Advanced Access** às permissões do Instagram.
Reúne o que a Meta exige, o que o projeto já cumpre, o que falta e em que ordem
resolver. Alvo: **entrega final**, não a de 75% — a fila de revisão leva de duas
a quatro semanas e a verificação de negócio corre em paralelo, com prazo próprio.

- **Data do levantamento:** 31 de agosto de 2026
- **Configuração escolhida:** *Instagram API with Facebook Login*
- **Permissões pedidas:** `instagram_basic`, `instagram_manage_insights`,
  `pages_show_list`, `pages_read_engagement`
- **Permissões deliberadamente não pedidas:** qualquer uma da Marketing API

## Por que esta configuração

`instagram_manage_insights` só existe na configuração com Facebook Login. A
variante com login pelo próprio Instagram é mais simples de autorizar e **não
concede insights** — sem insights não há auditoria de alcance, que é o produto.
A consequência dessa escolha (o token ser de usuário do Facebook, e não do
perfil do Instagram) está na [ADR-007](adr/0007-instagram-com-facebook-login-e-views.md).

## Estado de cada requisito

| # | Requisito da Meta | Estado | Onde |
|---|---|---|---|
| 1 | Código não pede métrica removida da API | **cumprido** | `src/integrations/instagram.py` |
| 2 | Versão da Graph API vigente | **cumprido** (v25.0) | `instagram.py:API_VERSION` |
| 3 | Escopos coerentes com o que o app faz | **cumprido** (4 escopos, nenhum de escrita) | `instagram.py:SCOPES` |
| 4 | Política de privacidade em URL pública | **cumprido** | `/privacidade`, pt e en |
| 5 | Termos de uso em URL pública | **cumprido** | `/termos`, pt e en |
| 6 | Caminho de exclusão de dados | **cumprido** | `/exclusao-de-dados`, pt e en |
| 7 | Interface em inglês para o revisor | **cumprido** | seletor de idioma no cabeçalho |
| 8 | App acessível por HTTPS público | **pendente** | `OAUTH_REDIRECT_BASE` ainda em `localhost` |
| 9 | Ícone, categoria e e-mail de contato do app | **pendente** | painel da Meta |
| 10 | Verificação de negócio concluída | **pendente — caminho crítico** | Business Manager |
| 11 | App em modo Live | **pendente** | depende de 8 e 9 |
| 12 | Screencast por permissão | **pendente** | roteiro abaixo |

Os itens 1 a 7 são de código e estão feitos. Os itens 8 a 12 dependem de
credenciais, documentos e domínio — só Gustavo pode executá-los.

## O que causaria rejeição e foi corrigido

**A métrica que devolvia erro.** `impressions` saiu da API na v22.0 (21/04/2025)
e hoje devolve erro para mídia criada a partir de 02/07/2024. O adaptador a
pedia na mesma chamada que traz alcance, curtidas e salvamentos: o erro
derrubaria a coleta inteira — o revisor veria a tela de um criador conectado sem
nenhum dado. Substituída por `views`.

**A chamada ao nó errado.** `fetch_profile_metrics` e `fetch_recent_posts`
falavam com `/me`, que num token de usuário do Facebook é a pessoa e não o
perfil do Instagram. Passaram a descobrir a Página com
`instagram_business_account` e usar o ID e o token dela.

**Os três links mortos do rodapé.** Privacidade, termos e contato apontavam para
`#`. O revisor abre cada um.

**O escopo faltando.** Sem `pages_read_engagement` a leitura da Página devolve
403 — falha que só apareceria depois da aprovação.

## Roteiro dos screencasts

A Meta pede **um vídeo por permissão**, não um só cobrindo tudo, e recusa
submissão em que qualquer permissão fique sem vídeo. Requisitos comuns aos
quatro: interface **em inglês** (o seletor está no cabeçalho, e as páginas
legais também existem em inglês), resolução de 1080p, e o fluxo começando
deslogado.

Estrutura de cada vídeo:

1. Abrir a landing deslogado, trocar o idioma para EN.
2. Entrar na plataforma.
3. Abrir um criador e iniciar a conexão do Instagram.
4. **Mostrar a tela de consentimento da Meta por inteiro**, com a permissão em
   questão visível na lista.
5. Concluir a autorização e voltar à plataforma.
6. Mostrar **onde aquele dado específico aparece** na interface.

O passo 6 é o que muda entre os quatro:

| Permissão | O que mostrar no passo 6 |
|---|---|
| `instagram_basic` | perfil do criador com nome de usuário e seguidores preenchidos, e a lista de publicações com legenda e miniatura |
| `instagram_manage_insights` | aba de publicações com alcance, visualizações, salvamentos e compartilhamentos; e o relatório em PDF que consolida esses números |
| `pages_show_list` | a tela de conexão listando a Página que será usada, antes de confirmar |
| `pages_read_engagement` | a mesma tela concluindo com sucesso, e os dados chegando — é a permissão que autoriza ler a Página escolhida |

## Passo a passo do que só Gustavo pode fazer

### 1. Verificação de negócio — comece por aqui

É o caminho crítico: roda em paralelo e tem prazo próprio, independente do app.

1. Abrir [business.facebook.com](https://business.facebook.com) com a conta que
   é administradora do app.
2. Menu **Configurações do negócio → Central de segurança**.
3. Iniciar **Verificação de negócio** e enviar os documentos da K13 WEB: cartão
   CNPJ, comprovante de endereço em nome da empresa e um meio de contato
   verificável (telefone ou e-mail no domínio da empresa).
4. Resultado esperado: status **"Em análise"** na Central de segurança.
5. Conferir: o status muda para **"Verificado"**. Enquanto não mudar, o pedido
   de Advanced Access não pode ser enviado.

### 2. Domínio público com HTTPS

O revisor precisa alcançar o app, e a Meta só aceita `redirect_uri` em HTTPS.

1. Escolher o domínio (subdomínio da K13 serve).
2. Publicar back-end e front-end nele, ou expor a stack local por túnel nomeado
   e estável — o endereço não pode mudar entre a submissão e a revisão.
3. No back-end, definir `OAUTH_REDIRECT_BASE=https://<domínio>` no `.env`.
   Hoje está `http://localhost:5000`.
4. No front-end, definir `VITE_API_BASE_URL` e `VITE_CONTACT_EMAIL`.
5. Conferir: abrir `https://<domínio>/privacidade` de fora da rede local e ver a
   política renderizada.

### 3. Configuração do app no painel da Meta

1. [developers.facebook.com/apps](https://developers.facebook.com/apps) → o app
   da Lumina → **Configurações → Básico**.
2. Preencher: **ícone** (1024×1024), **categoria**, **e-mail de contato**,
   **URL da política de privacidade** = `https://<domínio>/privacidade`,
   **URL dos termos** = `https://<domínio>/termos`, e
   **Instruções de exclusão de dados** = `https://<domínio>/exclusao-de-dados`.
3. O e-mail de contato precisa ser **o mesmo** publicado nas páginas legais
   (`VITE_CONTACT_EMAIL`). Divergência entre os dois é motivo documentado de
   rejeição.
4. Em **Facebook Login → Configurações**, adicionar
   `https://<domínio>/api/v1/integrations/instagram/callback` aos URIs de
   redirecionamento válidos.
5. Virar a chave para o **modo Live** no topo do painel.
6. Conferir: com o app em Live, conectar uma conta do Instagram de ponta a ponta
   e ver as publicações chegando.

### 4. Submissão

1. **App Review → Permissões e recursos.**
2. Pedir **Advanced Access** para as quatro permissões **na mesma submissão**.
   Pedidos separados são revisados em filas separadas, e uma rejeição em
   qualquer uma atrasa o conjunto.
3. Anexar o screencast correspondente a cada permissão.
4. Na descrição de uso, dizer em uma frase o que o app faz com aquele dado e
   onde ele aparece — a mesma tela que o vídeo mostra.
5. Não fornecer credenciais de conta pessoal: a Meta testa com contas próprias.
   O que ela exige é que o app esteja **acessível**.

## Decisões registradas

**Instruções de exclusão em vez de callback.** A Meta aceita as duas formas. O
callback recebe um `signed_request` com o **ID do usuário do Facebook**, e a
Lumina não guarda esse identificador — ela guarda o ID do perfil profissional do
Instagram. Implementar o callback exigiria uma coluna nova e uma migration para
gravar uma identidade que o produto não usa para mais nada. A página de
instruções cumpre o requisito, descreve caminhos de exclusão que **existem e
funcionam** na plataforma, e não introduz dado pessoal novo. Se um dia o
Facebook Login virar também o login da aplicação, a decisão muda.

**Marketing API fora da submissão.** Ela é o que separaria alcance orgânico de
pago (ver [ADR-005](adr/0005-alcance-organico-e-pago-vem-do-seed.md)), mas é
outro review, mais pesado. Pedir permissão que o app não exerce é causa comum de
rejeição, e uma rejeição recomeça a fila.

## O que este trabalho não prova

Nenhuma chamada foi feita contra a rede real: não há App Review aprovado, e é
essa a razão do pedido. O que existe é conformidade com a documentação vigente e
uma suíte que trava cada decisão — 25 testes, 100% do adaptador. A validação de
verdade acontece no primeiro sync com o app em Live, e o resultado dela deve
voltar para este arquivo.
