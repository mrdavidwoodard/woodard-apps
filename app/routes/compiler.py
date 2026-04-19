import copy
import json

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.models import Document, ExtractionResult, ReviewAction, TaxReturn, utc_now
from app.services.package_readiness import package_document_stats

compiler_bp = Blueprint("compiler", __name__, url_prefix="/compiler")

STRUCTURED_FIELD_SETS = {
    "organizer": [
        ("client_name", "Client Name"),
        ("tax_year", "Tax Year"),
        ("notes", "Notes"),
    ],
    "w2": [
        ("employer_name", "Employer Name"),
        ("ein", "EIN"),
        ("wages", "Wages"),
        ("federal_withholding", "Federal Withholding"),
        ("state_wages", "State Wages"),
    ],
    "1099_int": [
        ("payer_name", "Payer Name"),
        ("interest_income", "Interest Income"),
        ("federal_withholding", "Federal Withholding"),
    ],
}

PACKAGE_REVIEW_CATEGORIES = {
    "organizer": "Organizer",
    "w2": "Wages and Withholding",
    "1099_int": "Interest Income",
    "1099": "Other Documents",
    "1099_div": "Dividend Income",
    "schedule_c": "Business / Self-Employment",
    "k1": "K-1 / Pass-Through",
    "1098": "Deductions / Mortgage / Prior Year",
    "prior_year": "Deductions / Mortgage / Prior Year",
}

PACKAGE_REVIEW_SECTION_ORDER = [
    "Organizer",
    "Wages and Withholding",
    "Interest Income",
    "Dividend Income",
    "Business / Self-Employment",
    "K-1 / Pass-Through",
    "Deductions / Mortgage / Prior Year",
    "Other Documents",
]


def latest_result_for(document):
    return document.extraction_results.order_by(ExtractionResult.created_at.desc()).first()


def review_history_for(document):
    return document.review_actions.order_by(ReviewAction.reviewed_at.desc()).all()


def normalized_document_type(document, latest_result=None):
    value = None
    if latest_result and latest_result.document_type_detected:
        value = latest_result.document_type_detected
    else:
        value = document.document_type
    return (value or "").lower().replace("-", "_")


def structured_fields_for(document, latest_result=None):
    return STRUCTURED_FIELD_SETS.get(normalized_document_type(document, latest_result), [])


def readable_field_label(field_name):
    return (field_name or "").replace("_", " ").title()


def extracted_fields_payload(latest_result):
    if not latest_result or not isinstance(latest_result.extracted_json, dict):
        return {}
    fields = latest_result.extracted_json.get("fields")
    return fields if isinstance(fields, dict) else {}


def has_structured_field_confidence(latest_result):
    return bool(extracted_fields_payload(latest_result))


def extraction_value(latest_result, field_name):
    if not latest_result or not latest_result.extracted_json:
        return ""
    fields = extracted_fields_payload(latest_result)
    if field_name in fields and isinstance(fields[field_name], dict):
        value = fields[field_name].get("value")
    else:
        value = latest_result.extracted_json.get(field_name)
    return "" if value is None else value


def extraction_confidence(latest_result, field_name):
    field_payload = extracted_fields_payload(latest_result).get(field_name)
    if not isinstance(field_payload, dict):
        return None
    confidence = field_payload.get("confidence")
    return confidence if isinstance(confidence, (int, float)) else None


def confidence_level(confidence):
    if confidence is None:
        return None
    if confidence >= 0.90:
        return "high"
    if confidence >= 0.75:
        return "medium"
    return "low"


def confidence_badge_label(confidence):
    level = confidence_level(confidence)
    return level.title() if level else ""


def confidence_badge_class(confidence):
    level = confidence_level(confidence)
    return f"confidence-{level}" if level else ""


def field_reviewer_updated(latest_result, field_name):
    field_payload = extracted_fields_payload(latest_result).get(field_name)
    return bool(isinstance(field_payload, dict) and field_payload.get("reviewer_updated"))


def confidence_summary(latest_result, field_defs):
    summary = {"high": 0, "medium": 0, "low": 0, "total": 0}
    for field_name, _label in field_defs:
        level = confidence_level(extraction_confidence(latest_result, field_name))
        if level:
            summary[level] += 1
            summary["total"] += 1
    return summary


def category_for_document(document, latest_result=None):
    document_type = normalized_document_type(document, latest_result)
    return PACKAGE_REVIEW_CATEGORIES.get(document_type, "Other Documents")


