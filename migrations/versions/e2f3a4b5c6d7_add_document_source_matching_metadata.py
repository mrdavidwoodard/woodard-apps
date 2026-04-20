"""add document source matching metadata

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-04-19 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("documents")}

    with op.batch_alter_table("documents", schema=None) as batch_op:
        if "source_system" not in existing_columns:
            batch_op.add_column(sa.Column("source_system", sa.String(length=50), nullable=True))
        if "source_file_name" not in existing_columns:
            batch_op.add_column(sa.Column("source_file_name", sa.String(length=255), nullable=True))
        if "detected_document_type" not in existing_columns:
            batch_op.add_column(sa.Column("detected_document_type", sa.String(length=80), nullable=True))
        if "matching_method" not in existing_columns:
            batch_op.add_column(sa.Column("matching_method", sa.String(length=80), nullable=True))

    bind.execute(
        sa.text(
            "UPDATE documents "
            "SET source_system = COALESCE(source_system, source), "
            "source_file_name = COALESCE(source_file_name, original_file_name)"
        )
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("documents")}

    with op.batch_alter_table("documents", schema=None) as batch_op:
        if "matching_method" in existing_columns:
            batch_op.drop_column("matching_method")
        if "detected_document_type" in existing_columns:
            batch_op.drop_column("detected_document_type")
        if "source_file_name" in existing_columns:
            batch_op.drop_column("source_file_name")
        if "source_system" in existing_columns:
            batch_op.drop_column("source_system")
