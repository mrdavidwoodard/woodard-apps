from app import db
from app.models import PackageDocumentRequirement, utc_now


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


def requirements_for(package):
    return package.package_document_requirements.order_by(
        PackageDocumentRequirement.is_required.desc(),
        PackageDocumentRequirement.display_name.asc(),
    ).all()


def find_or_create_requirement_for_document(package, document):
    document_type = normalize_document_type(document.document_type)
    requirement = package.package_document_requirements.filter_by(document_type=document_type, is_required=True).first()
    if not requirement:
        requirement = PackageDocumentRequirement(
            tax_return=package,
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
    required_requirements = package.package_document_requirements.filter_by(is_required=True).all()
    total_required = len(required_requirements)
    received_required = sum(1 for requirement in required_requirements if requirement.is_received)
    missing_required = total_required - received_required
    return {
        "total_required": total_required,
        "received_required": received_required,
        "missing_required": missing_required,
        "is_complete": total_required > 0 and missing_required == 0,
    }


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
        }
    )
    return summary
