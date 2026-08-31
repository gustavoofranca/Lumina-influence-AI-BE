"""Varredura 5 (estatica) da bateria: texto que o usuario le sem passar por t().

Dois alvos: literal entre >texto< no JSX e os atributos que chegam ao usuario
(placeholder, title, aria-label, alt, label). Ignora o que e claramente
identidade visual, nome proprio ou fragmento tecnico.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(sys.argv[1] if len(sys.argv) > 1 else "src")
ENTRE_TAGS = re.compile(r">\s*([A-Za-zÀ-ÿ][^<>{}\n]{2,60}?)\s*<")
ATRIBUTO = re.compile(r'\b(placeholder|title|aria-label|alt|label)\s*=\s*"([^"{}]{3,60})"')
# Marca, nome de fonte e termos de identidade nao sao interface traduzivel.
EXCECOES = {
    "Lumina", "Lumina Influence AI", "Influence AI", "React", "Vite", "Tailwind",
    "i18next", "Space Grotesk", "Inter", "JetBrains Mono", "Growth Trajectory",
    "Network Resonance",
}
SO_TECNICO = re.compile(r"^[\s\d\W_]+$|^[a-z][a-zA-Z]*$|^https?://")


def relevante(texto: str) -> bool:
    t = texto.strip()
    if t in EXCECOES or SO_TECNICO.match(t):
        return False
    return bool(re.search(r"[A-Za-zÀ-ÿ]{3,}", t))


def main() -> int:
    achados = []
    for arq in sorted(RAIZ.rglob("*.jsx")):
        texto = arq.read_text(encoding="utf-8")
        for regex, grupo in ((ENTRE_TAGS, 1), (ATRIBUTO, 2)):
            for m in regex.finditer(texto):
                valor = m.group(grupo)
                if not relevante(valor):
                    continue
                linha = texto[:m.start()].count("\n") + 1
                achados.append((str(arq), linha, valor.strip()))
    for arq, linha, valor in achados:
        print(f"{arq}:{linha}: {valor!r}")
    print(f"\n{len(achados)} literal(is) fora do t()")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
