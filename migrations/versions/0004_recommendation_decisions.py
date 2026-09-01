"""Decisões da agência sobre as recomendações da IA.

Revision ID: 8b41c0d5e7a2
Revises: 6598a89ce9fa
Create Date: 2026-09-01

A recomendação não vira linha própria: ela vive dentro do JSON da análise, que
é imutável depois de gerada. A identidade estável de um item é o par
(análise, posição na lista) — daí a chave única sobre os dois.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '8b41c0d5e7a2'
down_revision = '6598a89ce9fa'
branch_labels = None
depends_on = None


def upgrade():
    # O tipo é criado à parte e a coluna o referencia com `create_type=False`.
    # Deixar o `create_table` criá-lo estoura quando o tipo já existe — e ele
    # sobrevive a uma migration que falhou no meio, porque o Postgres mantém o
    # tipo mesmo desfazendo a tabela.
    # Rótulos em MAIÚSCULA: o schema inteiro guarda o **nome** do membro do
    # enum ('ADMIN', 'INSTAGRAM'), que é o padrão do SQLAlchemy. Criar este
    # tipo com os valores minúsculos fazia o INSERT estourar com
    # `invalid input value for enum` — e só em Postgres, porque o SQLite dos
    # testes aceita qualquer texto na coluna.
    decisao = postgresql.ENUM('ACCEPTED', 'IGNORED', name='recommendation_decision',
                              create_type=False)
    postgresql.ENUM('ACCEPTED', 'IGNORED', name='recommendation_decision').create(
        op.get_bind(), checkfirst=True
    )

    op.create_table(
        'recommendation_decisions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('analysis_id', sa.Uuid(), nullable=False),
        sa.Column('item_index', sa.Integer(), nullable=False),
        sa.Column('decision', decisao, nullable=False),
        sa.Column('decided_by_user_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['analysis_id'], ['ai_analyses.id'], ondelete='CASCADE'),
        # SET NULL, e não cascade: a decisão continua valendo depois que quem a
        # tomou sai da agência. Apagar reescreveria o histórico.
        sa.ForeignKeyConstraint(['decided_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('analysis_id', 'item_index',
                            name='uq_recommendation_decision_item'),
    )
    op.create_index(op.f('ix_recommendation_decisions_analysis_id'),
                    'recommendation_decisions', ['analysis_id'])
    op.create_index(op.f('ix_recommendation_decisions_decided_by_user_id'),
                    'recommendation_decisions', ['decided_by_user_id'])


def downgrade():
    op.drop_index(op.f('ix_recommendation_decisions_decided_by_user_id'),
                  table_name='recommendation_decisions')
    op.drop_index(op.f('ix_recommendation_decisions_analysis_id'),
                  table_name='recommendation_decisions')
    op.drop_table('recommendation_decisions')
    sa.Enum(name='recommendation_decision').drop(op.get_bind(), checkfirst=True)
