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
    "password": "Senha",
    "current_password": "Senha atual",
    "new_password": "Nova senha",
    "agency_name": "Nome da agência",
    "accept_terms": "Termos",
    "token": "Link",
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


def _mensagem(err: dict, campo: str) -> str:
    """Traduz um erro do Pydantic para a frase que a pessoa lê na tela."""
    tipo = err.get("type", "")
    ctx = err.get("ctx") or {}
    if tipo in _ERROS_DE_TIPO and err.get("input") is None:
        return "não pode ficar vazio"
    if tipo == "missing":
        return "campo obrigatório"
    # Com validador antes do tipo, o Pydantic mede o texto pela regra genérica
    # de tamanho (`too_short`/`too_long`) e não pela de string. Texto conta
    # caracteres; lista conta itens.
    if tipo in ("string_too_short", "too_short"):
        minimo = ctx.get("min_length", 1)
        if tipo == "too_short" and not isinstance(err.get("input"), str):
            return f"deve ter pelo menos {minimo} {'item' if minimo == 1 else 'itens'}"
        return "não pode ficar em branco" if minimo == 1 else f"deve ter pelo menos {minimo} caracteres"
    if tipo in ("string_too_long", "too_long"):
        maximo = ctx.get("max_length")
        if tipo == "too_long" and not isinstance(err.get("input"), str):
            return f"deve ter no máximo {maximo} itens"
        return f"deve ter no máximo {maximo} caracteres"
    if tipo == "string_type":
        return "deve ser um texto"
    if tipo == "string_pattern_mismatch":
        return "use só letras, números, ponto, hífen e sublinhado, sem espaços"
    if tipo in ("int_type", "int_parsing", "int_from_float"):
        return "deve ser um número inteiro"
    if tipo in ("greater_than_equal", "greater_than"):
        limite = ctx.get("ge", ctx.get("gt"))
        return f"deve ser maior ou igual a {_numero(limite, campo)}"
    if tipo in ("less_than_equal", "less_than"):
        limite = ctx.get("le", ctx.get("lt"))
        return f"deve ser no máximo {_numero(limite, campo)}"
    if tipo.startswith("date_") or tipo == "date_type":
        return "data inválida; use o formato AAAA-MM-DD"
    if tipo == "enum":
        # O Pydantic monta a lista com "or" antes do último item.
        opcoes = str(ctx.get("expected", "")).replace(" or ", " ou ")
        return f"valor inválido; use um destes: {opcoes}"
    if tipo in ("uuid_parsing", "uuid_type"):
        return "identificador inválido"
    if tipo == "extra_forbidden":
        return "campo não reconhecido"
    if tipo == "list_type":
        return "deve ser uma lista"
    if tipo in ("bool_type", "bool_parsing"):
        return "deve ser verdadeiro ou falso"
    if tipo == "value_error":
        # O EmailStr devolve a explicação da biblioteca, em inglês.
        if campo == "email":
            return "e-mail inválido"
        return str(err.get("msg", "")).removeprefix("Value error, ")
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
