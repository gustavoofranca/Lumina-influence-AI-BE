"""Trava das fronteiras entre módulos de `src/services` (ARQ-01, fase F0).

A ADR-008 diz que um serviço não importa o model de outro módulo: pede ao
serviço dono daquele model. Nada no interpretador impede o import cruzado, então
a regra só se sustenta se um teste reprovar quando ela for quebrada. Este teste
lê o código com `ast` (sem importar os serviços), aplica o mapa de donos do
plano ARQ-01 (seção 2) e compara com a lista de exceções conhecidas.

O que conta como violação:
- `from src.models import X` (ou `from src.models.modulo import X`) num serviço
  cujo domínio não é o dono de `X`, inclusive import feito dentro de função;
- não conta import sob `if TYPE_CHECKING:` (anotação não acopla comportamento,
  seção 2.4), nem enum de `models/_enums.py` ou a infraestrutura de
  `models/base.py` (núcleo compartilhado, seção 2.2).
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA_SERVICOS = RAIZ / "src" / "services"
PASTA_MODELS = RAIZ / "src" / "models"

AGENCIA = "Agência e usuários"
CRIADORES = "Criadores"
CAMPANHAS = "Campanhas"
CONTEUDO = "Conteúdo e IA"
RELATORIOS = "Relatórios"
INTEGRACOES = "Integrações"

# Mapa de donos, seção 2.1 do plano ARQ-01. Model novo precisa entrar aqui:
# sem dono não há como dizer se o import dele cruza fronteira.
DONO_DO_MODEL = {
    "Agency": AGENCIA,
    "Plan": AGENCIA,
    "User": AGENCIA,
    "AuthToken": AGENCIA,
    "CodigoRecuperacao": AGENCIA,
    # Proteção contra replay do `state` do OAuth: primitiva de segurança do
    # login, reaproveitada pela conexão de redes. Segurança tem um dono só.
    "OAuthState": AGENCIA,
    "Influencer": CRIADORES,
    "SocialAccount": CRIADORES,
    "Campaign": CAMPANHAS,
    "CampaignInfluencer": CAMPANHAS,
    "Post": CONTEUDO,
    "Comment": CONTEUDO,
    "AIAnalysis": CONTEUDO,
    "RecommendationDecision": CONTEUDO,
    "ApiUsageLog": CONTEUDO,
    "Report": RELATORIOS,
}

DOMINIO_DO_SERVICO = {
    "agency_service": AGENCIA,
    "user_service": AGENCIA,
    "auth_service": AGENCIA,
    "senha_service": AGENCIA,
    "cadastro_service": AGENCIA,
    "token_service": AGENCIA,
    "dois_fatores_service": AGENCIA,
    "plan_service": AGENCIA,
    "emails": AGENCIA,
    "influencer_service": CRIADORES,
    "social_account_service": CRIADORES,
    "campaign_service": CAMPANHAS,
    "post_service": CONTEUDO,
    "ai_analysis_service": CONTEUDO,
    "video_upload_service": CONTEUDO,
    "report_service": RELATORIOS,
    # Não tem tabela própria: todo model que ela importa é de outro domínio.
    "integration_service": INTEGRACOES,
}

# Camada de leitura (seção 2.3): o dashboard é, por definição, uma visão de
# todos os domínios. A isenção vale enquanto eles só lerem, e isso é conferido
# em `test_camada_de_leitura_nao_grava`.
CAMADA_DE_LEITURA = {"dashboard_service", "metric_service"}

# Módulos de `src/services` que não são serviço de domínio.
FORA_DO_MAPA = {
    # Só marca o pacote.
    "__init__": "pacote",
    # Texto do HTML do relatório; não consulta nem grava nada.
    "report_template": "modelo de HTML do relatório",
    # Healthcheck: faz `SELECT 1` pela sessão, sem model nenhum.
    "health_service": "verificação de dependências do healthcheck",
}

# Violações conhecidas em 24/11/2026 (par serviço -> model).
# ESTA LISTA SÓ PODE DIMINUIR. Cada fase do plano ARQ-01 remove os pares que
# corrigiu; o teste reprova se um par daqui deixar de existir no código, para a
# lista não guardar entrada morta. Acrescentar par novo é reabrir a dívida que
# o plano fecha: em vez disso, peça ao serviço dono (ADR-008).
EXCECOES = {
    # F2 (contagens): itens 5 e 6 do plano.
    ("agency_service", "AIAnalysis"),
    ("agency_service", "Influencer"),
    ("agency_service", "Post"),
    ("agency_service", "Report"),
    ("agency_service", "SocialAccount"),
    ("user_service", "Campaign"),
    ("user_service", "Influencer"),
    ("user_service", "Report"),
    # F3 (campanhas e relatório): itens 4, 8 e 9.
    ("campaign_service", "Influencer"),
    ("report_service", "Campaign"),
    ("report_service", "Post"),
    ("video_upload_service", "Campaign"),
    ("video_upload_service", "Influencer"),
    ("video_upload_service", "SocialAccount"),
    # F1 (escopo por agência): item 3.
    ("post_service", "Influencer"),
    ("post_service", "SocialAccount"),
    # F4 (decisões de recomendação): item 7.
    ("influencer_service", "AIAnalysis"),
    ("influencer_service", "Post"),
    ("influencer_service", "RecommendationDecision"),
    # F5 (integração): itens 10 a 13.
    ("integration_service", "Comment"),
    ("integration_service", "Influencer"),
    ("integration_service", "OAuthState"),
    ("integration_service", "Post"),
    ("integration_service", "SocialAccount"),
}

# Ciclos de import (de nível de módulo) que já existiam quando a trava entrou.
# Vazia: hoje não há ciclo. Mesma regra da lista acima, só pode diminuir.
CICLOS_CONHECIDOS: set[frozenset[str]] = set()


# ==========================================================================
# Leitura dos imports com ast
# ==========================================================================
@dataclass
class ImportsDoModulo:
    # Nomes importados de `src.models`, em qualquer nível (inclusive função).
    nomes_de_models: set[str] = field(default_factory=set)
    # Serviços importados no nível do módulo: são os que podem fechar ciclo.
    servicos_no_modulo: set[str] = field(default_factory=set)
    # Imports que o teste não consegue resolver para nomes (`import src.models`,
    # `from src.models import *`); reprovam para não esconder violação.
    nao_verificaveis: list[str] = field(default_factory=list)


def _eh_type_checking(teste: ast.expr) -> bool:
    if isinstance(teste, ast.Name):
        return teste.id == "TYPE_CHECKING"
    return isinstance(teste, ast.Attribute) and teste.attr == "TYPE_CHECKING"


def _modulo_absoluto(no: ast.ImportFrom, pacote: str) -> str:
    if not no.level:
        return no.module or ""
    partes = pacote.split(".")
    base = partes[: len(partes) - no.level + 1]
    return ".".join(base + ([no.module] if no.module else []))


class _Coletor(ast.NodeVisitor):
    def __init__(self, pacote: str, servicos_existentes: set[str]):
        self.pacote = pacote
        self.servicos_existentes = servicos_existentes
        self.resultado = ImportsDoModulo()
        self._profundidade_de_funcao = 0

    def visit_If(self, no: ast.If) -> None:
        # Só o corpo do `if TYPE_CHECKING:` é ignorado; o `else` roda de verdade.
        if not _eh_type_checking(no.test):
            for filho in no.body:
                self.visit(filho)
        for filho in no.orelse:
            self.visit(filho)

    def _visitar_funcao(self, no: ast.AST) -> None:
        self._profundidade_de_funcao += 1
        self.generic_visit(no)
        self._profundidade_de_funcao -= 1

    visit_FunctionDef = _visitar_funcao
    visit_AsyncFunctionDef = _visitar_funcao
    visit_Lambda = _visitar_funcao

    def _servico(self, nome: str) -> None:
        if self._profundidade_de_funcao == 0 and nome in self.servicos_existentes:
            self.resultado.servicos_no_modulo.add(nome)

    def visit_Import(self, no: ast.Import) -> None:
        for alias in no.names:
            if alias.name == "src.models" or alias.name.startswith("src.models."):
                self.resultado.nao_verificaveis.append(
                    f"linha {no.lineno}: import {alias.name}"
                )
            elif alias.name.startswith("src.services."):
                self._servico(alias.name.split(".")[2])

    def visit_ImportFrom(self, no: ast.ImportFrom) -> None:
        modulo = _modulo_absoluto(no, self.pacote)
        nomes = [alias.name for alias in no.names]
        if modulo == "src.models" or modulo.startswith("src.models."):
            if "*" in nomes:
                self.resultado.nao_verificaveis.append(
                    f"linha {no.lineno}: from {modulo} import *"
                )
            else:
                self.resultado.nomes_de_models.update(nomes)
        elif modulo == "src.services":
            for nome in nomes:
                self._servico(nome)
        elif modulo.startswith("src.services."):
            self._servico(modulo.split(".")[2])


def ler_imports(
    codigo: str, servicos_existentes: set[str], pacote: str = "src.services"
) -> ImportsDoModulo:
    coletor = _Coletor(pacote, servicos_existentes)
    coletor.visit(ast.parse(codigo))
    return coletor.resultado


def _servicos() -> dict[str, Path]:
    return {p.stem: p for p in sorted(PASTA_SERVICOS.glob("*.py"))}


def _nomes_de_nivel_de_modulo(arquivo: Path) -> set[str]:
    nomes = set()
    for no in ast.parse(arquivo.read_text(encoding="utf-8")).body:
        if isinstance(no, (ast.ClassDef, ast.FunctionDef)):
            nomes.add(no.name)
        elif isinstance(no, ast.Assign):
            nomes.update(t.id for t in no.targets if isinstance(t, ast.Name))
    return nomes


def _nucleo_compartilhado() -> set[str]:
    # Lido do próprio código: enum novo em `_enums.py` já nasce compartilhado,
    # sem precisar lembrar de atualizar este teste.
    return _nomes_de_nivel_de_modulo(PASTA_MODELS / "_enums.py") | _nomes_de_nivel_de_modulo(
        PASTA_MODELS / "base.py"
    )


def _imports_de_todos() -> dict[str, ImportsDoModulo]:
    servicos = _servicos()
    return {
        nome: ler_imports(caminho.read_text(encoding="utf-8"), set(servicos))
        for nome, caminho in servicos.items()
    }


def _violacoes_atuais() -> set[tuple[str, str]]:
    nucleo = _nucleo_compartilhado()
    violacoes = set()
    for servico, imports in _imports_de_todos().items():
        if servico in CAMADA_DE_LEITURA or servico not in DOMINIO_DO_SERVICO:
            continue
        for nome in imports.nomes_de_models - nucleo:
            if DONO_DO_MODEL.get(nome) != DOMINIO_DO_SERVICO[servico]:
                violacoes.add((servico, nome))
    return violacoes


# ==========================================================================
# Detecção de ciclo e de gravação
# ==========================================================================
def encontrar_ciclos(grafo: dict[str, set[str]]) -> set[frozenset[str]]:
    """Componentes fortemente conexos com mais de um nó, ou nó que importa a si."""
    indice: dict[str, int] = {}
    menor: dict[str, int] = {}
    pilha: list[str] = []
    na_pilha: set[str] = set()
    ciclos: set[frozenset[str]] = set()
    contador = [0]

    def visitar(no: str) -> None:
        indice[no] = menor[no] = contador[0]
        contador[0] += 1
        pilha.append(no)
        na_pilha.add(no)
        for vizinho in grafo.get(no, ()):
            if vizinho not in indice:
                visitar(vizinho)
                menor[no] = min(menor[no], menor[vizinho])
            elif vizinho in na_pilha:
                menor[no] = min(menor[no], indice[vizinho])
        if menor[no] == indice[no]:
            componente = set()
            while True:
                topo = pilha.pop()
                na_pilha.discard(topo)
                componente.add(topo)
                if topo == no:
                    break
            if len(componente) > 1 or no in grafo.get(no, ()):
                ciclos.add(frozenset(componente))

    for no in sorted(grafo):
        if no not in indice:
            visitar(no)
    return ciclos


_METODOS_DE_GRAVACAO_DA_SESSAO = {
    "add",
    "add_all",
    "delete",
    "commit",
    "flush",
    "merge",
    "bulk_save_objects",
    "bulk_insert_mappings",
    "bulk_update_mappings",
}
_CONSTRUTORES_DE_DML = {"insert", "update", "delete"}
_SQL_QUE_GRAVA = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE)\b", re.IGNORECASE)


def _cadeia(no: ast.expr) -> list[str]:
    """Nomes da cadeia de atributos e chamadas: `db.session.add` -> [db, session, add]."""
    nomes = []
    while True:
        if isinstance(no, ast.Attribute):
            nomes.append(no.attr)
            no = no.value
        elif isinstance(no, ast.Call):
            no = no.func
        elif isinstance(no, ast.Name):
            nomes.append(no.id)
            break
        else:
            break
    return list(reversed(nomes))


def encontrar_gravacoes(codigo: str) -> list[str]:
    arvore = ast.parse(codigo)
    # Nomes locais que apontam para o sqlalchemy ou para insert/update/delete
    # dele, para pegar também `from sqlalchemy import update as upd`.
    modulos_sa: set[str] = set()
    dml_importado: set[str] = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            for alias in no.names:
                if alias.name == "sqlalchemy" or alias.name.startswith("sqlalchemy."):
                    modulos_sa.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(no, ast.ImportFrom) and (no.module or "").startswith("sqlalchemy"):
            for alias in no.names:
                if alias.name in _CONSTRUTORES_DE_DML:
                    dml_importado.add(alias.asname or alias.name)

    achados = []
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Call):
            continue
        cadeia = _cadeia(no.func)
        if not cadeia:
            continue
        metodo = cadeia[-1]
        if isinstance(no.func, ast.Name) and metodo in dml_importado:
            achados.append(f"linha {no.lineno}: {metodo}(...)")
        elif "session" in cadeia[:-1] and metodo in _METODOS_DE_GRAVACAO_DA_SESSAO:
            achados.append(f"linha {no.lineno}: {'.'.join(cadeia)}(...)")
        elif metodo in _CONSTRUTORES_DE_DML and len(cadeia) > 1 and (
            cadeia[0] in modulos_sa
            or "query" in cadeia[:-1]
            or "__table__" in cadeia[:-1]
        ):
            achados.append(f"linha {no.lineno}: {'.'.join(cadeia)}(...)")
        elif metodo == "text" and no.args and isinstance(no.args[0], ast.Constant):
            sql = no.args[0].value
            if isinstance(sql, str) and _SQL_QUE_GRAVA.search(sql):
                achados.append(f"linha {no.lineno}: text({sql!r})")
    return achados


# ==========================================================================
# A trava
# ==========================================================================
def test_nenhuma_violacao_nova_de_fronteira():
    novas = sorted(_violacoes_atuais() - EXCECOES)
    assert not novas, (
        "Serviço importando model de outro domínio (ADR-008):\n"
        + "\n".join(
            f"  - {servico} -> {model} (dono: {DONO_DO_MODEL.get(model)})"
            for servico, model in novas
        )
        + "\nPeça ao serviço dono do model uma função que faça a consulta ou a "
        "gravação, e chame essa função. Se o import for só para anotação de "
        "tipo, ponha-o sob `if TYPE_CHECKING:`. Não acrescente o par em "
        "EXCECOES: a lista só pode diminuir."
    )


def test_excecoes_sem_entrada_morta():
    mortas = sorted(EXCECOES - _violacoes_atuais())
    assert not mortas, (
        "Estes pares de EXCECOES não existem mais no código:\n"
        + "\n".join(f"  - {servico} -> {model}" for servico, model in mortas)
        + "\nA fronteira foi corrigida: remova os pares de EXCECOES em "
        "tests/test_fronteiras.py para que o import não possa voltar."
    )


def test_todo_servico_tem_dominio_no_mapa():
    sem_dominio = sorted(
        set(_servicos()) - set(DOMINIO_DO_SERVICO) - CAMADA_DE_LEITURA - set(FORA_DO_MAPA)
    )
    assert not sem_dominio, (
        f"Serviço sem domínio no mapa: {sem_dominio}. Acrescente-o em "
        "DOMINIO_DO_SERVICO (seção 2.1 do plano ARQ-01) para que a regra da "
        "ADR-008 valha também para ele."
    )
    inexistentes = sorted(
        (set(DOMINIO_DO_SERVICO) | CAMADA_DE_LEITURA | set(FORA_DO_MAPA)) - set(_servicos())
    )
    assert not inexistentes, (
        f"O mapa cita serviços que não existem mais: {inexistentes}. Tire-os do mapa."
    )


def test_todo_model_importado_tem_dono():
    nucleo = _nucleo_compartilhado()
    sem_dono = sorted(
        f"{servico} importa {nome}"
        for servico, imports in _imports_de_todos().items()
        for nome in imports.nomes_de_models - nucleo - set(DONO_DO_MODEL)
    )
    assert not sem_dono, (
        f"Model sem domínio no mapa: {sem_dono}. Acrescente-o em DONO_DO_MODEL "
        "(seção 2.1 do plano ARQ-01); sem dono não há como verificar a fronteira."
    )


def test_imports_de_models_sao_verificaveis():
    problemas = sorted(
        f"{servico}: {item}"
        for servico, imports in _imports_de_todos().items()
        for item in imports.nao_verificaveis
    )
    assert not problemas, (
        f"Import de src.models que o teste não consegue ler: {problemas}. Use "
        "`from src.models import Nome`, para que a fronteira possa ser conferida."
    )


def test_modulos_fora_do_mapa_nao_usam_models():
    # A isenção de FORA_DO_MAPA vale porque esses módulos não tocam tabela;
    # se passarem a tocar, precisam de domínio.
    imports = _imports_de_todos()
    nucleo = _nucleo_compartilhado()
    usando = {
        nome: sorted(imports[nome].nomes_de_models - nucleo)
        for nome in FORA_DO_MAPA
        if nome in imports and imports[nome].nomes_de_models - nucleo
    }
    assert not usando, (
        f"Módulo fora do mapa importando model: {usando}. Dê a ele um domínio em "
        "DOMINIO_DO_SERVICO."
    )


def test_camada_de_leitura_nao_grava():
    servicos = _servicos()
    gravacoes = {
        nome: achados
        for nome in sorted(CAMADA_DE_LEITURA)
        if (achados := encontrar_gravacoes(servicos[nome].read_text(encoding="utf-8")))
    }
    assert not gravacoes, (
        f"A camada de leitura gravou no banco: {gravacoes}. dashboard_service e "
        "metric_service só são isentos da regra de fronteira porque só leem "
        "(seção 2.3 do plano ARQ-01). Mova a gravação para o serviço dono do model."
    )


def test_sem_ciclo_de_import_entre_servicos():
    grafo = {nome: imports.servicos_no_modulo for nome, imports in _imports_de_todos().items()}
    ciclos = encontrar_ciclos(grafo)
    novos = sorted(sorted(c) for c in ciclos - CICLOS_CONHECIDOS)
    assert not novos, (
        f"Ciclo de import entre serviços: {novos}. Um serviço que chama outro "
        "não pode ser importado por ele no nível do módulo. Mova a função para "
        "o dono certo ou faça o import dentro da função que o usa."
    )
    mortos = sorted(sorted(c) for c in CICLOS_CONHECIDOS - ciclos)
    assert not mortos, f"Ciclos de CICLOS_CONHECIDOS que não existem mais: {mortos}. Remova-os."


# ==========================================================================
# Os detectores acima precisam enxergar o que dizem enxergar; sem estes
# testes, um detector quebrado passaria a trava em silêncio.
# ==========================================================================
def test_leitor_conta_import_em_funcao_e_ignora_type_checking():
    codigo = (
        "from typing import TYPE_CHECKING\n"
        "from src.models import Post, Platform\n"
        "from src.models.campaign import Campaign\n"
        "from ..models import Report\n"
        "from src.services import user_service\n"
        "if TYPE_CHECKING:\n"
        "    from src.models import Influencer\n"
        "    from src.services import post_service\n"
        "else:\n"
        "    from src.models import Comment\n"
        "def f():\n"
        "    from src.models import AIAnalysis\n"
        "    from src.services import auth_service\n"
    )
    resultado = ler_imports(codigo, {"user_service", "post_service", "auth_service"})
    assert resultado.nomes_de_models == {
        "Post", "Platform", "Campaign", "Report", "Comment", "AIAnalysis"
    }
    assert resultado.servicos_no_modulo == {"user_service"}


def test_leitor_recusa_import_que_nao_da_para_conferir():
    resultado = ler_imports("import src.models\nfrom src.models import *\n", set())
    assert len(resultado.nao_verificaveis) == 2


def test_detector_de_gravacao():
    assert encontrar_gravacoes(
        "from sqlalchemy import select\n"
        "db.session.scalars(select(X))\n"
        "d = {}\nd.update(a=1)\n"
        "db.session.execute(text('SELECT 1'))\n"
    ) == []
    achados = encontrar_gravacoes(
        "import sqlalchemy as sa\n"
        "from sqlalchemy import update as upd, delete\n"
        "db.session.add(x)\n"
        "db.session.commit()\n"
        "db.session.execute(upd(X).values(a=1))\n"
        "db.session.execute(delete(X))\n"
        "db.session.execute(sa.insert(X))\n"
        "X.query.filter_by(a=1).delete()\n"
        "db.session.execute(text('UPDATE x SET a = 1'))\n"
    )
    assert len(achados) == 7


def test_detector_de_ciclo():
    assert encontrar_ciclos({"a": {"b"}, "b": {"c"}, "c": set()}) == set()
    assert encontrar_ciclos({"a": {"b"}, "b": {"c"}, "c": {"a"}, "d": {"a"}}) == {
        frozenset({"a", "b", "c"})
    }
    assert encontrar_ciclos({"a": {"a"}}) == {frozenset({"a"})}
