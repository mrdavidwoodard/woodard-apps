"""add taxdome linkage fields

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-04-19 12:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    client_columns = {column["name"] for column in inspector.get_columns("clients")}
    with op.batch_alter_table("clients", schema=None) as batch_op:
        if "taxdome_client_id" not in client_columns:
            batch_op.add_column(sa.Column("taxdome_client_id", sa.String(length=120), nullable=True))
            batch_op.create_index("ix_clients_taxdome_client_id", ["taxdome_client_id"], unique=False)

    tax_return_columns = {column["name"] for column in inspector.get_columns("tax_returns")}
    with op.batch_alter_table("tax_returns", schema=None) as batch_op:
        if "source_system" not in tax_return_columns:
            batch_op.add_column(
                sa.Column("source_system", sa.String(length=50), nullable=False, server_default="internal")
            )
        if "taxdome_job_id" not in tax_return_columns:
            batch_op.add_column(sa.Column("taxdome_job_id", sa.String(length=120), nullable=True))
            batch_op.create_index("ix_tax_returns_taxdome_job_id", ["taxdome_job_id"], unique=False)
        if "taxdome_organizer_request_id" not in tax_return_columns:
            batch_op.add_column(sa.Column("taxdome_organizer_request_id", sa.String(length=120), nullable=True))
            batch_op.create_index(
                "ix_tax_returns_taxdome_organizer_request_id",
                ["taxdome_organizer_request_id"],
                unique=False,
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    tax_return_columns = {column["name"] for column in inspector.get_columns("tax_returns")}
    with op.batch_alter_table("tax_returns", schema=None) as batch_op:
        if "taxdome_organizer_request_id" in tax_return_columns:
            batch_op.drop_index("ix_tax_returns_taxdome_organizer_request_id")
            batch_op.drop_column("taxdome_organizer_request_id")
        if "taxdome_job_id" in tax_return_columns:
            batch_op.drop_index("ix_tax_returns_taxdome_job_id")
            batch_op.drop_column("taxdome_job_id")
        if "source_system" in tax_return_columns:
            batch_op.drop_column("source_system")

    client_columns = {column["name"] for column in inspector.get_columns("clients")}
    with op.batch_alter_table("clients", schema=None) as batch_op:
        if "taxdome_client_id" in client_columns:
            batch_op.drop_index("ix_clients_taxdome_client_id")
            batch_op.drop_column("taxdome_client_id")
