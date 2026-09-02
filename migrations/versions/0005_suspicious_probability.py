"""Faixa suspeita da audiência passa a ser medida, e não derivada.

Revision ID: c17e4a90b3d1
Revises: 8b41c0d5e7a2
Create Date: 2026-09-02

O cartão de integridade de audiência exibia três percentuais — orgânico,
suspeito e bot — e o modelo devolvia **um**: `bot_probability`. Os outros dois
saíam de `bot * 0.6` e `bot * 0.4`, constantes que ninguém justificou. Três
números apresentados como medidos, sendo um medido e dois inventados, num
cartão chamado "integridade".

A coluna é nullable de propósito: análises geradas antes desta mudança não têm
o valor, e preenchê-las com qualquer número reintroduziria a invenção que a
mudança existe para remover.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c17e4a90b3d1'
down_revision = '8b41c0d5e7a2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ai_analyses', sa.Column('suspicious_probability', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('ai_analyses', 'suspicious_probability')
