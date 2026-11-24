"""Parsing de body JSON via Pydantic, convertendo erros pro formato Lumina."""
from __future__ import annotations

from typing import TypeVar

from flask import request
from pydantic import BaseModel, ValidationError as PydanticValidationError

from src.utils.errors import ValidationError

T = TypeVar("T", bound=BaseModel)


# Rótulo de cada campo como a tela o chama. A mensagem de erro de um campo só
# vira "Marca: deve ter no máximo 160 caracteres" se o campo estiver aqui; fora
# daqui, sai só a regra.
ROTULOS = {
    "brand_name": "Marca",
    "title": "Título",
    "period_start": "Início",
    "period_end": "Fim",
    "period": "Período",
    "budget_brl_cents": "Orçamento",
    "fee_brl_cents": "Cachê",
    "deliverables": "Entregáveis",
    "participants": "Participantes",
    "influencer_id": "Criador",
    "campaign_id": "Campanha",
    "display_name": "Nome",
    "niche": "Nicho",
    "bio": "Bio",
    "status": "Status",
    "handle": "Usuário na plataforma",
    "platform": "Plataforma",
    "platform_user_id": "Identificador na plataforma",
    "follower_count": "Seguidores",
    "name": "Nome",
    "cnpj": "CNPJ",
    "plan_id": "Plano",
    "email": "E-mail",
    "role": "Papel",
    "avatar_url": "Foto",
    "sections": "Seções",
    "video": "Vídeo",
    "caption": "Legenda",
    "analysis_id": "Análise",
    "decision": "Decisão",
}

# Erros de tipo que, com `null` na entrada, querem dizer "campo obrigatório
# enviado vazio" — é o caso da edição que mandava `null` e estourava no banco.
_ERROS_DE_TIPO = {
    "string_type", "int_type", "date_type", "enum", "uuid_type", "bool_type",
    "list_type", "dict_type", "model_type", "float_type", "datetime_type",
}


def _reais(centavos: int) -> str:
    inteiro, resto = divmod(int(centavos), 100)
    return f"R$ {inteiro:,}".replace(",", ".") + f",{resto:02d}"


def _numero(valor, campo: str) -> str:
    if campo.endswith("_brl_cents"):
        return _reais(valor)
    return f"{valor:,}".replace(",", ".") if isinstance(valor, int) else str(valor)


# Tipos de erro cuja frase não depende do valor nem do limite.
_FRASES_FIXAS = {
    "missing": "campo obrigatório",
    "string_type": "deve ser um texto",
    "string_pattern_mismatch": "use só letras, números, ponto, hífen e sublinhado, sem espaços",
    "int_type": "deve ser um número inteiro",
    "int_parsing": "deve ser um número inteiro",
    "int_from_float": "deve ser um número inteiro",
    "uuid_parsing": "identificador inválido",
    "uuid_type": "identificador inválido",
    "extra_forbidden": "campo não reconhecido",
    "list_type": "deve ser uma lista",
    "bool_type": "deve ser verdadeiro ou falso",
    "bool_parsing": "deve ser verdadeiro ou falso",
}

# O Pydantic tem um tipo para cada formato de data inválido (`date_parsing`,
# `date_from_datetime_parsing`...); todos viram a mesma frase.
_FRASE_DE_DATA = "data inválida; use o formato AAAA-MM-DD"


# Com validador antes do tipo, o Pydantic mede o texto pela regra genérica de
# tamanho (`too_short`/`too_long`) e não pela de string. Texto conta
# caracteres; lista conta itens.
def _e_lista(err: dict) -> bool:
    return err.get("type") in ("too_short", "too_long") and not isinstance(err.get("input"), str)


def _pelo_menos(err: dict, ctx: dict, campo: str) -> str:
    minimo = ctx.get("min_length", 1)
    if _e_lista(err):
        return f"deve ter pelo menos {minimo} {'item' if minimo == 1 else 'itens'}"
    return "não pode ficar em branco" if minimo == 1 else f"deve ter pelo menos {minimo} caracteres"


def _no_maximo(err: dict, ctx: dict, campo: str) -> str:
    unidade = "itens" if _e_lista(err) else "caracteres"
    return f"deve ter no máximo {ctx.get('max_length')} {unidade}"


def _limite_inferior(err: dict, ctx: dict, campo: str) -> str:
    return f"deve ser maior ou igual a {_numero(ctx.get('ge', ctx.get('gt')), campo)}"


def _limite_superior(err: dict, ctx: dict, campo: str) -> str:
    return f"deve ser no máximo {_numero(ctx.get('le', ctx.get('lt')), campo)}"


