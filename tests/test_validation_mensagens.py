"""Caracterização de `_mensagem`: a frase de cada tipo de erro do Pydantic.

Escrito antes de trocar a cadeia de if/elif por tabela (COD-03). Cada caso
fixa a frase que a tela mostra hoje; a refatoração não pode mudar nenhuma.
"""
import pytest

from src.utils.validation import _mensagem

CASOS = [
    # (erro do Pydantic, campo, frase esperada)
    ({"type": "string_type", "input": None}, "title", "não pode ficar vazio"),
    ({"type": "int_type", "input": None}, "follower_count", "não pode ficar vazio"),
    ({"type": "enum", "input": None}, "status", "não pode ficar vazio"),
    ({"type": "missing"}, "title", "campo obrigatório"),
    ({"type": "string_too_short", "ctx": {"min_length": 1}, "input": ""}, "title",
     "não pode ficar em branco"),
    ({"type": "string_too_short", "ctx": {"min_length": 3}, "input": "a"}, "title",
     "deve ter pelo menos 3 caracteres"),
    ({"type": "too_short", "ctx": {"min_length": 2}, "input": "a"}, "name",
     "deve ter pelo menos 2 caracteres"),
    ({"type": "too_short", "ctx": {"min_length": 1}, "input": []}, "participants",
     "deve ter pelo menos 1 item"),
    ({"type": "too_short", "ctx": {"min_length": 2}, "input": []}, "participants",
     "deve ter pelo menos 2 itens"),
    ({"type": "too_short", "input": "a"}, "name", "não pode ficar em branco"),
    ({"type": "string_too_long", "ctx": {"max_length": 160}, "input": "x"}, "brand_name",
     "deve ter no máximo 160 caracteres"),
    ({"type": "too_long", "ctx": {"max_length": 80}, "input": "x"}, "name",
     "deve ter no máximo 80 caracteres"),
    ({"type": "too_long", "ctx": {"max_length": 5}, "input": [1]}, "deliverables",
     "deve ter no máximo 5 itens"),
    ({"type": "string_type", "input": 3}, "title", "deve ser um texto"),
    ({"type": "string_pattern_mismatch", "input": "a b"}, "handle",
     "use só letras, números, ponto, hífen e sublinhado, sem espaços"),
    ({"type": "int_type", "input": "x"}, "follower_count", "deve ser um número inteiro"),
    ({"type": "int_parsing", "input": "x"}, "follower_count", "deve ser um número inteiro"),
    ({"type": "int_from_float", "input": 1.5}, "follower_count", "deve ser um número inteiro"),
    ({"type": "greater_than_equal", "ctx": {"ge": 0}, "input": -1}, "follower_count",
     "deve ser maior ou igual a 0"),
    ({"type": "greater_than", "ctx": {"gt": 1000}, "input": 1}, "follower_count",
     "deve ser maior ou igual a 1.000"),
    ({"type": "greater_than_equal", "ctx": {"ge": 100}, "input": 1}, "budget_brl_cents",
     "deve ser maior ou igual a R$ 1,00"),
    ({"type": "less_than_equal", "ctx": {"le": 1_000_000}, "input": 2}, "follower_count",
     "deve ser no máximo 1.000.000"),
    ({"type": "less_than", "ctx": {"lt": 123456}, "input": 2}, "fee_brl_cents",
     "deve ser no máximo R$ 1.234,56"),
    ({"type": "less_than_equal", "ctx": {"le": 2.5}, "input": 3}, "score",
     "deve ser no máximo 2.5"),
    ({"type": "date_from_datetime_parsing", "input": "x"}, "period_start",
     "data inválida; use o formato AAAA-MM-DD"),
    ({"type": "date_type", "input": 3}, "period_start",
     "data inválida; use o formato AAAA-MM-DD"),
    ({"type": "enum", "ctx": {"expected": "'a', 'b' or 'c'"}, "input": "z"}, "status",
     "valor inválido; use um destes: 'a', 'b' ou 'c'"),
    ({"type": "enum", "input": "z"}, "status", "valor inválido; use um destes: "),
    ({"type": "uuid_parsing", "input": "x"}, "campaign_id", "identificador inválido"),
    ({"type": "uuid_type", "input": 3}, "campaign_id", "identificador inválido"),
    ({"type": "extra_forbidden", "input": 1}, "foo", "campo não reconhecido"),
    ({"type": "list_type", "input": 1}, "participants", "deve ser uma lista"),
    ({"type": "bool_type", "input": "x"}, "accept", "deve ser verdadeiro ou falso"),
    ({"type": "bool_parsing", "input": "x"}, "accept", "deve ser verdadeiro ou falso"),
    ({"type": "value_error", "msg": "value is not a valid email address"}, "email",
     "e-mail inválido"),
    ({"type": "value_error", "msg": "Value error, CNPJ inválido"}, "cnpj", "CNPJ inválido"),
    ({"type": "value_error", "msg": "Value error, nome com link"}, "name", "nome com link"),
    ({"type": "value_error"}, "name", ""),
    ({"type": "dict_type", "input": 1, "msg": "Input should be a valid dictionary"},
     "sections", "Input should be a valid dictionary"),
    ({"type": "url_parsing", "msg": "Input should be a valid URL"}, "avatar_url",
     "Input should be a valid URL"),
    ({"msg": "sem tipo"}, "x", "sem tipo"),
    ({}, "x", ""),
]


@pytest.mark.parametrize(("err", "campo", "esperado"), CASOS)
def test_mensagem_de_cada_tipo_de_erro(err, campo, esperado):
    assert _mensagem(err, campo) == esperado
