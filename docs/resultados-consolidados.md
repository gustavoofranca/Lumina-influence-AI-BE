# Resultados consolidados

Índice de evidência para a escrita: cada afirmação que o texto pode fazer, o
número que a sustenta, como ele foi obtido e onde está o relatório completo.
**Nada aqui é estimativa** — todo valor foi medido e está reproduzível pelo
relatório de origem.

Última consolidação: 9 de setembro de 2026.

## Como usar

Ao escrever uma seção, procure a afirmação na coluna da esquerda. Se ela não
estiver aqui, ou não foi medida, ou está em algum relatório que ainda não foi
consolidado — e nos dois casos **não deve ser afirmada sem antes medir**. Cada
linha cita o arquivo onde estão o método e os dados brutos.

## Qualidade do código

| Afirmação | Número | Como foi obtido | Evidência |
|---|---|---|---|
| O back-end tem cobertura automatizada | **441 testes, 95%** de `src/` | `pytest --cov=src` | [`testes/robustez-adaptadores.md`](testes/robustez-adaptadores.md) |
| A camada que fala com serviços externos é coberta | **os 5 adaptadores a 100%** (`instagram`, `tiktok`, `youtube`, `gemini`, `media`); `google_oauth` 96%; `microsoft_oauth` 91% | 133 cenários com dublês, sem rede | idem |
| A interface tem teste ponta a ponta | **80 testes** — 78 executados e 2 pulados —, ~9 min | Playwright sobre a aplicação em funcionamento | [`testes/e2e-front.md`](testes/e2e-front.md) |
| A interface é verificada além do teste automatizado | **7 verificações**, com defeito real registrado em cada uma; na execução de 08–09/09 as 7 rodaram sobre **25 rotas** e acharam 2 defeitos, ambos corrigidos | 6 das 7 já automatizadas; 2 temas, 2 idiomas | [`testes/verificacao-pre-entrega.md`](testes/verificacao-pre-entrega.md) |
| As decisões de arquitetura estão registradas | **12 ADRs**, cobrindo monolito modular, UUID como chave, três camadas e banco gerenciado | auditoria normativa de 08/09 apontou as 4 ausentes; escritas no formato das 7 anteriores | [`adr/`](adr/) |
| A bateria fechou os limites que declarou sobre si | **3 pontos cegos**, os 3 automatizados; cada teste validado reintroduzindo o defeito histórico | contraste com SVG e composição de camadas; carregamento com a resposta segurada; i18n com dois alvos novos | idem |

## Segurança

| Afirmação | Número | Como foi obtido | Evidência |
|---|---|---|---|
| Não há vulnerabilidade de severidade média ou alta no código | **0** achados Medium/High em **7.684 linhas** | `bandit` 1.9.4; os 17 Low foram verificados um a um, em 25/08 e de novo em 08/09, e são falso positivo | [`security/analise-estatica.md`](security/analise-estatica.md) |
| As dependências Python não têm vulnerabilidade conhecida | **0** | `pip-audit` 2.10.1 | idem |
| O ambiente é reproduzível | **27 de 27** dependências fixadas em `==` | congeladas a partir do ambiente que passa nos 441 testes; imagem limpa construída do arquivo passa nos mesmos 441 | `requirements.txt` |
| O corpo de requisição tem teto | **1 MB**, resposta 413 | `MAX_CONTENT_LENGTH`, conferido enviando 2 MB a um endpoint que lê o corpo | `src/config.py` |
| Log de autenticação não guarda dado pessoal | e-mail substituído por **id** nos 2 pontos | conferido nos registros emitidos pela suíte, não na leitura do código | `src/services/auth_service.py` |
| As vulnerabilidades do front não alcançam o produto | no que é **embarcado**: 0 crítica, **0 alta**, 2 moderadas, nenhuma alcançável. Com as dependências de compilação: 6 | `npm audit --omit=dev` separa embarcado de cadeia de build; a inalcançabilidade vem da inspeção dos 12 pontos de navegação dinâmica | idem |
| Não há referência direta insegura a objeto (IDOR) | **26 endpoints e 6 listagens, 0 vazamentos** | sondagem com identidade de outra agência, sem token e com id inexistente | [`security/idor.md`](security/idor.md) |
| O modelo resiste a injeção de prompt | **7 famílias de ataque, 7 resistiram**; schema íntegro em todas | cargas contra o `gemini-3.6-flash` real, em container isolado | [`security/prompt-injection.md`](security/prompt-injection.md) |

## Desempenho

