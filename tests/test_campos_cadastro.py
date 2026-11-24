"""Tipos de campo do cadastro: CNPJ alfanumérico, links, nomes e e-mail.

O CNPJ segue a IN RFB 2.229/2024. O exemplo `12ABC34501DE35` é o da própria
Receita, no documento de perguntas e respostas sobre o formato alfanumérico.
"""
from __future__ import annotations

import time

import pytest
from pydantic import BaseModel, ValidationError

from src.schemas.campos import (
    CnpjObrigatorio,
    Email,
    Nome,
    NomeDeEmpresa,
    NomeDePessoa,
    cnpj_valido,
    contem_link,
)


class _Pessoa(BaseModel):
    nome: NomeDePessoa(160)


class _Empresa(BaseModel):
    nome: NomeDeEmpresa(160)


class _Marca(BaseModel):
    nome: Nome(160)


class _Cnpj(BaseModel):
    cnpj: CnpjObrigatorio


class _Email(BaseModel):
    email: Email


def _erro(modelo, **dados) -> str:
    with pytest.raises(ValidationError) as exc:
        modelo(**dados)
    return exc.value.errors()[0]["msg"]


# ---------------------------------------------------------------- CNPJ
@pytest.mark.parametrize("cnpj", [
    "12ABC34501DE35", "12.ABC.345/01DE-35", "12abc34501de35",
    "11222333000181", "12.345.678/0001-95", "19131243000197",
])
def test_cnpj_valido_numerico_e_alfanumerico(cnpj):
    assert cnpj_valido(cnpj)


@pytest.mark.parametrize("cnpj", [
    "12ABC34501DE99", "11111111111111", "11.222.333/0001-80", "12ABC34501DEXX", "",
])
def test_cnpj_invalido(cnpj):
    assert not cnpj_valido(cnpj)


def test_cnpj_obrigatorio_grava_mascarado_em_maiuscula():
    assert _Cnpj(cnpj=" 12abc34501de35 ").cnpj == "12.ABC.345/01DE-35"


@pytest.mark.parametrize("cnpj,trecho", [
    ("12ABC34501DE99", "CNPJ inválido"),
    ("12.345-678", "14 caracteres"),
    ("12ABC34501DEXX", "dois últimos"),
    ("12ÁBC34501DE35", "letras sem acento"),
])
def test_cnpj_obrigatorio_recusa_com_mensagem(cnpj, trecho):
    assert trecho in _erro(_Cnpj, cnpj=cnpj)


# ---------------------------------------------------------------- links
@pytest.mark.parametrize("texto", [
    "www.marina.com", "https://acme.com.br", "acme.com.br", "Veja acme.io/promo",
    "Lumina.AI", "marca@x.com", "Booking.com",
])
def test_contem_link(texto):
    assert contem_link(texto)


@pytest.mark.parametrize("texto", [
    "Silva & Costa Ltda.", "ACME (Brasil) S/A", "José da Silva Jr.", "Ana-Clara", "Agência 360",
])
def test_nao_e_link(texto):
    assert not contem_link(texto)


def test_detector_de_link_e_linear():
    for texto in ("a." * 5000 + "b" * 5000, "x " * 10000, "." * 10000):
        inicio = time.perf_counter()
        contem_link(texto)
        assert time.perf_counter() - inicio < 0.05


def test_nome_generico_recusa_link():
    assert "links" in _erro(_Marca, nome="Booking.com")


# ---------------------------------------------------------------- nomes
@pytest.mark.parametrize("nome,esperado", [
    ("Marina Costa", "Marina Costa"),
    ("Maria D'Ávila", "Maria D'Ávila"),
    ("  marina    costa ", "marina costa"),
    ("Ana-Clara Jr.", "Ana-Clara Jr."),
    ("Zoë", "Zoë"),
])
def test_nome_de_pessoa_aceito(nome, esperado):
    assert _Pessoa(nome=nome).nome == esperado


@pytest.mark.parametrize("nome,trecho", [
    ("Marina2", "números"),
    ("@marina", "só letras"),
    ("www.marina.com", "links"),
    ("M", "2 letras"),
    ("<b>Ana</b>", "< ou >"),
])
def test_nome_de_pessoa_recusado(nome, trecho):
    assert trecho in _erro(_Pessoa, nome=nome)


@pytest.mark.parametrize("nome", [
    "Silva & Costa Ltda.", "ACME (Brasil) S/A", "Agência 360 Comunicação", "Lumina+",
])
def test_nome_de_empresa_aceito(nome):
    assert _Empresa(nome=nome).nome == nome


@pytest.mark.parametrize("nome,trecho", [
    ("agencia@acme", "@"),
    ("https://acme.com.br", "links"),
    ("!!!", "letra ou número"),
    ("Agência #1", "só letras, números"),
])
def test_nome_de_empresa_recusado(nome, trecho):
    assert trecho in _erro(_Empresa, nome=nome)


# ---------------------------------------------------------------- e-mail
def test_email_normalizado_em_minusculas():
    assert _Email(email="  Marina@Agencia.COM.br ").email == "marina@agencia.com.br"


@pytest.mark.parametrize("email", [
    "marina @agencia.com", "marina@agencia", '"A" <a@b.com>', "a" * 250 + "@x.com",
])
def test_email_recusado(email):
    with pytest.raises(ValidationError):
        _Email(email=email)
