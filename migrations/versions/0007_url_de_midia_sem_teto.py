"""Endereço de mídia do post deixa de ter teto de mil caracteres.

Revision ID: 9d3e07b4c512
Revises: 4f2c81aa9e07
Create Date: 2026-09-16

`video_url` e `thumbnail_url` eram `VARCHAR(1000)`. A CDN do Instagram devolve
URL **assinada** — dezenas de parâmetros de autenticação, região, expiração e
hash — e ela passa de mil caracteres com folga. O primeiro sync de uma conta
real com Reel morreu em `StringDataRightTruncation`, derrubando a coleta inteira
do criador: nenhuma publicação entrava, porque o INSERT falhava no primeiro
vídeo e a transação ia junto.

O defeito não aparecia em teste nem em demonstração. Toda URL que o projeto
usava até aqui — seed, provedor local, fixture — é curta e bem-comportada; só
a plataforma real produz endereço desse tamanho. É a mesma categoria dos seis
defeitos que a rodada de bordas achou lendo os adaptadores contra a
documentação: falha que exige resposta que só a rede verdadeira devolve.

`Text` em vez de um número maior porque não há teto defensável a escolher: o
tamanho é decidido pela plataforma, muda sem aviso, e qualquer limite fixo aqui
seria palpite esperando quebrar de novo. No Postgres, `TEXT` e `VARCHAR(n)` têm
o mesmo desempenho e o mesmo armazenamento — o limite não estava comprando nada.

`downgrade` volta a `VARCHAR(1000)` e **trunca** o que passar disso; é o preço
de desfazer, e por isso está declarado aqui.
"""
import sqlalchemy as sa
from alembic import op

revision = '9d3e07b4c512'
down_revision = '4f2c81aa9e07'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('posts', 'video_url', type_=sa.Text(), existing_nullable=True)
    op.alter_column('posts', 'thumbnail_url', type_=sa.Text(), existing_nullable=True)


def downgrade():
    # Trunca o que exceder: voltar ao teto é lossy por natureza.
    op.execute("UPDATE posts SET video_url = left(video_url, 1000) "
               "WHERE length(video_url) > 1000")
    op.execute("UPDATE posts SET thumbnail_url = left(thumbnail_url, 1000) "
               "WHERE length(thumbnail_url) > 1000")
    op.alter_column('posts', 'video_url', type_=sa.String(1000), existing_nullable=True)
    op.alter_column('posts', 'thumbnail_url', type_=sa.String(1000), existing_nullable=True)
