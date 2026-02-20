"""Add document_category to indexed_documents for type-based filtering

Revision ID: b7c8d9e0f1a2
Revises: f1a2b3c4d5e6
Create Date: 2025-02-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'indexed_documents',
        sa.Column('document_category', sa.String(), nullable=True),
    )
    op.create_index(
        op.f('ix_indexed_documents_document_category'),
        'indexed_documents',
        ['document_category'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_indexed_documents_document_category'), table_name='indexed_documents')
    op.drop_column('indexed_documents', 'document_category')