def extracted_rows_for(document, latest_result):
    if not latest_result or not isinstance(latest_result.extracted_json, dict):
        return []

    fields = extracted_fields_payload(latest_result)
    if fields:
        rows = []
        for field_name, payload in fields.items():
            if isinstance(payload, dict):
                value = payload.get("value")
                confidence = payload.get("confidence")
            else:
                value = payload
                confidence = None
            rows.append(
                {
                    "label": readable_field_label(field_name),
                    "value": value,
                    "confidence": confidence if isinstance(confidence, (int, float)) else None,
                }
            )
        return rows

    rows = []
    for field_name, value in latest_result.extracted_json.items():
        if isinstance(value, (dict, list)):
            rows.append({"label": readable_field_label(field_name), "json_text": json.dumps(value, indent=2, sort_keys=True)})
        else:
            rows.append({"label": readable_field_label(field_name), "value": value, "confidence": None})
    return rows


def grouped_extracted_data_for(package):
    grouped = {section: [] for section in PACKAGE_REVIEW_SECTION_ORDER}
    for document in package.documents.order_by(Document.uploaded_at.asc()).all():
        latest_result = latest_result_for(document)
        if not latest_result:
            continue
        category = category_for_document(document, latest_result)
        grouped.setdefault(category, [])
        grouped[category].append(
            {
                "document": document,
                "latest_result": latest_result,
                "rows": extracted_rows_for(document, latest_result),
                "json_text": json.dumps(latest_result.extracted_json or {}, indent=2, sort_keys=True),
            }
        )
    return [(section, grouped.get(section, [])) for section in PACKAGE_REVIEW_SECTION_ORDER if grouped.get(section)]


def package_review_issues_for(package):
    issues = []
    for document in package.documents.order_by(Document.uploaded_at.asc()).all():
        latest_result = latest_result_for(document)
        if document.status == "exception":
            issues.append({"document": document, "summary": "Document is in exception status."})
        if not latest_result:
            issues.append({"document": document, "summary": "No extraction result is available."})
            continue
        for field_name, payload in extracted_fields_payload(latest_result).items():
            if isinstance(payload, dict) and confidence_level(payload.get("confidence")) == "low":
                issues.append(
                    {
                        "document": document,
                        "summary": f"Low confidence field: {readable_field_label(field_name)}.",
                    }
                )
    return issues


def can_approve_package(package):
    documents = package.documents.all()
    has_extracted_document = any(document.extraction_results.count() for document in documents)
    return has_extracted_document and not package_review_issues_for(package)


def has_saved_corrections(document):
    return document.review_actions.filter(ReviewAction.action_type == "corrected").count() > 0


def build_structured_json_from_form(latest_result, field_defs):
    if has_structured_field_confidence(latest_result):
        corrected = copy.deepcopy(latest_result.extracted_json)
        corrected.setdefault("fields", {})
        for field_name, _label in field_defs:
            new_value = request.form.get(field_name, "").strip()
            existing_field = corrected["fields"].get(field_name, {})
            if not isinstance(existing_field, dict):
                existing_field = {"value": existing_field}
            previous_value = "" if existing_field.get("value") is None else str(existing_field.get("value"))
            existing_field["value"] = new_value
            if new_value != previous_value:
                existing_field["reviewer_updated"] = True
            corrected["fields"][field_name] = existing_field
        return corrected

    corrected = {}
    for field_name, _label in field_defs:
        corrected[field_name] = request.form.get(field_name, "").strip()
    return corrected


def all_documents_approved(tax_return):
    documents = tax_return.documents.all()
    return bool(documents) and all(document.status == "approved" for document in documents)


def mark_ready_for_prep_if_complete(tax_return):
    if all_documents_approved(tax_return) and not tax_return.is_waiting_on_client:
        tax_return.status = "ready_for_prep"


def create_review_action(document, action_type, latest_result=None, notes=None, field_changes=None):
    review_action = ReviewAction(
        tax_return=document.tax_return,
        document=document,
        extraction_result=latest_result,
        reviewed_by_user=current_user,
        action_type=action_type,
        notes=notes,
        field_changes_json=field_changes,
    )
    db.session.add(review_action)
    return review_action


@compiler_bp.route("/queue")
@login_required
def queue():
    documents = Document.query.filter_by(status="review_pending").order_by(Document.uploaded_at.desc()).all()
    rows = [{"document": document, "latest_result": latest_result_for(document)} for document in documents]
    return render_template("compiler/queue.html", rows=rows)


@compiler_bp.route("/package/<int:package_id>")
@login_required
def package_review(package_id):
    package = TaxReturn.query.get_or_404(package_id)
    stats = package_document_stats(package)
    issues = package_review_issues_for(package)
    return render_template(
        "compiler/package_review.html",
        package=package,
        package_stats=stats,
        grouped_data=grouped_extracted_data_for(package),
        issues=issues,
        can_approve=can_approve_package(package),
        confidence_badge_class=confidence_badge_class,
        confidence_badge_label=confidence_badge_label,
    )


