"""Política de senha (NIST SP 800-63B rev. 4) e hash (Argon2id)."""
from __future__ import annotations

import unicodedata

import pytest

from src.utils import senha as S


@pytest.mark.parametrize("valor,trecho", [
    ("Lumina@2026", "pelo menos 12"),
    ("a" * 129, "no máximo 128"),
    ("aaaaaaaaaaaa", "previsível"),
    ("qwertyuiop123", "muito comum"),
    ("Password1234", "muito comum"),
])
def test_senha_recusada(valor, trecho):
    assert trecho in S.problema_da_senha(valor)


def test_senha_que_contem_o_email_e_recusada():
    problema = S.problema_da_senha("marina.lumina2026", email="marina@lumina-agency.com.br")
    assert "e-mail" in problema


def test_senha_que_contem_o_nome_e_recusada_sem_olhar_acento():
    problema = S.problema_da_senha("minha senha do Joao 77", nome="João Pereira")
    assert "nome" in problema


@pytest.mark.parametrize("valor", ["café com pão de queijo", "T7#kq!vZ2@mW"])
def test_senha_boa_passa(valor):
    assert S.problema_da_senha(valor, email="marina@x.com", nome="Marina Costa") is None


def test_comprimento_conta_depois_do_nfkc():
    # "ﬁ" (ligadura) vira "fi" no NFKC: 11 ligaduras = 22 caracteres.
    assert S.problema_da_senha("ﬁ" * 11 + "x") is None


def test_hash_e_argon2id_e_confere():
    h = S.gerar_hash("café com pão de queijo")
    assert h.startswith("$argon2id$")
    assert S.conferir("café com pão de queijo", h)
    assert not S.conferir("cafe com pao de queijo", h)


def test_formas_unicode_diferentes_da_mesma_senha_conferem():
    composta = "café com pão de queijo"
    assert S.conferir(unicodedata.normalize("NFD", composta), S.gerar_hash(composta))


def test_hash_corrompido_nao_explode():
    assert S.conferir("x" * 12, "lixo") is False


def test_hash_ficticio_roda_sem_erro():
    S.conferir_contra_hash_ficticio("qualquer coisa longa")


def test_lista_de_vazadas_carregada():
    assert len(S._comuns()) > 20000
