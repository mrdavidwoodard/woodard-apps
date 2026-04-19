import copy
import json

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.models import Document, ExtractionResult, ReviewAction

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
