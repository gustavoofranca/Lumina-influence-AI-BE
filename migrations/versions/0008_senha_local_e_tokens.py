"""Conta com senha local e tokens de uso único.

Revision ID: a1c3e5f70b28
Revises: 9d3e07b4c512
Create Date: 2026-10-15

Até aqui `users` só existia para OAuth: `oauth_provider` e `oauth_id` eram
obrigatórios e nenhuma coluna guardava credencial. O login por e-mail e senha
(spec de 15/10/2026) pede:

- `password_hash` (nulo = conta só OAuth);
- `email_verificado_em`, com backfill de `created_at` para as contas que já
  existem, porque o provedor OAuth já tinha verificado o e-mail delas;
- `sessoes_validas_desde`, o marco que derruba sessões depois de trocar a senha
  (ADR-0013);
- `termos_aceitos_em`, evidência do consentimento;
- `oauth_provider` e `oauth_id` passam a aceitar nulo. A restrição
  `uq_users_oauth_identity` continua valendo: o Postgres admite vários nulos.

O e-mail passa a ser gravado em minúsculas. Antes de converter, a migration
procura endereços que só diferem na caixa: se houver, para com a lista na
mensagem, porque converter violaria a unicidade e escolher qual conta manter
não é decisão para uma migration.

`downgrade` recusa se já existir conta só com senha: voltar `oauth_provider` a
NOT NULL apagaria essas pessoas, e isso também não é decisão para uma migration.
"""
import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision = 'a1c3e5f70b28'
down_revision = '9d3e07b4c512'
branch_labels = None
depends_on = None


def _conferir_colisao_de_email() -> None:
    if context.is_offline_mode():
        return
    colisoes = op.get_bind().execute(sa.text(
        "SELECT lower(email) FROM users GROUP BY lower(email) HAVING count(*) > 1"
    )).scalars().all()
    if colisoes:
        raise RuntimeError(
            "E-mails que só diferem em maiúsculas/minúsculas impedem a migration: "
            + ", ".join(colisoes)
        )


def upgrade():
    _conferir_colisao_de_email()
    op.execute("UPDATE users SET email = lower(email) WHERE email <> lower(email)")

    op.add_column('users', sa.Column('password_hash', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('email_verificado_em', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('sessoes_validas_desde', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('termos_aceitos_em', sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET email_verificado_em = created_at")
    op.alter_column('users', 'oauth_provider', existing_type=postgresql.ENUM(name='oauth_provider'),
                    nullable=True)
    op.alter_column('users', 'oauth_id', existing_type=sa.String(120), nullable=True)

    finalidade = postgresql.ENUM('VERIFICAR_EMAIL', 'REDEFINIR_SENHA', name='finalidade_token')
    finalidade.create(op.get_bind(), checkfirst=True)
    op.create_table(
        'auth_tokens',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('finalidade', postgresql.ENUM(name='finalidade_token', create_type=False), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('expira_em', sa.DateTime(timezone=True), nullable=False),
        sa.Column('usado_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('token_hash', name='uq_auth_tokens_token_hash'),
    )
    op.create_index('ix_auth_tokens_user_id', 'auth_tokens', ['user_id'])


def downgrade():
    if not context.is_offline_mode():
        so_senha = op.get_bind().execute(sa.text(
            "SELECT count(*) FROM users WHERE oauth_provider IS NULL"
        )).scalar()
        if so_senha:
            raise RuntimeError(
                f"{so_senha} conta(s) só com senha impedem o downgrade — ver o cabeçalho."
            )
    op.drop_index('ix_auth_tokens_user_id', table_name='auth_tokens')
    op.drop_table('auth_tokens')
    postgresql.ENUM(name='finalidade_token').drop(op.get_bind(), checkfirst=True)
    op.alter_column('users', 'oauth_id', existing_type=sa.String(120), nullable=False)
    op.alter_column('users', 'oauth_provider', existing_type=postgresql.ENUM(name='oauth_provider'),
                    nullable=False)
    op.drop_column('users', 'termos_aceitos_em')
    op.drop_column('users', 'sessoes_validas_desde')
    op.drop_column('users', 'email_verificado_em')
    op.drop_column('users', 'password_hash')
