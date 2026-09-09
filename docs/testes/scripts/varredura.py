"""Apoio comum das varreduras estáticas: filtro auditável e prova de regressão.

Existe por causa de um defeito de método, não de código. A varredura de i18n
descartava `^[a-z][a-zA-Z]*$` para ignorar identificador, e junto ignorava
**qualquer palavra minúscula solta** — inclusive "seguidores", fixo em português
no cabeçalho do criador, que sobreviveu a duas auditorias de idioma.

O que torna esse erro caro é onde ele mora: **uma varredura falha em silêncio
pelo lado da exclusão, não pelo lado da detecção.** Quando a detecção erra, o
relatório enche de ruído e alguém percebe. Quando a exclusão erra, o relatório
fica limpo — e limpo é exatamente o que se espera de um relatório bom. Não
aparece lendo a lista de achados; só aparece lendo o filtro.

Daí as duas peças aqui:

- `Filtro` registra **por regra** tudo que foi descartado e imprime o resumo
  junto dos achados. O filtro passa a ser lido toda vez que a varredura roda,
  em vez de nunca.
- `verificar_regressao` roda a varredura contra amostras que contêm defeitos
  **reais**, já vividos, e falha se algum deixar de ser visto. É o que impede
  que um ajuste de filtro volte a cegar a varredura sem ninguém notar.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

PASTA_REGRESSAO = Path(__file__).parent / "regressao"
MANIFESTO = PASTA_REGRESSAO / "esperado.json"


class Filtro:
    """Contabiliza descartes por regra, para que o filtro seja auditável."""

    def __init__(self) -> None:
        self._descartes: dict[str, list[str]] = defaultdict(list)

    def descarta(self, regra: str, valor: str) -> bool:
        """Registra e devolve True, para uso direto em `if`."""
        self._descartes[regra].append(str(valor)[:60])
        return True

    def imprimir_relatorio(self, *, exemplos: int = 4) -> None:
        if not self._descartes:
            print("\nNenhum candidato descartado.")
            return
        total = sum(len(v) for v in self._descartes.values())
        print(f"\n--- filtro: {total} candidato(s) descartado(s) por regra ---")
        print("Leia esta seção. Regra que descarta demais cega a varredura, e o")
        print("sintoma é um relatório limpo — indistinguível de um sistema são.")
        for regra, valores in sorted(self._descartes.items(), key=lambda p: -len(p[1])):
            amostra = ", ".join(repr(v) for v in sorted(set(valores))[:exemplos])
            resto = len(set(valores)) - exemplos
            sufixo = f", +{resto}" if resto > 0 else ""
            print(f"  {regra}: {len(valores)}  [{amostra}{sufixo}]")


def verificar_regressao(nome: str, coletar) -> int:
    """Roda `coletar(pasta)` sobre as amostras e cobra os defeitos conhecidos.

    `coletar` devolve uma lista de textos achados. O manifesto diz o que
    precisa aparecer; falta de qualquer um significa que a varredura regrediu.
    """
    esperado = json.loads(MANIFESTO.read_text(encoding="utf-8")).get(nome, [])
    if not esperado:
        print(f"[regressao] nenhum caso declarado para {nome!r} em {MANIFESTO}")
        return 1

    achados = [str(a) for a in coletar(PASTA_REGRESSAO)]
    faltando = [e for e in esperado if not any(e in a for a in achados)]

    for caso in esperado:
        marca = "FALTOU" if caso in faltando else "ok"
        print(f"  [{marca}] {caso}")
    if faltando:
        print(f"\n[regressao] {len(faltando)} defeito(s) conhecido(s) deixaram de ser vistos.")
        print("A varredura regrediu — provavelmente uma regra de exclusão ficou larga demais.")
        return 1
    print(f"\n[regressao] {len(esperado)} defeito(s) conhecido(s) continuam visíveis.")
    return 0


def sem_comentarios(texto: str) -> str:
    """Apaga comentario de JS/JSX preservando tamanho e quebras de linha.

    Existe por um falso positivo real: a varredura de botao morto reportou
    `landing/FaqSection.jsx:19`, que e a linha `<button aria-expanded>` escrita
    **dentro do comentario** do arquivo, explicando por que nao se usou
    `<details>`. O botao de verdade, dez linhas abaixo, tem `onClick`.

    Comentario e onde o autor escreve o codigo que **nao** existe — exemplo,
    alternativa descartada, trecho antigo. Varredura que le comentario acha
    justamente o que foi decidido nao fazer.

    Cada caractere apagado vira espaco e cada `\n` sobrevive, entao offset e
    numero de linha continuam batendo com o arquivo original — quem chama
    reporta a posicao certa sem precisar de mapa de conversao.

    O estado de string e respeitado, senao `"https://exemplo"` perderia metade
    da URL para a regra de `//` — que e o mesmo erro de exclusao larga, agora do
    lado do detector.
    """
    saida = []
    i = 0
    n = len(texto)
    aspas = None
    while i < n:
        c = texto[i]
        if aspas:
            saida.append(c)
            if c == "\\" and i + 1 < n:      # escape dentro de string
                saida.append(texto[i + 1])
                i += 2
                continue
            if c == aspas:
                aspas = None
            i += 1
            continue
        if c in "\"'`":
            aspas = c
            saida.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and texto[i + 1] == "/":
            while i < n and texto[i] != "\n":
                saida.append(" ")
                i += 1
            continue
        if c == "/" and i + 1 < n and texto[i + 1] == "*":
            fim = texto.find("*/", i + 2)
            fim = n if fim == -1 else fim + 2
            for j in range(i, fim):
                saida.append("\n" if texto[j] == "\n" else " ")
            i = fim
            continue
        saida.append(c)
        i += 1
    return "".join(saida)
