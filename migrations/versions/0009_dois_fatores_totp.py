"""2FA por app autenticador (TOTP) e códigos de recuperação.

Revision ID: b7d2f4a91c36
Revises: a1c3e5f70b28
Create Date: 2026-10-19

Decisões: docs/adr/0014-segundo-fator-totp.md.

- `users.totp_segredo_cifrado`: segredo cifrado com a FERNET_KEY. Com
  `totp_ativado_em` nulo, é uma ativação ainda não confirmada.
- `users.totp_ativado_em`: quando o 2FA passou a valer.
- `users.totp_ultimo_passo`: último passo de tempo aceito. É o que faz cada
  código valer uma vez só (NIST SP 800-63B-4, §3.1.5.2).
- `codigos_recuperacao`: um registro por código, só com o HMAC dele.
- `finalidade_token` ganha `DESAFIO_2FA` e `ATIVAR_2FA`, os tickets que o login
  devolve no lugar da sessão.

Toda coluna nova é anulável e nenhuma linha existente muda: ninguém sai desta
migration com 2FA ligado. O administrador passa a ser levado à ativação no
próximo login, pela aplicação, e não pela migration.

`downgrade` apaga as colunas, a tabela e os tickets das finalidades novas, mas
deixa os dois valores no enum: o Postgres não remove valor de enum sem recriar
o tipo, e um valor que nenhuma linha usa não tem efeito.
"""
import sqlalchemy as sa
from alembic import op

revision = 'b7d2f4a91c36'
down_revision = 'a1c3e5f70b28'
branch_labels = None
depends_on = None


def upgrade():
    # Fora de transação no Postgres < 12; dentro dela a partir do 12, desde que
    # o valor novo não seja usado na mesma transação — e não é.
    op.execute("ALTER TYPE finalidade_token ADD VALUE IF NOT EXISTS 'DESAFIO_2FA'")
    op.execute("ALTER TYPE finalidade_token ADD VALUE IF NOT EXISTS 'ATIVAR_2FA'")

    op.add_column('users', sa.Column('totp_segredo_cifrado', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('totp_ativado_em', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('totp_ultimo_passo', sa.BigInteger(), nullable=True))

    op.create_table(
        'codigos_recuperacao',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('codigo_hash', sa.String(64), nullable=False),
        sa.Column('usado_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('codigo_hash', name='uq_codigos_recuperacao_codigo_hash'),
    )
    op.create_index('ix_codigos_recuperacao_user_id', 'codigos_recuperacao', ['user_id'])


def downgrade():
    op.execute("DELETE FROM auth_tokens WHERE finalidade IN ('DESAFIO_2FA', 'ATIVAR_2FA')")
    op.drop_index('ix_codigos_recuperacao_user_id', table_name='codigos_recuperacao')
    op.drop_table('codigos_recuperacao')
    op.drop_column('users', 'totp_ultimo_passo')
    op.drop_column('users', 'totp_ativado_em')
    op.drop_column('users', 'totp_segredo_cifrado')
