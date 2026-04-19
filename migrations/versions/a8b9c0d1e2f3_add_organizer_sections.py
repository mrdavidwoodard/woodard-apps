"""add organizer sections

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-04-19 11:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a8b9c0d1e2f3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


DEFAULT_SECTIONS = [
    ("General", "Legacy and uncategorized intake requirements.", 0),
    ("Client Information", None, 1),
    ("Dependents", None, 2),
    ("Misc Questions", None, 3),
    ("Wages", None, 4),
    ("Interest & Dividends", None, 5),
    ("Capital Gains", None, 6),
    ("Business Income", None, 7),
    ("Rental Income", None, 8),
    ("K-1 Income", None, 9),
    ("Adjustments", None, 10),
    ("Deductions", None, 11),
    ("Education", None, 12),
    ("HSA", None, 13),
    ("Other Taxes / Credits", None, 14),
]


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("organizer_sections"):
        op.create_table(
            "organizer_sections",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("display_order", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )

    section_table = sa.table(
        "organizer_sections",
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("display_order", sa.Integer),
    )
    existing_sections = {row[0] for row in bind.execute(sa.text("SELECT name FROM organizer_sections")).fetchall()}
    rows = [
        {"name": name, "description": description, "display_order": display_order}
        for name, description, display_order in DEFAULT_SECTIONS
        if name not in existing_sections
    ]
    if rows:
        op.bulk_insert(section_table, rows)

    existing_columns = {column["name"] for column in inspector.get_columns("package_document_requirements")}
    with op.batch_alter_table("package_document_requirements", schema=None) as batch_op:
        if "section_id" not in existing_columns:
            batch_op.add_column(sa.Column("section_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_package_document_requirements_section_id_organizer_sections",
                "organizer_sections",
                ["section_id"],
                ["id"],
            )
            batch_op.create_index("ix_package_document_requirements_section_id", ["section_id"], unique=False)
        if "name" not in existing_columns:
            batch_op.add_column(sa.Column("name", sa.String(length=120), nullable=True))

    general_id = bind.execute(sa.text("SELECT id FROM organizer_sections WHERE name = 'General'")).scalar()
    if general_id:
        bind.execute(
            sa.text(
                "UPDATE package_document_requirements "
                "SET section_id = :section_id "
                "WHERE section_id IS NULL"
            ),
            {"section_id": general_id},
        )
    bind.execute(
        sa.text(
            "UPDATE package_document_requirements "
            "SET name = display_name "
            "WHERE name IS NULL"
        )
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("package_document_requirements")}
    with op.batch_alter_table("package_document_requirements", schema=None) as batch_op:
        if "name" in existing_columns:
            batch_op.drop_column("name")
        if "section_id" in existing_columns:
            batch_op.drop_index("ix_package_document_requirements_section_id")
            batch_op.drop_constraint("fk_package_document_requirements_section_id_organizer_sections", type_="foreignkey")
            batch_op.drop_column("section_id")

    if inspector.has_table("organizer_sections"):
        op.drop_table("organizer_sections")
