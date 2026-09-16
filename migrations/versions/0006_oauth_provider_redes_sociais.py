"""O enum de provedor OAuth passa a conhecer Meta e TikTok.

Revision ID: 4f2c81aa9e07
Revises: c17e4a90b3d1
Create Date: 2026-09-15

O callback de integração social gasta o `jti` do state na mesma tabela
`oauth_states` que o login usa, para que um state vazado não possa ser
reapresentado dentro dos seus 15 minutos de validade. O provedor é coluna
obrigatória dessa tabela, e o enum só conhecia `GOOGLE` e `MICROSOFT`: o mapa
`_STATE_NONCE_PROVIDER` tinha uma linha só, a do YouTube, cujo provedor é
literalmente `accounts.google.com`.

Instagram e TikTok ficavam de fora e o consumo do nonce falhava fechado — a
decisão certa enquanto o enum não cobria os dois, porque seguir sem a garantia
de uso único seria abrir mão da proteção em silêncio. O custo era que as duas
plataformas eram **inalcançáveis por completo**, mesmo com credencial válida no
ambiente: o erro aparecia no callback, depois do consentimento.

`META` e não `INSTAGRAM` porque é quem de fato emite o token na configuração
escolhida (*Instagram API with Facebook Login*, ver ADR-007): quem autoriza é
uma conta do Facebook, e o perfil do Instagram é alcançado pela Página. Nomear o
valor de `instagram` descreveria mal o que está registrado.

Os rótulos são **maiúsculos** porque é o que o `sqlalchemy.Enum` grava: ele
persiste o *nome* do membro do enum Python, não o seu valor — daí `GOOGLE` e
`MICROSOFT` já no tipo, e não `google` e `microsoft`. Uma primeira versão desta
migration adicionou os dois em minúsculo e o INSERT quebrou no callback do
TikTok, com `invalid input value for enum oauth_provider: "TIKTOK"`. Onde ela já
tiver rodado, os rótulos minúsculos continuam no tipo sem uso: o Postgres não
remove valor de enum sem recriar o tipo e reescrever a coluna, e um rótulo órfão
não faz mal nenhum.

`downgrade` não remove nada, pelo mesmo motivo. Voltar atrás significa apenas
parar de usá-los, e quem decide isso é o mapa em `integration_service`.
"""
from alembic import op

revision = '4f2c81aa9e07'
down_revision = 'c17e4a90b3d1'
branch_labels = None
depends_on = None

_NOVOS = ('META', 'TIKTOK')


def upgrade():
    # `IF NOT EXISTS` porque o tipo pode já ter os valores num banco que nasceu
    # do `create_all` da suíte, e falhar aqui não protegeria nada.
    for rotulo in _NOVOS:
        op.execute(f"ALTER TYPE oauth_provider ADD VALUE IF NOT EXISTS '{rotulo}'")


def downgrade():
    # Intencionalmente vazio — ver o cabeçalho.
    pass