@compiler_bp.route("/package/<int:package_id>/approve", methods=["POST"])
@login_required
def approve_package(package_id):
    package = TaxReturn.query.get_or_404(package_id)
    if not can_approve_package(package):
        flash("This package has unresolved issues that must be reviewed before approval.", "danger")
        return redirect(url_for("compiler.package_review", package_id=package.id))

    package.status = "ready_for_prep"
    package.review_completed_at = utc_now()
    db.session.commit()

    flash("Package approved for prep.", "success")
    return redirect(url_for("compiler.package_review", package_id=package.id))


@compiler_bp.route("/document/<int:document_id>")
@login_required
def document_detail(document_id):
    document = Document.query.get_or_404(document_id)
    latest_result = latest_result_for(document)
    extracted_json_text = json.dumps(latest_result.extracted_json, indent=2, sort_keys=True) if latest_result else ""
    field_defs = structured_fields_for(document, latest_result)
    field_confidence_summary = confidence_summary(latest_result, field_defs)
    return render_template(
        "compiler/document_detail.html",
        document=document,
        latest_result=latest_result,
        extracted_json_text=extracted_json_text,
        field_defs=field_defs,
        extraction_value=extraction_value,
        extraction_confidence=extraction_confidence,
        confidence_badge_label=confidence_badge_label,
        confidence_badge_class=confidence_badge_class,
        confidence_level=confidence_level,
        field_reviewer_updated=field_reviewer_updated,
        field_confidence_summary=field_confidence_summary,
        has_saved_corrections=has_saved_corrections(document),
        review_actions=review_history_for(document),
    )


@compiler_bp.route("/document/<int:document_id>/approve", methods=["POST"])
@login_required
def approve(document_id):
    document = Document.query.get_or_404(document_id)
    latest_result = latest_result_for(document)

    create_review_action(document, "approved", latest_result=latest_result)
    document.status = "approved"
    mark_ready_for_prep_if_complete(document.tax_return)
    db.session.commit()

    flash("Document approved.", "success")
    return redirect(url_for("compiler.document_detail", document_id=document.id))


@compiler_bp.route("/document/<int:document_id>/correct", methods=["POST"])
@login_required
def correct(document_id):
    document = Document.query.get_or_404(document_id)
    latest_result = latest_result_for(document)
    if not latest_result:
        flash("This document does not have an extraction result to correct.", "danger")
        return redirect(url_for("compiler.document_detail", document_id=document.id))

    raw_json = request.form.get("extracted_json", "").strip()
    try:
        corrected_json = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        flash(f"Corrected extraction JSON is invalid: {exc.msg}.", "danger")
        return redirect(url_for("compiler.document_detail", document_id=document.id))

    latest_result.extracted_json = corrected_json
    create_review_action(
        document,
        "corrected",
        latest_result=latest_result,
        notes="Extraction result manually corrected and approved.",
        field_changes={"summary": "Extraction result manually corrected in Compiler."},
    )
    document.status = "approved"
    mark_ready_for_prep_if_complete(document.tax_return)
    db.session.commit()

    flash("Correction saved and document approved.", "success")
    return redirect(url_for("compiler.document_detail", document_id=document.id))


@compiler_bp.route("/document/<int:document_id>/save-corrections", methods=["POST"])
@login_required
def save_corrections(document_id):
    document = Document.query.get_or_404(document_id)
    latest_result = latest_result_for(document)
    if not latest_result:
        flash("No extraction data is available to correct.", "danger")
        return redirect(url_for("compiler.document_detail", document_id=document.id))

    field_defs = structured_fields_for(document, latest_result)
    if field_defs:
        corrected_json = build_structured_json_from_form(latest_result, field_defs)
    else:
        raw_json = request.form.get("extracted_json", "").strip()
        try:
            corrected_json = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            flash(f"Corrected extraction JSON is invalid: {exc.msg}.", "danger")
            return redirect(url_for("compiler.document_detail", document_id=document.id))

    latest_result.extracted_json = corrected_json
    create_review_action(
        document,
        "corrected",
        latest_result=latest_result,
        notes="Extraction corrections saved for reviewer validation.",
        field_changes={"summary": "Reviewer updated extracted fields in Compiler."},
    )
    db.session.commit()

    flash("Corrections saved.", "success")
    return redirect(url_for("compiler.document_detail", document_id=document.id))


@compiler_bp.route("/document/<int:document_id>/escalate", methods=["POST"])
@login_required
def escalate(document_id):
    document = Document.query.get_or_404(document_id)
    latest_result = latest_result_for(document)
    notes = request.form.get("notes", "").strip() or "Marked for review from Compiler."

    create_review_action(document, "escalated", latest_result=latest_result, notes=notes)
    document.status = "exception"
    document.tax_return.status = "on_hold"
    db.session.commit()

    flash("Document escalated for follow-up.", "success")
    return redirect(url_for("compiler.document_detail", document_id=document.id))
