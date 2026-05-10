"""Add llama.cpp fields and agent_port to nodes

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('nodes', sa.Column('agent_port', sa.Integer(), nullable=True))
    op.add_column('nodes', sa.Column('llama_running', sa.Boolean(), nullable=True))
    op.add_column('nodes', sa.Column('llama_model_loaded', sa.String(255), nullable=True))
    op.add_column('nodes', sa.Column('llama_n_ctx', sa.Integer(), nullable=True))
    op.add_column('nodes', sa.Column('llama_n_gpu_layers', sa.Integer(), nullable=True))
    op.add_column('nodes', sa.Column('llama_tps', sa.Float(), nullable=True))
    op.add_column('nodes', sa.Column('llama_slots_active', sa.Integer(), nullable=True))
    op.add_column('nodes', sa.Column('llama_prompt_tokens_processed', sa.Integer(), nullable=True))
    op.add_column('nodes', sa.Column('llama_tokens_generated', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('nodes', 'llama_tokens_generated')
    op.drop_column('nodes', 'llama_prompt_tokens_processed')
    op.drop_column('nodes', 'llama_slots_active')
    op.drop_column('nodes', 'llama_tps')
    op.drop_column('nodes', 'llama_n_gpu_layers')
    op.drop_column('nodes', 'llama_n_ctx')
    op.drop_column('nodes', 'llama_model_loaded')
    op.drop_column('nodes', 'llama_running')
    op.drop_column('nodes', 'agent_port')
