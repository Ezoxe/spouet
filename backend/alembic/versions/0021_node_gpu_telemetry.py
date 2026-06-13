"""Node GPU telemetry (live snapshot + time-series)

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-14 00:00:00.000000

Télémétrie GPU riche remontée par spouet-agent :
 - nodes.gpu_telemetry (JSONB) : snapshot live par carte (temp, usage, VRAM,
   puissance, ventilo, fréquences) — multi-GPU.
 - node_metrics_raw / node_metrics_1min : 3 colonnes agrégées par node pour les
   graphiques historiques (température/usage max, puissance totale).

Les tables de métriques sont partitionnées par jour : un ALTER TABLE ADD COLUMN
sur le parent se propage à toutes les partitions (y compris _default) sans
réécriture (colonnes NULL).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("nodes", sa.Column("gpu_telemetry", JSONB(), nullable=True))
    for table in ("node_metrics_raw", "node_metrics_1min"):
        op.add_column(table, sa.Column("gpu_temp_c", sa.REAL(), nullable=True))
        op.add_column(table, sa.Column("gpu_util_pct", sa.REAL(), nullable=True))
        op.add_column(table, sa.Column("gpu_power_w", sa.REAL(), nullable=True))


def downgrade() -> None:
    for table in ("node_metrics_1min", "node_metrics_raw"):
        op.drop_column(table, "gpu_power_w")
        op.drop_column(table, "gpu_util_pct")
        op.drop_column(table, "gpu_temp_c")
    op.drop_column("nodes", "gpu_telemetry")
