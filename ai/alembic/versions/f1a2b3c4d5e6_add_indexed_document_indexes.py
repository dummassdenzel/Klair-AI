"""Add indexes on indexed_documents for frequently queried fields

Revision ID: f1a2b3c4d5e6
Revises: e9dd4e5fe52a
Create Date: 2025-02-12

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e9dd4e5fe52a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        op.f('ix_indexed_documents_file_type'),
        'indexed_documents',
        ['file_type'],
        unique=False,
    )
    op.create_index(
        op.f('ix_indexed_documents_last_modified'),
        'indexed_documents',
        ['last_modified'],
        unique=False,
    )
    op.create_index(
        op.f('ix_indexed_documents_processing_status'),
        'indexed_documents',
        ['processing_status'],
        unique=False,
    )
    op.create_index(
        op.f('ix_indexed_documents_indexed_at'),
        'indexed_documents',
        ['indexed_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_indexed_documents_indexed_at'), table_name='indexed_documents')
    op.drop_index(op.f('ix_indexed_documents_processing_status'), table_name='indexed_documents')
    op.drop_index(op.f('ix_indexed_documents_last_modified'), table_name='indexed_documents')
    op.drop_index(op.f('ix_indexed_documents_file_type'), table_name='indexed_documents')
