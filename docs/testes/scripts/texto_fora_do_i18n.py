"""Varredura 5 (estatica) da bateria: texto que o usuario le sem passar por t().

Quatro alvos:

1. literal entre >texto< no JSX;
2. atributos que chegam ao usuario (placeholder, title, aria-label, alt, label);
3. **texto colado a uma expressao** — `{valor} seguidores<`. O primeiro alvo
   procura `>texto<` e nao ve isso: foi assim que "seguidores", fixo em
   portugues, sobreviveu a duas auditorias de idioma no cabecalho do criador;
4. **string dentro de handler e de chamada** — `setToast({ message: '...' })`,
   `alert('...')`, `throw new Error('...')` com texto de interface. Nao aparece
   entre `>` e `<` nem em atributo, e sobreviveu as mesmas duas auditorias.

Os alvos 3 e 4 nasceram dos pontos cegos que a propria bateria registrou em
31/08. Ignora o que e claramente identidade visual, nome proprio ou fragmento
tecnico.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

RAIZ = Path(sys.argv[1] if len(sys.argv) > 1 else "src")
ENTRE_TAGS = re.compile(r">\s*([A-Za-zÀ-ÿ][^<>{}\n]{2,60}?)\s*<")
ATRIBUTO = re.compile(r'\b(placeholder|title|aria-label|alt|label)\s*=\s*"([^"{}]{3,60})"')
# `{expr} texto<` — o alvo 1 exige `>` antes do texto e perde exatamente isto.
APOS_EXPRESSAO = re.compile(r"\}\s*([A-Za-zÀ-ÿ][^<>{}\n]{2,60}?)\s*<")
# String de interface passada a funcao: mensagem de toast, de alerta, de erro.
EM_CHAMADA = re.compile(
    r"(?:message|description|title|label|texto|mensagem)\s*:\s*"
    r"['\"]([A-Za-zÀ-ÿ][^'\"\n]{4,80})['\"]"
    r"|(?:alert|confirm)\(\s*['\"]([A-Za-zÀ-ÿ][^'\"\n]{4,80})['\"]"
)
# Marca, nome de fonte e termos de identidade nao sao interface traduzivel.
EXCECOES = {
    "Lumina", "Lumina Influence AI", "Influence AI", "React", "Vite", "Tailwind",
    "i18next", "Space Grotesk", "Inter", "JetBrains Mono", "Growth Trajectory",
    "Network Resonance",
}
# Descartar `^[a-z][a-zA-Z]*$` inteiro era o buraco: a regra existia para
# ignorar identificador (`onClick`, `flex`), e junto ignorava **qualquer palavra
# minuscula solta** — inclusive "seguidores", que ficou fixo em portugues no
# cabecalho do criador e passou por duas auditorias de idioma. Agora so cai
# fora o que tem cara de identificador: camelCase, ou palavra curta demais para
# ser texto de interface.
SO_TECNICO = re.compile(r"^[\s\d\W_]+$|^[a-z][a-z]{0,2}$|^[a-z]+[A-Z]\w*$|^https?://")
# O alvo 3 casa `}` + texto + `<`, e isso inclui codigo: `} return ( <div`.
# Frase de interface nao tem parentese solto, atribuicao nem palavra-chave de
# JavaScript no comeco — filtrar por isso e mais barato que parsear.
PARECE_CODIGO = re.compile(
    r"[(){}=;]|&&|\|\||=>|"
    r"^(?:return|if|else|const|let|var|function|export|import|for|while|switch|"
    r"case|await|async|new|typeof|delete)\b",
    re.IGNORECASE,
)


def nomes_de_chave(raiz: Path) -> set[str]:
    """Todo nome de chave dos locales, em qualquer profundidade.

    Serve para separar texto de **fragmento de chave**. O caso concreto:
    `label: 'accepted'` alimenta ``t(`...recommendations.${label}`)``, ou seja,
    'accepted' e o nome de uma chave e nao uma palavra que o usuario le. Sem
    esta consulta o alvo 4 acusa todo padrao desse tipo, e um relatorio cheio de
    falso positivo e um relatorio que ninguem le.
    """
    nomes: set[str] = set()

    def desce(obj):
        if isinstance(obj, dict):
            for chave, valor in obj.items():
                nomes.add(chave)
                desce(valor)

    for arquivo in raiz.rglob("locales/*.json"):
        try:
            desce(json.loads(arquivo.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return nomes


CHAVES: set[str] = set()


def relevante(texto: str) -> bool:
    t = texto.strip()
    if t in EXCECOES or SO_TECNICO.match(t) or PARECE_CODIGO.search(t):
        return False
    if t in CHAVES:
        return False
    return bool(re.search(r"[A-Za-zÀ-ÿ]{3,}", t))


def main() -> int:
    global CHAVES
    CHAVES = nomes_de_chave(RAIZ)
    achados = []
    # `.js` entra por causa do alvo 4: servico e hook tambem montam mensagem.
    arquivos = sorted([*RAIZ.rglob("*.jsx"), *RAIZ.rglob("*.js")])
    for arq in arquivos:
        texto = arq.read_text(encoding="utf-8")
        for regex, grupos in (
            (ENTRE_TAGS, (1,)),
            (ATRIBUTO, (2,)),
            (APOS_EXPRESSAO, (1,)),
            (EM_CHAMADA, (1, 2)),
        ):
            for m in regex.finditer(texto):
                valor = next((m.group(g) for g in grupos if m.group(g)), None)
                if valor is None or not relevante(valor):
                    continue
                linha = texto[:m.start()].count("\n") + 1
                achados.append((str(arq), linha, valor.strip()))
    for arq, linha, valor in achados:
        print(f"{arq}:{linha}: {valor!r}")
    print(f"\n{len(achados)} literal(is) fora do t()")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