| Afirmação | Número | Como foi obtido | Evidência |
|---|---|---|---|
| O gargalo de consulta foi identificado e corrigido | `/dashboard/overview`: **70 → 13 consultas**, **15 s → 3,2 s** contra o banco gerenciado | comparação local × gerenciado com **um único usuário** — sem fila, a diferença é round trip puro | [`testes/carga.md`](testes/carga.md) |
| A correção melhorou a vazão | **9,49 → 23,22 req/s** (50 usuários, local) | Locust 2.46 | idem |
| Os endpoints não multiplicam consulta com o tamanho da coleção | 13 das 15 rotas de leitura entre **2 e 7 consultas**; o N+1 restante (`/campaigns/{id}/benchmarking`, `3 + 5n`) foi corrigido para **7 constante**, 3.597 → 1.406 ms | contagem por requisição instrumentando o `Engine`; linearidade provada variando o número de participantes; resposta comparada campo a campo antes e depois | [`testes/carga.md`](testes/carga.md) |
| A arquitetura de processos multiplica a capacidade | latência com 50 usuários: **880 ms → 64 ms** de 1 para 4 workers | `gunicorn` | idem |
| O sistema satura sem falhar | **~43 req/s**, **0 falhas até 600 usuários** — degrada em tempo, não em erro | concorrência empurrada até a latência crescer | idem |

## Produto e dado real

| Afirmação | Número | Como foi obtido | Evidência |
|---|---|---|---|
| O sistema coleta de plataforma real via OAuth | canal de YouTube vinculado, **10 posts** e **1 comentário** ingeridos; 130 exibições conferem com o canal | fluxo completo de OAuth e sync em `mode: real` | [`testes/integracao-social.md`](testes/integracao-social.md) |
| A análise de IA roda sobre conteúdo verdadeiro | análise completa em **30,7 s** sobre os posts coletados | `gemini-3.6-flash` | idem |
| O que o produto afirma publicamente é o que ele faz | **29 afirmações auditadas**, 5 divergências, 4 resolvidas construindo o que faltava | leitura de cada frase dos documentos publicados contra a implementação | [`conformidade-publicada.md`](conformidade-publicada.md) |
| A exportação em PDF resiste a entrada adversa | **11 cenários**, nenhum arquivo corrompido, truncado ou ilegível | geração pelo caminho real de produção | [`testes/robustez-pdf.md`](testes/robustez-pdf.md) |
| Os adaptadores estão conformes às APIs vigentes | **6 defeitos** que impediriam ou falseariam a coleta, corrigidos; Instagram e TikTok de 0% e 41% para **100%** | leitura do código contra a documentação da Graph API v25.0 e da TikTok Display API v2 | [`testes/robustez-adaptadores.md`](testes/robustez-adaptadores.md) |

## Limites que o texto precisa declarar

Um trabalho sobre auditoria de dado não pode esconder o que não mediu. Estes
limites são conhecidos, têm decisão registrada e são defensáveis — desde que
declarados.

| Limite | Por quê | Onde está a decisão |
|---|---|---|
| Só **1 das 3 plataformas** foi conectada de fato | Instagram e TikTok exigem HTTPS público e App Review; a submissão à Meta está preparada e depende de domínio público e verificação de negócio | [`meta-app-review.md`](meta-app-review.md) |
| O adaptador do Instagram **não foi validado contra a rede real** | não há App Review aprovado; o que existe é conformidade com a documentação e 25 testes com dublê | [ADR-007](adr/0007-instagram-com-facebook-login-e-views.md) |
| A separação entre alcance **orgânico e pago vem do seed** | nenhuma API concede essa métrica sem programa comercial; a Data API v3 do YouTube não separa origem | idem |
| Não há teste de carga sobre o endpoint de análise | o free tier do Gemini dá **20 requisições por dia**; medir p95 com carga esgotaria a cota | [`testes/carga.md`](testes/carga.md) |
| A vazão medida é de um servidor com 4 workers | número de arquitetura, não de produto; o platô inicial de 32 req/s era teto do **gerador de carga**, não do servidor | idem |
| O que o **leitor de tela anuncia** é medido só em parte | desde 09/09 o **nome acessível** de todo controle é lido da árvore de acessibilidade por CDP, o que achou 4 interruptores sem nome; **ordem de leitura, `aria-live` e agrupamento continuam fora de alcance** | [`testes/verificacao-pre-entrega.md`](testes/verificacao-pre-entrega.md) |
| Um botão da landing fica em **3,39:1** na ponta escura do gradiente | veio assim do arquivo de design; a ponta clara dá 7,08:1 | mesmo relatório |
| Emoji no título do relatório vira quadrado no PDF | embarcar fonte com cobertura de emoji pesaria em todo PDF gerado | [`testes/robustez-pdf.md`](testes/robustez-pdf.md) |

## O que o método achou, que é o resultado menos óbvio

Vale como seção própria na escrita: **as medições que mais renderam não foram as
que confirmaram o esperado, e sim as que expuseram limite do próprio método.**

