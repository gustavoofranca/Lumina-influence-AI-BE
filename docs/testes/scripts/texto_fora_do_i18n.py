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

from varredura import Filtro, verificar_regressao

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
MODO_REGRESSAO = "--verificar-regressao" in sys.argv
RAIZ = Path(ARGS[0] if ARGS else "src")
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
#
# **Esta regra vale so onde se le JSX cru** (alvos 1 e 3): o `>` que fecha uma
# tag e o `}` que fecha uma expressao sao ambos seguidos de codigo. Nao vale
# para os alvos 2 e 4, que leem string entre aspas — ali nao ha codigo para
# vazar, e a regra so tira texto legitimo. Aplica-la a todos cegava os outros: sem
# `re.IGNORECASE` "Export" ainda casaria com a palavra-chave `export`, e o
# parentese sozinho descartava "Background solido (neutral-800)...", que e
# texto de interface legitimo. Filtro escrito para um alvo nao pode filtrar os
# demais — foi o relatorio de descartes que expos isso, na primeira execucao.
#
# Sem IGNORECASE de proposito: palavra-chave de JavaScript e minuscula, e
# "Export", "Import", "New", "Case" e "Delete" sao rotulos de botao.
ALVOS_COM_CODIGO_CRU = ("entre_tags", "apos_expressao")
PARECE_CODIGO = re.compile(
    r"[{}=;]|&&|\|\||=>|"
    r"^(?:return|if|else|const|let|var|function|export|import|for|while|switch|"
    r"case|await|async|new|typeof|delete)\b"
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
FILTRO = Filtro()


def relevante(texto: str, *, alvo: str = "") -> bool:
    """Cada descarte é registrado por regra — ver `varredura.Filtro`.

    Um `return False` mudo aqui foi o que cegou esta varredura por duas
    auditorias: a regra de identificador comia palavra minúscula solta, e o
    relatório limpo parecia bom resultado.

    `alvo` existe porque **filtro é específico do alvo**. A guarda contra código
    só faz sentido onde código pode vazar (o padrão `}` … `<`); aplicá-la ao
    texto entre tags descartava frase de interface com parêntese.
    """
    t = texto.strip()
    if t in EXCECOES:
        return not FILTRO.descarta("identidade visual / nome próprio", t)
    if SO_TECNICO.match(t):
        return not FILTRO.descarta("parece identificador ou fragmento técnico", t)
    if alvo in ALVOS_COM_CODIGO_CRU and PARECE_CODIGO.search(t):
        return not FILTRO.descarta("parece código (só nos alvos que leem JSX cru)", t)
    if t in CHAVES:
        return not FILTRO.descarta("é nome de chave do i18n", t)
    if not re.search(r"[A-Za-zÀ-ÿ]{3,}", t):
        return not FILTRO.descarta("sem palavra de 3+ letras", t)
    return True


def coletar(raiz: Path) -> list[str]:
    """Só os textos achados — usado pela verificação de regressão."""
    global CHAVES, RAIZ
    anterior, RAIZ = RAIZ, raiz
    CHAVES = nomes_de_chave(raiz)
    try:
        return [valor for _, _, valor in _varrer(raiz)]
    finally:
        RAIZ = anterior


def _varrer(raiz: Path):
    achados = []
    # `.js` entra por causa do alvo 4: servico e hook tambem montam mensagem.
    arquivos = sorted([*raiz.rglob("*.jsx"), *raiz.rglob("*.js")])
    for arq in arquivos:
        texto = arq.read_text(encoding="utf-8")
        for regex, grupos, alvo in (
            (ENTRE_TAGS, (1,), "entre_tags"),
            (ATRIBUTO, (2,), "atributo"),
            (APOS_EXPRESSAO, (1,), "apos_expressao"),
            (EM_CHAMADA, (1, 2), "em_chamada"),
        ):
            for m in regex.finditer(texto):
                valor = next((m.group(g) for g in grupos if m.group(g)), None)
                if valor is None or not relevante(valor, alvo=alvo):
                    continue
                linha = texto[:m.start()].count("\n") + 1
                achados.append((str(arq), linha, valor.strip()))
    return achados


def main() -> int:
    global CHAVES
    if MODO_REGRESSAO:
        return verificar_regressao("texto_fora_do_i18n", coletar)

    CHAVES = nomes_de_chave(RAIZ)
    achados = _varrer(RAIZ)
    for arq, linha, valor in achados:
        print(f"{arq}:{linha}: {valor!r}")
    print(f"\n{len(achados)} literal(is) fora do t()")
    FILTRO.imprimir_relatorio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
