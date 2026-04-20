"""add document classification metadata

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-04-19 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f3a4b5c6d7e8"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("documents")}

    with op.batch_alter_table("documents", schema=None) as batch_op:
        if "extracted_text" not in existing_columns:
            batch_op.add_column(sa.Column("extracted_text", sa.Text(), nullable=True))
        if "classification_confidence" not in existing_columns:
            batch_op.add_column(sa.Column("classification_confidence", sa.String(length=50), nullable=True))
        if "classification_notes" not in existing_columns:
            batch_op.add_column(sa.Column("classification_notes", sa.Text(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("documents")}

    with op.batch_alter_table("documents", schema=None) as batch_op:
        if "classification_notes" in existing_columns:
            batch_op.drop_column("classification_notes")
        if "classification_confidence" in existing_columns:
            batch_op.drop_column("classification_confidence")
        if "extracted_text" in existing_columns:
            batch_op.drop_column("extracted_text")
