"""Marca embutida no PDF.

O xhtml2pdf é chamado sem `link_callback`, então caminho relativo de imagem não
resolve — a marca entra como data URI. É lida do disco uma vez e fica em cache:
são ~9 KB, e reler a cada relatório seria trabalho por nada.
"""
from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

_ARQUIVO = Path(__file__).resolve().parent.parent / "assets" / "brand" / "lumina-symbol-black.png"


@lru_cache(maxsize=1)
def marca_data_uri() -> str:
    """Símbolo da marca em preto, pronto para o `src` de um <img>.

    Preto porque a folha do relatório é branca. Devolve string vazia se o
    arquivo faltar — um relatório sem logo é melhor que um relatório que falha.
    """
    try:
        dados = _ARQUIVO.read_bytes()
    except OSError:
        return ""
    return "data:image/png;base64," + base64.b64encode(dados).decode("ascii")
