# ADR-008 — Monolito modular em vez de microsserviços

- **Status:** aceito
- **Data:** 2026-09-08 — registro retroativo de decisão tomada no início do projeto

## Contexto

O sistema cobre seis domínios: agência e usuários, criadores e contas sociais,
campanhas, posts e análise de IA, relatórios, e integrações externas. Um único
desenvolvedor o constrói dentro de um prazo fechado, e o resultado precisa ser
demonstrável numa apresentação, não operado por uma equipe de plantão.

A pergunta a decidir não é qual arquitetura é melhor em abstrato, e sim qual
delas um desenvolvedor sozinho consegue manter íntegra até a entrega.

## Alternativas consideradas

**Monolito tradicional.** Uma aplicação sem fronteira interna declarada. É o
mais rápido de escrever e o mais barato de operar. O custo aparece quando o
domínio cresce: sem fronteira, a lógica de campanha e a de criador se misturam,
e depois de misturadas não se separam sem reescrita.

**Microsserviços.** Fronteira imposta pelo processo — um serviço não alcança a
tabela do outro porque não tem conexão com o banco dele. Em troca, cada
fronteira vira uma chamada de rede que pode falhar, e o sistema passa a exigir
orquestração, descoberta de serviço, rastreamento distribuído e uma estratégia
de consistência entre bancos. Newman (2019) é explícito quanto a isso: a
migração se justifica por um problema concreto — escala independente,
autonomia de equipes — e nenhum dos dois existe aqui, com um desenvolvedor e
uma instância. Fowler (2015) chega do outro lado e conclui o mesmo: começar
monolítico e extrair depois, quando as fronteiras já se revelaram no uso.

**Serverless.** Elimina a operação de servidor, mas fragmenta o domínio em
funções e cobra partida a frio justamente no caminho mais lento do sistema, a
análise de vídeo pelo Gemini, que já leva dezenas de segundos.

**Monolito modular.** Um processo, um banco, e a fronteira declarada dentro do
código em vez de imposta pela rede.

## Decisão

Monolito modular, organizado em duas direções ao mesmo tempo.

Quatro camadas horizontais, cada uma com uma responsabilidade e uma direção de
dependência que não se inverte:

1. `api/` — blueprints REST. Traduzem HTTP em chamada de serviço e serviço em
   resposta. Não contêm regra de negócio nem tocam o banco.
2. `services/` — a lógica de negócio. É a única camada que decide.
3. `models/` — o mapeamento SQLAlchemy. Estrutura de dado, não comportamento.
4. `integrations/` — adaptadores para o que é de terceiro: Gemini, Instagram,
   TikTok, YouTube, OAuth. Isolam a API externa do resto do sistema, o que é o
   que permite substituir uma chamada real por simulação sem tocar em serviço.

Seis módulos verticais atravessando essas camadas, um por domínio.

A regra que sustenta o desenho: **um módulo fala com outro apenas pela camada de
serviços.** Um serviço não importa o model de outro módulo — pede ao serviço
dono daquele model.

## Consequências

- Operação simples: um processo, um banco, um deploy. Nenhuma falha de rede
  interna, nenhuma consistência eventual a raciocinar.
- A extração de um módulo para serviço próprio continua possível, e é para isso
  que a fronteira existe. É o caminho que Fowler descreve.
- **A fronteira depende de disciplina, não de imposição.** Nada no interpretador
  impede um `from src.models.influencer import Influencer` dentro de
  `campaign_service.py`. Em microsserviços isso seria um erro de conexão; aqui
  é uma linha que passa no teste.

  Esta é a contrapartida real da decisão, e ela já se materializou. A auditoria
  de 08/09/2026 encontrou **cinco serviços importando models de outro módulo**:

  | Serviço | Models importados de fora do próprio módulo |
  |---|---|
  | `campaign_service.py` | `Influencer` |
  | `integration_service.py` | `Comment`, `Influencer`, `OAuthProvider`, `OAuthState`, `Platform` |
  | `post_service.py` | `AIAnalysis`, `Influencer`, `SocialAccount` |
  | `social_account_service.py` | `Influencer`, `Platform` |
  | `user_service.py` | `Campaign`, `Influencer`, `OAuthProvider`, `Report` |

  Ficam registradas como dívida técnica conhecida, sob o identificador ARQ-01,
  e não como conformidade. Corrigi-las a poucos dias da entrega custaria
  refatoração estrutural em cinco serviços, com risco de regressão que o
  calendário não comporta — a decisão de adiar está no plano de correção.

  Nem toda ocorrência é do mesmo tipo. `user_service → Campaign, Report` pede
  que o serviço dono exponha uma função. `social_account_service → Influencer`
  provavelmente indica outra coisa: que conta social e criador pertencem ao
  mesmo contexto delimitado, e que a fronteira é que está mal desenhada.
- Enquanto a dívida existir, a afirmação "monolito modular" descreve o desenho
  pretendido e não o estado integral do código. Divergência documentada é
  dívida; divergência silenciosa seria contradição.

## Referências

- FOWLER, M. *MonolithFirst*. 2015.
- NEWMAN, S. *Monolith to Microservices*. O'Reilly, 2019.
- AL-QORA'N; AL-SAID AHMAD. 2025. — conferir a entrada exata na bibliografia do
  trabalho antes da versão final.
