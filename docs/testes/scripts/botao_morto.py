"""Varredura 4 da bateria: botao sem acao atras.

Percorre os .jsx do front procurando <button> nativo e <Button> do design
system e reporta os que nao tem onClick, type="submit", asChild/href/to nem
disabled. A tag e multilinha e contem chaves, entao o parser conta {} ate o
'>' de profundidade zero — casar [^>]*> quebra em onClick={() => ...}.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from varredura import Filtro, verificar_regressao

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
MODO_REGRESSAO = "--verificar-regressao" in sys.argv
RAIZ = Path(ARGS[0] if ARGS else "src")
FILTRO = Filtro()
ABERTURA = re.compile(r"<(button|Button)(?=[\s/>])")
ACOES = ("onClick", 'type="submit"', "type={'submit'}", "asChild", "href", "to=", "onMouseDown")


def tag_completa(texto: str, i: int) -> tuple[str, int]:
    """Devolve a tag a partir de '<', respeitando chaves e strings."""
    prof = 0
    aspas = None
    j = i
    while j < len(texto):
        c = texto[j]
        if aspas:
            if c == aspas:
                aspas = None
        elif c in "\"'`":
            aspas = c
        elif c == "{":
            prof += 1
        elif c == "}":
            prof -= 1
        elif c == ">" and prof == 0:
            return texto[i:j + 1], j + 1
        j += 1
    return texto[i:], len(texto)


def envolto_em_link(texto: str, inicio: int) -> bool:
    """Botao dentro de <Link>/<NavLink>/<a> herda a navegacao do pai."""
    antes = texto[max(0, inicio - 400):inicio]
    for tag in ("<Link", "<NavLink", "<a "):
        pos = antes.rfind(tag)
        if pos != -1 and "</" not in antes[pos:]:
            return True
    return False


def _varrer(raiz: Path):
    """Cada descarte vai para o filtro auditavel, e nao para um `continue` mudo.

    A razao esta em `varredura.py`: varredura falha em silencio pelo lado da
    exclusao. Aqui um `disabled` que casasse por engano — ou um `<Link>` mal
    detectado 400 caracteres acima — esconderia botao morto de verdade, e o
    sintoma seria um relatorio limpo.
    """
    achados = []
    for arq in sorted(raiz.rglob("*.jsx")):
        texto = arq.read_text(encoding="utf-8")
        for m in ABERTURA.finditer(texto):
            tag, _ = tag_completa(texto, m.start())
            resumo = " ".join(tag.split())[:90]
            acao = next((a for a in ACOES if a in tag), None)
            if acao:
                FILTRO.descarta(f"tem acao: {acao}", resumo)
                continue
            if "disabled" in tag:
                FILTRO.descarta("marcado disabled", resumo)
                continue
            if envolto_em_link(texto, m.start()):
                FILTRO.descarta("dentro de <Link>/<a> (herda navegacao)", resumo)
                continue
            linha = texto[:m.start()].count("\n") + 1
            achados.append((str(arq), linha, resumo))
    return achados


def coletar(raiz: Path) -> list[str]:
    return [tag for _, _, tag in _varrer(raiz)]


def main() -> int:
    if MODO_REGRESSAO:
        return verificar_regressao("botao_morto", coletar)

    achados = _varrer(RAIZ)
    for arq, linha, tag in achados:
        print(f"{arq}:{linha}: {tag}")
    print(f"\n{len(achados)} botao(oes) sem acao aparente")
    FILTRO.imprimir_relatorio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
