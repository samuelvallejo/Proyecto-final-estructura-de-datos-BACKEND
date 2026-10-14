"""Encrypted accounts and shared authentication rate limits. Existing reports stay intact."""
from alembic import op
from sqlalchemy import inspect, Text, Column, String
from app.schema import auth_attempts

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column['name'] for column in inspect(bind).get_columns('users')}
    op.alter_column('users', 'email', type_=Text())
    op.alter_column('users', 'display_name', type_=Text())
    if 'email_lookup' not in columns:
        op.add_column('users', Column('email_lookup', String(64), nullable=True))
        op.create_unique_constraint('uq_users_email_lookup', 'users', ['email_lookup'])
    auth_attempts.create(bind, checkfirst=True)


def downgrade():
    raise RuntimeError('La reversión de cuentas cifradas requiere una migración de datos explícita.')
