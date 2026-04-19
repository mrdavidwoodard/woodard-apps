"""add extraction jobs and results

Revision ID: 9f8a1c2d3e4b
Revises: 6c0a7f9b2d1e
Create Date: 2026-04-18 18:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9f8a1c2d3e4b"
down_revision = "6c0a7f9b2d1e"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "extraction_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("tax_return_id", sa.Integer(), nullable=False),
        sa.Column("job_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["tax_return_id"], ["tax_returns.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("extraction_jobs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_extraction_jobs_document_id"), ["document_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_extraction_jobs_tax_return_id"), ["tax_return_id"], unique=False)

    op.create_table(
        "extraction_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("extraction_job_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("tax_return_id", sa.Integer(), nullable=False),
        sa.Column("document_type_detected", sa.String(length=80), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("validation_status", sa.String(length=50), nullable=False),
        sa.Column("is_ready_for_review", sa.Boolean(), nullable=False),
        sa.Column("extracted_json", sa.JSON(), nullable=False),
        sa.Column("validation_messages_json", sa.JSON(), nullable=True),
        sa.Column("model_name", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["extraction_job_id"], ["extraction_jobs.id"]),
        sa.ForeignKeyConstraint(["tax_return_id"], ["tax_returns.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("extraction_results", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_extraction_results_document_id"), ["document_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_extraction_results_extraction_job_id"), ["extraction_job_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_extraction_results_tax_return_id"), ["tax_return_id"], unique=False)


def downgrade():
    with op.batch_alter_table("extraction_results", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_extraction_results_tax_return_id"))
        batch_op.drop_index(batch_op.f("ix_extraction_results_extraction_job_id"))
        batch_op.drop_index(batch_op.f("ix_extraction_results_document_id"))

    op.drop_table("extraction_results")

    with op.batch_alter_table("extraction_jobs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_extraction_jobs_tax_return_id"))
        batch_op.drop_index(batch_op.f("ix_extraction_jobs_document_id"))

    op.drop_table("extraction_jobs")