- Comparar local × gerenciado **com um único usuário** expôs um N+1 que teste de
  carga com concorrência esconderia atrás da fila.
- O platô de 32 req/s era o teto do gerador de carga. Sem empurrar a
  concorrência até a latência crescer, o número publicado seria falso.
- A varredura de contraste passou duas vezes numa tela com rótulos a 2,4:1,
  porque mede `color` e o SVG usa `fill`. Ao ser automatizada e passar a
  **compor** as camadas translúcidas, achou mais três famílias de defeito que o
  método antigo escondia — medir contra branco puro fazia tokens que sempre
  pousam sobre tinte parecerem folgados.
- **Uma varredura falha em silêncio pelo lado da exclusão, não pelo lado da
  detecção.** Detecção errada enche o relatório de ruído e alguém percebe;
  exclusão errada deixa o relatório limpo, que é o sintoma de um sistema são. A
  de i18n descartava `^[a-z][a-zA-Z]*$` para ignorar identificador e com isso
  ignorava qualquer palavra minúscula solta — inclusive "seguidores", fixo em
  português. A correção não foi o caso, foi a forma: todo descarte passou a ser
  contabilizado e impresso junto dos achados, e **na primeira execução com o
  relatório ligado apareceram mais duas exclusões largas demais**, uma delas
  descartando o rótulo "Export" por casar com a palavra-chave `export`. Em
  ferramenta de auditoria, a regra de exclusão é código de produção.
- **Teste que nunca reprovou pode não estar medindo nada.** Cada verificação
  automatizada foi validada reintroduzindo o defeito histórico, e duas delas
  passavam por vazio na primeira versão — uma media a tela antes de o gráfico
  existir, a outra tinha um padrão de rota estreito demais para interceptar.
- Um marcador de injeção de prompt apareceu na resposta do modelo e quase virou
  achado: estava no campo que **cita** o conteúdo analisado. Citar não é obedecer.
- Ler o código contra a **documentação vigente** achou três defeitos que nenhum
  teste local pegaria: os três só falham com um token real, e um deles só
  falharia **depois** do App Review aprovado. Cobertura não substitui conferir a
  API contra a fonte — o módulo tinha teste de rota passando e 0% de cobertura
  própria.
- **Documento publicado é código sem teste.** As páginas legais foram escritas
  em 31/08 e a primeira frase conferida contra o código era falsa; as duas
  seguintes também. Nada no sistema falha quando texto e implementação divergem,
  e é por isso que a divergência dura. A resposta foi dar endereço no código a
  cada compromisso: um teste que caia quando ele deixar de valer, ou uma
  verificação em execução que reclame.
- A resposta do modelo **varia entre execuções idênticas**: a mesma carga
  repetida 3× produziu o marcador em 1. Teste sobre modelo generativo exige
  repetição.
- **Guarda que não pode falhar não guarda nada.** O teste de contraste
  verificava a troca de tema com
  `classList.contains('dark') === false`. O tema não mora em classe: o app usa
  `data-theme` no `<html>`. Aquela classe **nunca existe**, então a asserção
  passava qualquer que fosse o tema — e o mesmo erro me fez rotular de "escuro"
  uma medição que estava clara. Só apareceu porque a varredura passou a imprimir
  o tema **efetivo** por rota. É o mesmo modo de falha da exclusão larga, do
  outro lado: ali o filtro esvazia a detecção, aqui a asserção esvazia a
  verificação.
- **Código que parece correto pela API errada.** O componente de interruptor
  envolvia o `<button role="switch">` num `<label htmlFor>`. Clicar no texto
  alternava o controle, o que dava a impressão de rótulo resolvido — mas
  `<label>` não nomeia `<button>`: pelo HTML-AAM o nome vem de
  `aria-labelledby`, de `aria-label` ou do conteúdo do próprio botão. Os quatro
  interruptores tinham nome **vazio** na árvore de acessibilidade. Nenhuma
  inspeção de código pegaria; leu-se a árvore que o leitor de tela recebe.
- **Medir o retângulo errado inventa defeito.** Na varredura de alvo de toque, o
  link "Nova Campanha" media 223×20 e reprovava. É um `<a>` `display: inline`
  envolvendo um `<button>` de 223×**40** — o alvo é o botão. Elemento inline
  não descreve a área do filho em bloco, do mesmo jeito que a viewport expandida
  não descreve o vazamento de largura.
- **O limite fixo de espera é uma aposta sobre a máquina.** A bateria mandava
  esperar 2 s por rota antes de medir se a tela renderizou. Medido: a tela de
  detalhe tem `<main>` no DOM e **0 caractere** aos 2,5 s, e 2.190 aos 5 s.
  Seguir a instrução reprovaria duas telas sãs. A correção não foi aumentar o
  número — foi esperar por **condição**, com o estouro do tempo virando o sinal.
