"""Esquema inicial PostgreSQL congelado en SQL para migraciones reproducibles."""
from pathlib import Path
from alembic import op

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    script = Path(__file__).parents[1] / '0001_schema.sql'
    for statement in script.read_text(encoding='utf-8').split(';'):
        if statement.strip():
            op.execute(statement)


def downgrade():
    raise RuntimeError('Restaurar un respaldo para revertir; no se eliminan datos automáticamente.')
