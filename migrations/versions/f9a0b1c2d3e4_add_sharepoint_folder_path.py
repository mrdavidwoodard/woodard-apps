"""add sharepoint folder path

Revision ID: f9a0b1c2d3e4
Revises: e4f5a6b7c8d9
Create Date: 2026-04-18 19:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f9a0b1c2d3e4"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("documents")}
    if "sharepoint_folder_path" not in existing_columns:
        with op.batch_alter_table("documents", schema=None) as batch_op:
            batch_op.add_column(sa.Column("sharepoint_folder_path", sa.String(length=1024), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("documents")}
    if "sharepoint_folder_path" in existing_columns:
        with op.batch_alter_table("documents", schema=None) as batch_op:
            batch_op.drop_column("sharepoint_folder_path")
