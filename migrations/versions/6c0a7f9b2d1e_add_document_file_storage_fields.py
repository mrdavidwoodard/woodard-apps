"""add document file storage fields

Revision ID: 6c0a7f9b2d1e
Revises: 23214eaf19eb
Create Date: 2026-04-18 18:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6c0a7f9b2d1e"
down_revision = "23214eaf19eb"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("original_file_name", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("stored_file_path", sa.String(length=1024), nullable=True))
        batch_op.add_column(sa.Column("file_size_bytes", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_column("file_size_bytes")
        batch_op.drop_column("stored_file_path")
        batch_op.drop_column("original_file_name")
