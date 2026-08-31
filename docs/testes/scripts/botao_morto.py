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

RAIZ = Path(sys.argv[1] if len(sys.argv) > 1 else "src")
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


def main() -> int:
    achados = []
    for arq in sorted(RAIZ.rglob("*.jsx")):
        texto = arq.read_text(encoding="utf-8")
        for m in ABERTURA.finditer(texto):
            tag, _ = tag_completa(texto, m.start())
            if any(a in tag for a in ACOES) or "disabled" in tag:
                continue
            if envolto_em_link(texto, m.start()):
                continue
            linha = texto[:m.start()].count("\n") + 1
            achados.append((str(arq), linha, " ".join(tag.split())[:90]))
    for arq, linha, tag in achados:
        print(f"{arq}:{linha}: {tag}")
    print(f"\n{len(achados)} botao(oes) sem acao aparente")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
