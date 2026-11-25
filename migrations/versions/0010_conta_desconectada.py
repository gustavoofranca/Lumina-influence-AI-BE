"""Conta social desconectada some da tela, com o histórico guardado.

Revision ID: c4e8a1d2f905
Revises: b7d2f4a91c36
Create Date: 2026-11-25

- `social_accounts.desconectada_em`: quando alguém desconectou a conta. Com
  valor, a conta e tudo o que veio dela (posts, comentários, análises e as
  recomendações) deixam de aparecer e de contar; as linhas continuam no banco.
  Reconectar zera a coluna.

Preenche as contas que já estavam desconectadas: sem token e com um
identificador que veio de OAuth — real ou do provedor de demonstração. A carga
inicial (`{rede}-{slug}`, sem token desde sempre) fica de fora: ela nunca foi
conectada, e escondê-la apagaria a demonstração.

`downgrade` remove a coluna; as contas voltam a aparecer como "vinculada, sem
coleta ativa", que é o comportamento anterior.
"""
import sqlalchemy as sa
from alembic import op

revision = 'c4e8a1d2f905'
down_revision = 'b7d2f4a91c36'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'social_accounts',
        sa.Column('desconectada_em', sa.DateTime(timezone=True), nullable=True),
    )
    if op.get_bind().dialect.name == 'postgresql':
        op.execute(
            """
            UPDATE social_accounts
               SET desconectada_em = now()
             WHERE access_token_encrypted IS NULL
               AND platform_user_id IS NOT NULL
               AND platform_user_id !~ '^(instagram|tiktok|youtube)-[a-z0-9-]+$'
            """
        )


def downgrade():
    op.drop_column('social_accounts', 'desconectada_em')
