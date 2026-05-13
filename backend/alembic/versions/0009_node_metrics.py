"""Add partitioned node_metrics tables for time-series telemetry

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-13 00:00:00.000000

Two tables partitioned by day:
 - node_metrics_raw   : 1 row par heartbeat (~10s), rétention 24h
 - node_metrics_1min  : agrégat tumbling 1-min, rétention 7j

BRIN index sur `time` : très efficace pour les inserts append-only et les
ranges temporels.

Une partition `_default` catch-all évite les INSERTs en échec si le worker
de création de partition tarde. Les partitions journalières sont créées
par le worker `create_metrics_partitions` (toutes les heures).
"""
from alembic import op


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


_CREATE_RAW = """
CREATE TABLE node_metrics_raw (
    time         TIMESTAMPTZ NOT NULL,
    node_id      UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    cpu_pct      REAL,
    ram_used_mb  INTEGER,
    ram_total_mb INTEGER,
    vram_used_mb INTEGER,
    vram_total_mb INTEGER,
    disk_used_mb INTEGER,
    net_rx_kbps  REAL,
    net_tx_kbps  REAL,
    llama_running BOOLEAN,
    llama_model_loaded TEXT,
    llama_tps    REAL,
    llama_slots_active INTEGER,
    llama_prompt_tokens_total BIGINT,
    llama_gen_tokens_total    BIGINT,
    llama_queue_pending INTEGER,
    PRIMARY KEY (node_id, time)
) PARTITION BY RANGE (time);
"""

_CREATE_1MIN = """
CREATE TABLE node_metrics_1min (
    time         TIMESTAMPTZ NOT NULL,
    node_id      UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    cpu_pct      REAL,
    ram_used_mb  INTEGER,
    ram_total_mb INTEGER,
    vram_used_mb INTEGER,
    vram_total_mb INTEGER,
    disk_used_mb INTEGER,
    net_rx_kbps  REAL,
    net_tx_kbps  REAL,
    llama_running BOOLEAN,
    llama_model_loaded TEXT,
    llama_tps    REAL,
    llama_slots_active INTEGER,
    llama_prompt_tokens_total BIGINT,
    llama_gen_tokens_total    BIGINT,
    llama_queue_pending INTEGER,
    PRIMARY KEY (node_id, time)
) PARTITION BY RANGE (time);
"""


def upgrade() -> None:
    op.execute(_CREATE_RAW)
    op.execute(_CREATE_1MIN)
    op.execute(
        "CREATE INDEX brin_node_metrics_raw_time ON node_metrics_raw "
        "USING BRIN (time) WITH (pages_per_range = 32);"
    )
    op.execute(
        "CREATE INDEX brin_node_metrics_1min_time ON node_metrics_1min "
        "USING BRIN (time) WITH (pages_per_range = 32);"
    )
    # Partitions DEFAULT catch-all : évitent des INSERTs en échec entre le
    # déploiement et la première exécution du worker create_metrics_partitions.
    # Le worker pourra ensuite créer des partitions journalières dédiées.
    op.execute(
        "CREATE TABLE node_metrics_raw_default PARTITION OF node_metrics_raw DEFAULT;"
    )
    op.execute(
        "CREATE TABLE node_metrics_1min_default PARTITION OF node_metrics_1min DEFAULT;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS node_metrics_1min CASCADE;")
    op.execute("DROP TABLE IF EXISTS node_metrics_raw CASCADE;")
