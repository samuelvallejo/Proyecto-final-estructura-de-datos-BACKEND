"""Roles, cuentas activas, duración de sesiones y pasos por baches conocidos.

Todo es aditivo: no modifica ni elimina reportes, cuentas ni recorridos existentes.
"""
from alembic import op
from sqlalchemy import BigInteger, Boolean, Column, inspect, true
from sqlalchemy.dialects.postgresql import insert
from app.schema import pothole_passes, roles, uid, now

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None

ROLE_NAMES = ('Administrador', 'Operario', 'Conductor')


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    user_columns = {column['name'] for column in inspector.get_columns('users')}
    if 'active' not in user_columns:
        op.add_column('users', Column('active', Boolean, nullable=False, server_default=true()))
    session_columns = {column['name'] for column in inspector.get_columns('sessions')}
    if 'last_seen_at' not in session_columns:
        op.add_column('sessions', Column('last_seen_at', BigInteger, nullable=True))
    if 'ended_at' not in session_columns:
        op.add_column('sessions', Column('ended_at', BigInteger, nullable=True))
    pothole_passes.create(bind, checkfirst=True)
    audit_indexes = {index['name'] for index in inspector.get_indexes('audit_events')}
    if 'ix_audit_events_recent' not in audit_indexes:
        op.create_index('ix_audit_events_recent', 'audit_events', ['created_at'])
    for name in ROLE_NAMES:
        bind.execute(insert(roles).values(id=uid(), created_at=now(), name=name).on_conflict_do_nothing(index_elements=['name']))


def downgrade():
    raise RuntimeError('Los pasos y roles se conservan; usa una migración explícita para revertir.')
