"""add sharepoint document fields

Revision ID: e4f5a6b7c8d9
Revises: d8e9f0a1b2c3
Create Date: 2026-04-18 19:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e4f5a6b7c8d9"
down_revision = "d8e9f0a1b2c3"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("documents")}
    with op.batch_alter_table("documents", schema=None) as batch_op:
        if "sharepoint_item_id" not in existing_columns:
            batch_op.add_column(sa.Column("sharepoint_item_id", sa.String(length=255), nullable=True))
        if "sharepoint_drive_id" not in existing_columns:
            batch_op.add_column(sa.Column("sharepoint_drive_id", sa.String(length=255), nullable=True))
        if "sharepoint_upload_status" not in existing_columns:
            batch_op.add_column(sa.Column("sharepoint_upload_status", sa.String(length=50), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("documents")}
    with op.batch_alter_table("documents", schema=None) as batch_op:
        if "sharepoint_upload_status" in existing_columns:
            batch_op.drop_column("sharepoint_upload_status")
        if "sharepoint_drive_id" in existing_columns:
            batch_op.drop_column("sharepoint_drive_id")
        if "sharepoint_item_id" in existing_columns:
            batch_op.drop_column("sharepoint_item_id")
