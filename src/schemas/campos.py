"""Tipos de campo reaproveitados pelos schemas de entrada.

Antes desta camada, cada schema declarava `str` com `min_length`/`max_length` e
nada mais. A varredura de 15/10/2026 mostrou o que passava por ali: nome só de
espaços (que cumpre `min_length=1`), caracteres invisíveis, inversão de direção
de texto, marcação HTML, e o byte nulo, que o Postgres recusa e virava erro 500.
Números sem teto estouravam a coluna `BigInteger` pelo mesmo caminho.

A regra de cada tipo mora aqui, uma vez, e os schemas só escolhem o tipo e o
tamanho. Os tamanhos continuam iguais aos das colunas do banco.

Três tipos de texto, porque os campos não pedem a mesma coisa:

- `Nome`: uma linha, sem `<` nem `>` — marca, nome de criador, de agência, de
  pessoa, nicho. Nada disso tem motivo para conter marcação.
- `Linha`: uma linha, pontuação livre — títulos.
- `Texto`: várias linhas — bio, entregáveis.

Todos tiram os espaços das pontas e normalizam o Unicode antes de medir o
tamanho, e todos recusam texto que só tem caractere invisível.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Annotated, Optional
from urllib.parse import urlparse

from pydantic import (
    AfterValidator,
    BeforeValidator,
    Field,
    StrictInt,
    StringConstraints,
)

# Recusar `<` e `>` em nomes é defesa em profundidade, não correção de brecha: a
# tela e o PDF já escapam o texto. Desligar aqui volta a aceitar.
NOME_RECUSA_SINAIS_DE_MARCACAO = True

# Controles C0 e C1. Tabulação, quebra de linha e retorno ficam de fora: o tipo
# `Texto` aceita, e os tipos de uma linha recusam por regra própria.
_CONTROLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_QUEBRA = re.compile(r"[\t\r\n]")
# Embutimento e sobreposição de direção (U+202A–202E, U+2066–2069). Fazem o
# texto aparecer de trás para frente na tela.
_DIRECAO = re.compile(r"[\u202a-\u202e\u2066-\u2069]")
# Largura zero. O ZWJ (U+200D) também é usado dentro de emoji composto, então
# não é recusado por si — só conta como "nada" na checagem de texto em branco.
_INVISIVEL = re.compile(r"[\u200b-\u200d\u2060\ufeff]")
_MARCACAO = re.compile(r"[<>]")

MENSAGEM_EM_BRANCO = "não pode ficar em branco"

# Datas de negócio: campanhas e relatórios. A faixa existe para recusar o ano 1
# e o ano 9999, que passavam, sem impor regra de duração que o negócio não tem.
DATA_MINIMA = date(2000, 1, 1)
DATA_MAXIMA = date(2100, 12, 31)

# R$ 1 bilhão em centavos: acima do que qualquer campanha real orça, e muito
# abaixo do teto do BigInteger, que antes estourava em erro 500.
LIMITE_CENTAVOS = 100_000_000_000
# Dez bilhões — mais que a população do planeta.
LIMITE_SEGUIDORES = 10_000_000_000


def _limpar(valor):
    """Normaliza e tira os espaços das pontas. Não-texto segue para o tipo recusar."""
    if not isinstance(valor, str):
        return valor
    return unicodedata.normalize("NFC", valor).strip()


def _limpar_ou_nulo(valor):
    """Como `_limpar`, mas texto que fica vazio vira `None` — para campo opcional."""
    valor = _limpar(valor)
    if isinstance(valor, str) and not _INVISIVEL.sub("", valor).strip():
        return None
    return valor


def _conferir_conteudo(*, multilinha: bool, aceita_marcacao: bool):
    def conferir(valor: str) -> str:
        if _CONTROLE.search(valor):
            raise ValueError("contém caractere de controle não permitido")
        if not multilinha and _QUEBRA.search(valor):
            raise ValueError("não pode ter quebra de linha")
        if _DIRECAO.search(valor):
            raise ValueError("contém caractere que inverte a direção do texto")
        if not _INVISIVEL.sub("", valor).strip():
            raise ValueError(MENSAGEM_EM_BRANCO)
        if not aceita_marcacao and NOME_RECUSA_SINAIS_DE_MARCACAO and _MARCACAO.search(valor):
            raise ValueError("não pode conter os sinais < ou >")
        return valor
    return conferir


def _texto(maximo: int, *, multilinha: bool, aceita_marcacao: bool):
    return Annotated[
        str,
        BeforeValidator(_limpar),
        StringConstraints(min_length=1, max_length=maximo),
        AfterValidator(_conferir_conteudo(multilinha=multilinha, aceita_marcacao=aceita_marcacao)),
    ]


def _texto_opcional(maximo: int, *, multilinha: bool, aceita_marcacao: bool):
    return Annotated[
        Optional[_texto(maximo, multilinha=multilinha, aceita_marcacao=aceita_marcacao)],
        BeforeValidator(_limpar_ou_nulo),
    ]


def Nome(maximo: int):
    return _texto(maximo, multilinha=False, aceita_marcacao=False)


def NomeOpcional(maximo: int):
    return _texto_opcional(maximo, multilinha=False, aceita_marcacao=False)


def Linha(maximo: int):
    return _texto(maximo, multilinha=False, aceita_marcacao=True)


def LinhaOpcional(maximo: int):
    return _texto_opcional(maximo, multilinha=False, aceita_marcacao=True)


def TextoOpcional(maximo: int):
    return _texto_opcional(maximo, multilinha=True, aceita_marcacao=True)


def _identificador(maximo: int):
    """Handle e id de plataforma: sem espaço, só letra, número e `._-`.

    `\\w` em Python é Unicode — aceita letra acentuada e de outros alfabetos,
    que o YouTube permite em handle.
    """
    return Annotated[
        str,
        BeforeValidator(_limpar),
        StringConstraints(min_length=1, max_length=maximo, pattern=r"^@?[\w.\-]+$"),
    ]


Handle = _identificador(120)
IdDePlataforma = Annotated[Optional[_identificador(120)], BeforeValidator(_limpar_ou_nulo)]


# `StrictInt` recusa `"100"` e `true`, que o modo tolerante convertia em
# silêncio — `true` virava orçamento de um centavo.
Centavos = Annotated[StrictInt, Field(ge=0, le=LIMITE_CENTAVOS)]
Seguidores = Annotated[StrictInt, Field(ge=0, le=LIMITE_SEGUIDORES)]


def _na_faixa(valor: date) -> date:
    if not DATA_MINIMA <= valor <= DATA_MAXIMA:
        raise ValueError(
            f"deve estar entre {DATA_MINIMA:%d/%m/%Y} e {DATA_MAXIMA:%d/%m/%Y}"
        )
    return valor


DataDeNegocio = Annotated[date, AfterValidator(_na_faixa)]


def periodo_em_ordem(inicio: date | None, fim: date | None) -> None:
    """Levanta se o fim vem antes do início. Usado como validador de `period_end`."""
    if inicio is not None and fim is not None and fim < inicio:
        raise ValueError("o fim não pode ser antes do início")


# ---------------------------------------------------------------- CNPJ
_CNPJ_FORMATO = re.compile(r"^[\d.\-/ ]+$")


def _normalizar_cnpj(valor):
    """Aceita com ou sem máscara e grava sempre com máscara.

    Confere só o formato. O dígito verificador é conferido no serviço, e só
    quando o CNPJ muda: a tela de Agência reenvia o CNPJ a cada salvamento, e
    um CNPJ gravado antes desta regra — o da agência principal em produção tem
    dígito errado — não pode impedir a pessoa de mudar o nome da agência.
    """
    valor = _limpar(valor)
    if valor is None or valor == "":
        return None
    if not isinstance(valor, str):
        return valor
    if not _CNPJ_FORMATO.match(valor):
        raise ValueError("deve conter só números, pontos, barra e hífen")
    digitos = re.sub(r"\D", "", valor)
    if len(digitos) != 14:
        raise ValueError("deve ter 14 dígitos")
    return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"


def cnpj_valido(cnpj: str) -> bool:
    """Confere os dois dígitos verificadores. Recebe com ou sem máscara."""
    digitos = re.sub(r"\D", "", cnpj)
    if len(digitos) != 14 or len(set(digitos)) == 1:
        return False

    def digito(base: str) -> str:
        pesos = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2][-len(base):]
        resto = sum(int(d) * p for d, p in zip(base, pesos)) % 11
        return "0" if resto < 2 else str(11 - resto)

    primeiro = digito(digitos[:12])
    return digitos[12:] == primeiro + digito(digitos[:12] + primeiro)


Cnpj = Annotated[Optional[str], BeforeValidator(_normalizar_cnpj)]


# ---------------------------------------------------------------- URL de imagem
def _https(valor: str) -> str:
    partes = urlparse(valor)
    if partes.scheme != "https" or not partes.netloc or " " in valor:
        raise ValueError("deve ser um endereço que comece com https://")
    return valor


UrlHttpsOpcional = Annotated[
    Optional[Annotated[str, StringConstraints(max_length=500), AfterValidator(_https)]],
    BeforeValidator(_limpar_ou_nulo),
]