def _opcoes(err: dict, ctx: dict, campo: str) -> str:
    # O Pydantic monta a lista com "or" antes do último item.
    opcoes = str(ctx.get("expected", "")).replace(" or ", " ou ")
    return f"valor inválido; use um destes: {opcoes}"


def _erro_de_valor(err: dict, ctx: dict, campo: str) -> str:
    # O EmailStr devolve a explicação da biblioteca, em inglês.
    if campo == "email":
        return "e-mail inválido"
    return str(err.get("msg", "")).removeprefix("Value error, ")


# Tipos de erro cuja frase leva o limite, o valor ou o campo.
_FRASES_CALCULADAS = {
    "string_too_short": _pelo_menos,
    "too_short": _pelo_menos,
    "string_too_long": _no_maximo,
    "too_long": _no_maximo,
    "greater_than_equal": _limite_inferior,
    "greater_than": _limite_inferior,
    "less_than_equal": _limite_superior,
    "less_than": _limite_superior,
    "enum": _opcoes,
    "value_error": _erro_de_valor,
}


def _mensagem(err: dict, campo: str) -> str:
    """Traduz um erro do Pydantic para a frase que a pessoa lê na tela."""
    tipo = err.get("type", "")
    # Vem antes das tabelas: `enum` e `string_type` com `null` não são valor
    # errado, são campo obrigatório enviado vazio.
    if tipo in _ERROS_DE_TIPO and err.get("input") is None:
        return "não pode ficar vazio"
    if tipo in _FRASES_FIXAS:
        return _FRASES_FIXAS[tipo]
    if tipo in _FRASES_CALCULADAS:
        return _FRASES_CALCULADAS[tipo](err, err.get("ctx") or {}, campo)
    if tipo.startswith("date_"):
        return _FRASE_DE_DATA
    return str(err.get("msg", ""))


def _rotulo(loc: tuple) -> str | None:
    nomes = [p for p in loc if isinstance(p, str)]
    return ROTULOS.get(nomes[-1]) if nomes else None


def _simplify_errors(exc: PydanticValidationError) -> list[dict]:
    out = []
    for err in exc.errors():
        loc = tuple(err.get("loc", ()))
        campo = next((p for p in reversed(loc) if isinstance(p, str)), "")
        out.append(
            {
                "field": ".".join(str(p) for p in loc),
                "label": _rotulo(loc),
                "message": _mensagem(err, campo),
                "type": err.get("type", ""),
            }
        )
    return out


def mensagem_geral(campos: list[dict]) -> str:
    """Um campo errado: "Marca: deve ter no máximo 160 caracteres". Vários: aviso geral.

    É a frase que aparece no aviso de erro da tela, então tem que dizer o que
    corrigir sem depender de a tela saber ler os detalhes.
    """
    if len(campos) != 1:
        return "Corrija os campos indicados"
    campo = campos[0]
    return f"{campo['label']}: {campo['message']}" if campo.get("label") else campo["message"]


def erro_de_campo(campo: str, mensagem: str, tipo: str = "value_error") -> ValidationError:
    """Erro levantado fora do schema, no mesmo formato dos erros de schema."""
    campos = [{"field": campo, "label": ROTULOS.get(campo), "message": mensagem, "type": tipo}]
    return ValidationError(mensagem_geral(campos), details={"fields": campos})


def parse_enum_arg(enum_cls, raw: str | None):
    """Converte uma query string em membro de enum. None se ausente. 422 se inválido."""
    if raw is None or raw == "":
        return None
    try:
        return enum_cls(raw)
    except ValueError as exc:
        valid = [e.value for e in enum_cls]
        raise ValidationError(
            f"Valor inválido para {enum_cls.__name__}",
            details={"received": raw, "valid": valid},
        ) from exc


def parse_json(schema_cls: type[T], *, partial: bool = False) -> T:
    """Valida o corpo JSON contra um schema Pydantic.

    `partial=True` ainda usa o mesmo schema — defina campos opcionais no schema
    de update. Levanta ValidationError (422) com detalhes por campo.
    """
    payload = request.get_json(silent=True)
    if payload is None:
        raise ValidationError("Corpo JSON ausente ou inválido", code="invalid_body")
    if not isinstance(payload, dict):
        raise ValidationError("Corpo JSON deve ser um objeto", code="invalid_body")
    return validar_dados(schema_cls, payload)


def validar_dados(schema_cls: type[T], dados: dict) -> T:
    """Valida um dicionário contra um schema, com o erro no formato de `parse_json`.

    Para entrada que não chega como corpo JSON — os campos de texto de um
    formulário multipart, por exemplo.
    """
    try:
        return schema_cls.model_validate(dados)
    except PydanticValidationError as exc:
        campos = _simplify_errors(exc)
        raise ValidationError(mensagem_geral(campos), details={"fields": campos}) from exc
