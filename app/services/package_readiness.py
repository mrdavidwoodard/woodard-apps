from app import db
from app.models import OrganizerSection, PackageDocumentRequirement, utc_now


DEFAULT_ORGANIZER_SECTIONS = [
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

DEFAULT_PACKAGE_REQUIREMENTS = [
    ("Client Information", "organizer", "Organizer"),
    ("Wages", "w2", "W-2"),
    ("Interest & Dividends", "1099_int", "1099-INT"),
    ("Capital Gains", "1099_b", "1099-B"),
    ("K-1 Income", "k1", "K-1"),
]

DOCUMENT_TYPE_SECTION_MAP = {
    "organizer": "Client Information",
    "source_document": "General",
    "w2": "Wages",
    "1099_int": "Interest & Dividends",
    "1099_div": "Interest & Dividends",
    "1099": "Interest & Dividends",
    "1099_b": "Capital Gains",
    "brokerage": "Capital Gains",
    "schedule_c": "Business Income",
    "business": "Business Income",
    "rental": "Rental Income",
    "schedule_e": "Rental Income",
    "k1": "K-1 Income",
    "k_1": "K-1 Income",
    "1098": "Deductions",
    "mortgage": "Deductions",
    "education": "Education",
    "1098_t": "Education",
    "hsa": "HSA",
    "5498_sa": "HSA",
    "other": "General",
}


def normalize_document_type(document_type):
    return (document_type or "").strip().lower().replace("-", "_").replace(" ", "_")


def requirement_display_name(document_type):
    labels = {
        "organizer": "Organizer",
        "w2": "W-2",
        "1099": "1099",
        "1099_int": "1099-INT",
        "source_document": "Source Document",
        "other": "Other",
    }
    normalized = normalize_document_type(document_type)
    return labels.get(normalized, normalized.replace("_", " ").title() or "Source Document")


def seed_default_organizer_sections():
    for name, description, display_order in DEFAULT_ORGANIZER_SECTIONS:
        section = OrganizerSection.query.filter_by(name=name).first()
        if not section:
            db.session.add(
                OrganizerSection(
                    name=name,
                    description=description,
                    display_order=display_order,
                )
            )
        else:
            section.description = description
            section.display_order = display_order
    db.session.flush()


def create_default_sections(package):
    """Ensure the standard organizer sections exist for an intake package."""
    seed_default_organizer_sections()
    return OrganizerSection.query.order_by(OrganizerSection.display_order.asc(), OrganizerSection.name.asc()).all()


def create_default_requirements(package):
    """Create the starter required checklist for a newly created intake package."""
    create_default_sections(package)
    existing_document_types = {
        normalize_document_type(requirement.document_type)
        for requirement in package.package_document_requirements.all()
    }

    for section_name, document_type, display_name in DEFAULT_PACKAGE_REQUIREMENTS:
        normalized_type = normalize_document_type(document_type)
        if normalized_type in existing_document_types:
            continue

        section = OrganizerSection.query.filter_by(name=section_name).first()
        if not section:
            section = OrganizerSection.query.filter_by(name="General").first()

        requirement = PackageDocumentRequirement(
            tax_return=package,
            section=section,
            name=display_name,
            document_type=normalized_type,
            display_name=display_name,
            is_required=True,
            is_received=False,
        )
        db.session.add(requirement)
    db.session.flush()


def organizer_section_for_document_type(document_type):
    seed_default_organizer_sections()
    normalized = normalize_document_type(document_type)
    section_name = DOCUMENT_TYPE_SECTION_MAP.get(normalized, "General")
    section = OrganizerSection.query.filter_by(name=section_name).first()
    if not section:
        section = OrganizerSection(name="General", description="Legacy and uncategorized intake requirements.", display_order=0)
        db.session.add(section)
        db.session.flush()
    return section


def requirements_for(package):
    assign_default_sections(package)
    return package.package_document_requirements.outerjoin(OrganizerSection).order_by(
        OrganizerSection.display_order.asc(),
        PackageDocumentRequirement.is_required.desc(),
        PackageDocumentRequirement.display_name.asc(),
    ).all()


def assign_default_sections(package):
    seed_default_organizer_sections()
    changed = False
    general_section = OrganizerSection.query.filter_by(name="General").first()
    for requirement in package.package_document_requirements.all():
        if not requirement.name:
            requirement.name = requirement.display_name
            changed = True
        if not requirement.section:
            requirement.section = organizer_section_for_document_type(requirement.document_type) or general_section
            changed = True
    if changed:
        db.session.flush()
    return changed


def find_or_create_requirement_for_document(package, document):
    document_type = normalize_document_type(document.document_type)
    requirement = package.package_document_requirements.filter_by(document_type=document_type, is_required=True).first()
    if not requirement:
        section = organizer_section_for_document_type(document_type)
        requirement = PackageDocumentRequirement(
            tax_return=package,
            section=section,
            name=requirement_display_name(document_type),
            document_type=document_type,
            display_name=requirement_display_name(document_type),
            is_required=True,
        )
        db.session.add(requirement)
        db.session.flush()
    return requirement


def match_document_to_requirement(package, document):
    requirement = find_or_create_requirement_for_document(package, document)
    requirement.document = document
    requirement.is_received = True
    requirement.received_at = requirement.received_at or utc_now()
    return requirement


def sync_requirements_from_documents(package):
    changed = False
    for document in package.documents.all():
        requirement = find_or_create_requirement_for_document(package, document)
        if not requirement.is_received or requirement.document_id != document.id:
            requirement.document = document
            requirement.is_received = True
            requirement.received_at = requirement.received_at or document.uploaded_at or utc_now()
            changed = True
    return changed


def completeness_summary(package):
    assign_default_sections(package)
    required_requirements = package.package_document_requirements.filter_by(is_required=True).all()
    total_required = len(required_requirements)
    received_required = sum(1 for requirement in required_requirements if requirement.is_received)
    missing_required = total_required - received_required
    section_summaries = section_completion_summary(package)
    required_sections = [section for section in section_summaries if section["required_count"] > 0]
    all_required_sections_complete = bool(required_sections) and all(
        section["status"] == "complete" for section in required_sections
    )
    return {
        "total_required": total_required,
        "received_required": received_required,
        "missing_required": missing_required,
        "section_summaries": section_summaries,
        "is_complete": all_required_sections_complete,
    }


def section_completion_summary(package):
    assign_default_sections(package)
    sections = OrganizerSection.query.order_by(OrganizerSection.display_order.asc(), OrganizerSection.name.asc()).all()
    summaries = []
    for section in sections:
        requirements = [
            requirement
            for requirement in package.package_document_requirements.filter_by(section_id=section.id).all()
        ]
        required = [requirement for requirement in requirements if requirement.is_required]
        received = [requirement for requirement in required if requirement.is_received]
        if not required:
            status = "not_started"
        elif len(received) == len(required):
            status = "complete"
        elif received:
            status = "in_progress"
        else:
            status = "not_started"
        summaries.append(
            {
                "section": section,
                "requirements": requirements,
                "required_count": len(required),
                "received_count": len(received),
                "missing_count": len(required) - len(received),
                "status": status,
            }
        )
    return summaries


def missing_required_items(package):
    assign_default_sections(package)
    missing = []
    for requirement in package.package_document_requirements.filter_by(is_required=True, is_received=False).all():
        missing.append(
            {
                "name": requirement.name or requirement.display_name,
                "document_type": requirement.document_type,
                "section": requirement.section.name if requirement.section else "General",
            }
        )
    return missing


def recalculate_package_readiness(package):
    sync_requirements_from_documents(package)
    summary = completeness_summary(package)
    can_be_marked_ready = package.status in {"new", "documents_received", "waiting_on_client"}
    package.is_ready_for_extraction = summary["is_complete"] and can_be_marked_ready
    package.is_waiting_on_client = not summary["is_complete"] and can_be_marked_ready
    if package.is_ready_for_extraction and package.status in {"new", "waiting_on_client"}:
        package.status = "documents_received"
    elif package.is_waiting_on_client and package.status in {"new", "documents_received"}:
        package.status = "waiting_on_client"
    return summary


def package_document_stats(package):
    documents = package.documents.all()
    summary = completeness_summary(package)
    summary.update(
        {
            "total": len(documents),
            "review_pending": sum(1 for document in documents if document.status == "review_pending"),
            "exceptions": sum(1 for document in documents if document.status == "exception"),
            "extracted": sum(1 for document in documents if document.extraction_results.count()),
            "missing_items": missing_required_items(package),
        }
    )
    return summary
