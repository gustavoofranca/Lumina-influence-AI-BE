"""Varredura 5 da bateria: a fronteira entre o que a tela chama e o que a API tem.

Duas direções, dois defeitos diferentes:

- **Fantasma** — a interface chama um caminho que não existe. `npm run build`
  passa, o teste de unidade passa, e a tela quebra em runtime na frente de
  quem estiver olhando. É o mesmo modo de falha do `refetch is not defined` e
  do import faltando do `ExcluirCriadorModal`: só aparece executando.
- **Órfã** — a rota existe, está na spec, e nenhuma tela a consome. Não quebra
  nada; é superfície de API sem dono, que ou é funcionalidade não entregue ou
  é endpoint que deveria ter saído junto com a tela que o usava.

O `test_toda_rota_esta_na_spec_openapi` já cobre app↔spec nas duas direções.
Esta varredura cobre o terceiro lado do triângulo, front↔app, que é o único
que nenhum teste atravessa — os dois lados vivem em repositórios diferentes.

As rotas vêm da spec da API em execução, não de `import create_app`: a spec é
o contrato que um integrador enxerga, os dois lados do triângulo já são
verificados por `test_toda_rota_esta_na_spec_openapi`, e assim a varredura roda
no host — onde o front existe — sem depender do Flask estar instalado ali.

Rodar (com a API de pé):
    python3 docs/testes/scripts/rota_orfa.py ../Lumina-Influence-AI-FE/src
    python3 docs/testes/scripts/rota_orfa.py --verificar-regressao
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from varredura import Filtro, verificar_regressao

PREFIXO = "/api/v1"
SPEC_PADRAO = "http://localhost:5000/api/v1/openapi.json"

# Rotas que legitimamente não têm chamada no cliente HTTP. Cada uma com o
# motivo: exceção sem motivo escrito volta a ser exceção sem motivo nenhum.
SEM_CONSUMIDOR_POR_DESENHO = {
    "get /api/v1/auth/google/login": "redirecionamento do browser, não passa pelo cliente",
    "get /api/v1/auth/google/callback": "o provedor OAuth é quem chama",
    "get /api/v1/auth/microsoft/login": "redirecionamento do browser, não passa pelo cliente",
    "get /api/v1/auth/microsoft/callback": "o provedor OAuth é quem chama",
    "get /api/v1/integrations/{id}/callback": "a rede social é quem chama",
    "get /api/v1/health": "monitoração e docker healthcheck",
    "get /api/v1/docs": "Swagger UI, aberto no browser",
    "get /api/v1/openapi.json": "consumido pelo Swagger UI e pelos testes",
    "get /static/{id}": "servido pelo Flask, não chamado por fetch",
}

# Espelha `ROTAS_FORA_DA_SPEC` em tests/test_hardening.py: rotas que existem no
# app e ficam fora do contrato de propósito. Chamá-las não quebra a tela, mas o
# front passa a depender de algo que nenhum integrador enxerga — categoria
# própria, não fantasma e não silêncio.
FORA_DO_CONTRATO_POR_DESENHO = {
    "post /api/v1/auth/dev-login": "atalho de demonstração, desligado em staging e produção",
}

# `raw` entra na lista: é como o download do PDF é buscado, com Authorization.
# Ficar de fora fazia `/reports/{id}/download` parecer órfã.
METODOS = ("get", "post", "patch", "put", "delete", "raw")

# O `\s*` antes da aspa é o que enxerga `api.delete(\n  `/caminho/${x}`\n)` —
# quebrar a linha para caber em 100 colunas não pode esconder a chamada. `re.S`
# cobre o caso mais raro do literal que ele próprio atravessa linhas.
CHAMADA = re.compile(
    r"api\.(" + "|".join(METODOS) + r")\s*\(\s*([\"'`])(.*?)\2",
    re.S,
)
# Chamada cujo primeiro argumento não é literal: o caminho vem de variável e
# esta varredura não consegue resolvê-lo. Não pode ser descartada em silêncio.
CHAMADA_NAO_LITERAL = re.compile(r"api\.(" + "|".join(METODOS) + r")\s*\(\s*[^\"'`\s)]")


_FONTE_SPEC = SPEC_PADRAO


def normalizar(caminho: str) -> str:
    """`/influencers/${id}/posts?limit=20` -> `/api/v1/influencers/{id}/posts`."""
    caminho = caminho.split("?", 1)[0]
    caminho = re.sub(r"\$\{[^}]*\}", "{id}", caminho)
    return PREFIXO + caminho


def chamadas_do_front(raiz: Path, filtro: Filtro) -> dict[str, list[str]]:
    """Mapeia `metodo caminho` -> arquivos que chamam."""
    achadas: dict[str, list[str]] = {}
    for arquivo in sorted([*raiz.rglob("*.js"), *raiz.rglob("*.jsx")]):
        if "node_modules" in arquivo.parts:
            continue
        texto = arquivo.read_text(encoding="utf-8")
        for metodo, _aspa, caminho in CHAMADA.findall(texto):
            if not caminho.startswith("/"):
                filtro.descarta("primeiro argumento não é caminho", f"{metodo} {caminho}")
                continue
            # `raw` é sempre GET: é o buscador de binário com Authorization.
            verbo = "get" if metodo == "raw" else metodo
            chave = f"{verbo} {normalizar(caminho)}"
            achadas.setdefault(chave, []).append(str(arquivo))
        for metodo in CHAMADA_NAO_LITERAL.findall(texto):
            achadas.setdefault(f"{metodo} <caminho em variável>", []).append(str(arquivo))
    return achadas


def rotas_da_api(fonte: str = SPEC_PADRAO) -> set[str]:
    """Lê a spec e devolve `metodo caminho` com os parâmetros normalizados."""
    try:
        if fonte.startswith("http"):
            with urllib.request.urlopen(fonte, timeout=10) as resposta:
                spec = json.load(resposta)
        else:
            spec = json.loads(Path(fonte).read_text(encoding="utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as erro:
        raise SystemExit(
            f"não foi possível ler a spec em {fonte}: {erro}\n"
            "Suba a API (docker compose up -d) ou aponte --spec para um arquivo."
        ) from erro

    return {
        f"{metodo} {re.sub(r'{[^}]*}', '{id}', caminho)}"
        for caminho, operacoes in spec["paths"].items()
        for metodo in operacoes
        if metodo in {"get", "post", "patch", "put", "delete"}
    }


def coletar_fantasmas(raiz: Path) -> list[str]:
    """Só a direção que quebra a tela — é a que a regressão precisa cobrar."""
    reais = rotas_da_api(_FONTE_SPEC)
    chamadas = chamadas_do_front(raiz, Filtro())
    return [c for c in chamadas if c not in reais and c not in FORA_DO_CONTRATO_POR_DESENHO]


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    global _FONTE_SPEC
    for arg in sys.argv[1:]:
        if arg.startswith("--spec="):
            _FONTE_SPEC = arg.split("=", 1)[1]
    if "--verificar-regressao" in sys.argv:
        return verificar_regressao("rota_orfa", coletar_fantasmas)

    raiz = Path(args[0] if args else "../Lumina-Influence-AI-FE/src")
    if not raiz.is_dir():
        print(f"pasta não encontrada: {raiz}")
        return 2

    filtro = Filtro()
    reais = rotas_da_api(_FONTE_SPEC)
    chamadas = chamadas_do_front(raiz, filtro)

    nao_contratadas = {
        c: f for c, f in chamadas.items() if c in FORA_DO_CONTRATO_POR_DESENHO
    }
    fantasmas = {
        c: f
        for c, f in chamadas.items()
        if c not in reais and c not in FORA_DO_CONTRATO_POR_DESENHO
    }
    orfas = sorted(reais - set(chamadas) - set(SEM_CONSUMIDOR_POR_DESENHO))

    print(f"{len(reais)} rota(s) na API, {len(chamadas)} chamada(s) distinta(s) no front.\n")

    if fantasmas:
        print(f"--- {len(fantasmas)} rota(s) chamada(s) que NÃO existem na API ---")
        print("A tela que executar isto quebra: o build passa, o erro é em runtime.")
        for chamada, arquivos in sorted(fantasmas.items()):
            print(f"  {chamada}")
            for a in sorted(set(arquivos)):
                print(f"      {a}")
    else:
        print("Nenhuma chamada aponta para rota inexistente.")

    if nao_contratadas:
        print(f"\n--- {len(nao_contratadas)} chamada(s) para rota fora do contrato ---")
        print("A rota existe no app, mas não está na spec. Funciona hoje e some")
        print("do dia para a noite sem quebrar nenhum teste de contrato.")
        for chamada, arquivos in sorted(nao_contratadas.items()):
            print(f"  {chamada}  — {FORA_DO_CONTRATO_POR_DESENHO[chamada]}")
            for a in sorted(set(arquivos)):
                print(f"      {a}")

    if orfas:
        print(f"\n--- {len(orfas)} rota(s) sem consumidor no front ---")
        print("Não quebram nada. Ou é funcionalidade que a interface ainda não")
        print("entrega, ou é endpoint que deveria ter saído com a tela que o usava.")
        for rota in orfas:
            print(f"  {rota}")

    filtro.imprimir_relatorio()
    return 1 if fantasmas else 0


if __name__ == "__main__":
    raise SystemExit(main())
