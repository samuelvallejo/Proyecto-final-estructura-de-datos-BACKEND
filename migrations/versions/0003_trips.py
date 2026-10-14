"""Owner-scoped encrypted GPS journeys."""
from alembic import op
from app.schema import trips, trip_samples, trip_reports
revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

def upgrade():
    for table in (trips, trip_samples, trip_reports):
        table.create(op.get_bind(), checkfirst=True)

def downgrade():
    raise RuntimeError('Los recorridos se conservan; usa una migración explícita para revertir.')
