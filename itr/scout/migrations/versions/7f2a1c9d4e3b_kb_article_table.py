"""kb_article table

Revision ID: 7f2a1c9d4e3b
Revises: 5835576deac8
Create Date: 2026-08-19 12:00:00.000000

Knowledge Base solution articles (see schema/009_kb_article.sql for the
reference DDL and rationale). Chained after the quarantine table, the
current head.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '7f2a1c9d4e3b'
down_revision: str | None = '5835576deac8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'kb_article',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('category', sa.Text(), nullable=False),
        sa.Column('problem_class', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('source', sa.Text(), nullable=False, server_default=sa.text("'llm_generated'")),
        sa.Column('model_name', sa.Text(), nullable=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_system', sa.Text(), nullable=False),
        sa.Column('external_id', sa.Text(), nullable=True),
        sa.Column('is_synthetic', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('connector_run_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(
            ['category', 'problem_class'],
            ['itr360.problem_taxonomy.category', 'itr360.problem_taxonomy.problem_class'],
        ),
        sa.UniqueConstraint('tenant_id', 'category', 'problem_class', 'title'),
        schema='itr360',
    )
    op.create_index('ix_itr360_kb_article_tenant_id', 'kb_article', ['tenant_id'], unique=False, schema='itr360')
    op.create_index('ix_itr360_kb_article_class', 'kb_article', ['category', 'problem_class'], unique=False, schema='itr360')


def downgrade() -> None:
    op.drop_index('ix_itr360_kb_article_class', table_name='kb_article', schema='itr360')
    op.drop_index('ix_itr360_kb_article_tenant_id', table_name='kb_article', schema='itr360')
    op.drop_table('kb_article', schema='itr360')
