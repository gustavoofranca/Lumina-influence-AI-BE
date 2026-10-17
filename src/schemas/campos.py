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
    EmailStr,
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


# ---------------------------------------------------------------- links
# Domínios que, depois de um ponto, fazem um texto ser lido como endereço. A
# lista é fechada de propósito: "Ltda." e "Jr." terminam em ponto e não são
# link, e uma regra aberta ("qualquer coisa.qualquer coisa") recusaria nome
# legítimo. O custo aceito, decidido com o usuário em 15/10/2026: marca cujo
# nome é um domínio ("Booking.com", "Lumina.AI") também é recusada.
_TLDS_DE_LINK = frozenset({
    "com", "br", "net", "org", "io", "app", "ai", "co", "dev", "me", "info",
    "site", "online", "store", "xyz", "tv", "gg", "ly",
})
_PONTUACAO_DE_BORDA = "()[]{}<>\"'.,;:!?"


def contem_link(texto: str) -> bool:
    """True se algum pedaço do texto parece endereço web ou e-mail.

    Corta por espaço e confere cada pedaço, sem expressão regular: o tempo é
    linear no tamanho do texto, e não há entrada que faça a conferência
    demorar (ReDoS).
    """
    for bruto in texto.lower().split():
        token = bruto.strip(_PONTUACAO_DE_BORDA)
        if not token:
            continue
        if token.startswith(("http://", "https://", "www.")) or "://" in token:
            return True
        partes = token.split("/")[0].split(".")
        if len(partes) >= 2 and partes[-1] in _TLDS_DE_LINK and all(partes[:-1]):
            return True
    return False


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
        # Nome de pessoa, de agência, de marca, de criador e nicho: nenhum deles
        # é lugar de endereço. Títulos e textos longos (`aceita_marcacao`)
        # continuam livres.
        if not aceita_marcacao and contem_link(valor):
            raise ValueError("não use links neste campo")
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


# ---------------------------------------------------------------- pessoa e empresa
_SEPARADORES_DE_NOME = frozenset(" '’.-")
_PONTUACAO_DE_EMPRESA = frozenset(" &.,'’-/()+")


def _e_letra(c: str) -> bool:
    # L = letra de qualquer alfabeto; M = acento combinante (o "e" + "´" que
    # alguns teclados produzem em vez de "é").
    return unicodedata.category(c)[0] in ("L", "M")


def _conferir_nome_de_pessoa(valor: str) -> str:
    """Letras, espaço, apóstrofo, hífen e ponto. Sobrenome não é obrigatório.

    Segue a orientação do W3C sobre nomes pessoais: há quem tenha um nome só, e
    exigir sobrenome recusaria gente de verdade.
    """
    valor = " ".join(valor.split())
    if any(c.isdecimal() for c in valor):
        raise ValueError("não pode ter números")
    if any(not (_e_letra(c) or c in _SEPARADORES_DE_NOME) for c in valor):
        raise ValueError("use só letras, espaço, apóstrofo, hífen e ponto")
    if sum(1 for c in valor if _e_letra(c)) < 2:
        raise ValueError("deve ter pelo menos 2 letras")
    return valor


def _conferir_nome_de_empresa(valor: str) -> str:
    valor = " ".join(valor.split())
    if "@" in valor:
        raise ValueError("não use @ neste campo")
    if not any(_e_letra(c) or c.isdecimal() for c in valor):
        raise ValueError("inclua ao menos uma letra ou número")
    if any(not (_e_letra(c) or c.isdecimal() or c in _PONTUACAO_DE_EMPRESA) for c in valor):
        raise ValueError("use só letras, números, espaço e & . , ' - / ( ) +")
    return valor


def NomeDePessoa(maximo: int):
    return Annotated[Nome(maximo), AfterValidator(_conferir_nome_de_pessoa)]


def NomeDeEmpresa(maximo: int):
    return Annotated[Nome(maximo), AfterValidator(_conferir_nome_de_empresa)]


def _email_limpo(valor):
    """Tira espaços das pontas e grava em minúsculas.

    O `EmailStr` do Pydantic aceita a forma `"Nome" <a@b.com>` e devolve só o
    endereço; aqui ela é recusada antes, porque ninguém digita isso num campo de
    e-mail sem estar testando o que passa.
    """
    valor = _limpar(valor)
    if not isinstance(valor, str):
        return valor
    if "<" in valor or ">" in valor:
        raise ValueError("e-mail inválido")
    if len(valor) > 254:
        raise ValueError("deve ter no máximo 254 caracteres")
    return valor.lower()


Email = Annotated[EmailStr, BeforeValidator(_email_limpo)]


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
# IN RFB 2.229/2024: desde julho de 2026 as 12 primeiras posições aceitam A–Z.
# Os dois dígitos verificadores continuam numéricos. O DV usa o valor ASCII − 48
# de cada caractere, o que dá exatamente a regra antiga para dígitos: CNPJ
# numérico gravado antes continua válido sem conversão nenhuma.
_CNPJ_SEPARADORES = re.compile(r"[.\-/\s]")
_CNPJ_SO_PERMITIDOS = re.compile(r"[0-9A-Z]*")
CNPJ_CRU = re.compile(r"[0-9A-Z]{12}[0-9]{2}")
_PESOS_CNPJ = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)


def cnpj_cru(valor: str) -> str:
    """Tira os separadores e passa para maiúscula. Não valida."""
    return _CNPJ_SEPARADORES.sub("", valor).upper()


def mascarar_cnpj(cru: str) -> str:
    return f"{cru[:2]}.{cru[2:5]}.{cru[5:8]}/{cru[8:12]}-{cru[12:]}"


def _normalizar_cnpj(valor):
    """Aceita com ou sem máscara, em qualquer caixa, e devolve mascarado.

    Confere só o formato. O DV é conferido por `CnpjObrigatorio` (cadastro) ou
    no serviço da agência, só quando o CNPJ muda — ver `agency_service`.
    """
    valor = _limpar(valor)
    if valor is None or valor == "":
        return None
    if not isinstance(valor, str):
        return valor
    cru = cnpj_cru(valor)
    if not _CNPJ_SO_PERMITIDOS.fullmatch(cru):
        raise ValueError("use só letras sem acento, números, pontos, barra e hífen")
    if len(cru) != 14:
        raise ValueError("deve ter 14 caracteres")
    if not CNPJ_CRU.fullmatch(cru):
        raise ValueError("os dois últimos caracteres devem ser números")
    return mascarar_cnpj(cru)


def _dv_cnpj(base: str) -> str:
    pesos = _PESOS_CNPJ[-len(base):]
    resto = sum((ord(c) - 48) * p for c, p in zip(base, pesos)) % 11
    return "0" if resto < 2 else str(11 - resto)


def cnpj_valido(cnpj: str) -> bool:
    """Confere os dois DVs. Recebe com ou sem máscara, em qualquer caixa."""
    cru = cnpj_cru(cnpj)
    if not CNPJ_CRU.fullmatch(cru) or len(set(cru)) == 1:
        return False
    primeiro = _dv_cnpj(cru[:12])
    return cru[12:] == primeiro + _dv_cnpj(cru[:12] + primeiro)


def _dv_confere(valor: str) -> str:
    if not cnpj_valido(valor):
        raise ValueError("CNPJ inválido — confira os dígitos")
    return valor


Cnpj = Annotated[Optional[str], BeforeValidator(_normalizar_cnpj)]
CnpjObrigatorio = Annotated[str, BeforeValidator(_normalizar_cnpj), AfterValidator(_dv_confere)]


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
