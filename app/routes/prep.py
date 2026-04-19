import json

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app import db
from app.models import Document, ExtractionResult, TaxReturn, utc_now

prep_bp = Blueprint("prep", __name__, url_prefix="/prep")


def approved_documents_for(tax_return):
    return tax_return.documents.filter(Document.status == "approved").order_by(Document.uploaded_at.desc()).all()


def latest_result_for(document):
    return document.extraction_results.order_by(ExtractionResult.created_at.desc()).first()


def format_other_json(value):
    return json.dumps(value or {}, indent=2, sort_keys=True)


def extracted_value(extracted, field_name):
    fields = extracted.get("fields") if isinstance(extracted, dict) else None
    if isinstance(fields, dict) and isinstance(fields.get(field_name), dict):
        return fields[field_name].get("value")
    return extracted.get(field_name) if isinstance(extracted, dict) else None


def extracted_fields(extracted):
    fields = extracted.get("fields") if isinstance(extracted, dict) else None
    if isinstance(fields, dict):
        return fields
    return {}


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


def readable_field_label(field_name):
    return (field_name or "").replace("_", " ").title()


PREP_SECTION_ORDER = [
    "Taxpayer / Client Info",
    "Wages and Withholding",
    "Interest and Dividend Income",
    "Business / Self-Employment",
    "K-1 / Pass-Through Income",
    "Deductions / Mortgage / Prior Year",
    "Notes / Follow-Up",
]


def prep_section_for(document, latest_result=None):
    document_type = ((latest_result.document_type_detected if latest_result else None) or document.document_type or "").lower()
    document_type = document_type.replace("-", "_").replace(" ", "_")
    if document_type == "organizer":
        return "Taxpayer / Client Info"
    if document_type == "w2":
        return "Wages and Withholding"
    if document_type in {"1099", "1099_int", "1099_div"}:
        return "Interest and Dividend Income"
    if document_type in {"schedule_c", "business", "self_employment"}:
        return "Business / Self-Employment"
    if document_type in {"k1", "k_1"}:
        return "K-1 / Pass-Through Income"
    if document_type in {"1098", "mortgage", "prior_year"}:
        return "Deductions / Mortgage / Prior Year"
    return "Notes / Follow-Up"


def worksheet_rows_for_document(document, latest_result):
    extracted = latest_result.extracted_json or {}
    field_payloads = extracted_fields(extracted)
    rows = []
    if field_payloads:
        for field_name, payload in field_payloads.items():
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
                    "source_document": document,
                    "confidence": confidence if isinstance(confidence, (int, float)) else None,
                }
            )
        return rows

    for field_name, value in extracted.items():
        if isinstance(value, (dict, list)):
            continue
        rows.append(
            {
                "label": readable_field_label(field_name),
                "value": value,
                "source_document": document,
                "confidence": None,
            }
        )
    return rows


def prep_worksheet_sections_for(package):
    sections = {section: [] for section in PREP_SECTION_ORDER}
    for document in package.documents.order_by(Document.uploaded_at.asc()).all():
        latest_result = latest_result_for(document)
        if not latest_result:
            continue
        section = prep_section_for(document, latest_result)
        sections.setdefault(section, [])
        sections[section].extend(worksheet_rows_for_document(document, latest_result))
    return [(section, rows) for section, rows in sections.items()]


def prep_summary_for(documents):
    summary = []
    for document in documents:
        latest_result = latest_result_for(document)
        if not latest_result:
            summary.append({"document": document, "result": None, "kind": "missing", "fields": {}, "json_text": ""})
            continue

        extracted = latest_result.extracted_json or {}
        detected_type = (latest_result.document_type_detected or document.document_type or "").lower()
        if detected_type == "w2":
            fields = {
                "Employer": extracted_value(extracted, "employer_name"),
                "EIN": extracted_value(extracted, "ein"),
                "Wages": extracted_value(extracted, "wages"),
                "Federal Withholding": extracted_value(extracted, "federal_withholding"),
                "State Wages": extracted_value(extracted, "state_wages"),
            }
            summary.append({"document": document, "result": latest_result, "kind": "w2", "fields": fields, "json_text": ""})
        elif detected_type in {"1099_int", "1099-int"}:
            fields = {
                "Payer": extracted_value(extracted, "payer_name"),
                "Interest Income": extracted_value(extracted, "interest_income"),
                "Federal Withholding": extracted_value(extracted, "federal_withholding"),
            }
            summary.append({"document": document, "result": latest_result, "kind": "1099_int", "fields": fields, "json_text": ""})
        else:
            summary.append({
                "document": document,
                "result": latest_result,
                "kind": "other",
                "fields": {},
                "json_text": format_other_json(extracted),
            })
    return summary


@prep_bp.route("/queue")
@login_required
def queue():
    tax_returns = (
        TaxReturn.query.filter_by(status="ready_for_prep")
        .order_by(TaxReturn.tax_year.desc(), TaxReturn.created_at.desc())
        .all()
    )
    rows = [
        {
            "tax_return": tax_return,
            "approved_document_count": tax_return.documents.filter(Document.status == "approved").count(),
        }
        for tax_return in tax_returns
    ]
    return render_template("prep/queue.html", rows=rows)


@prep_bp.route("/tax-return/<int:tax_return_id>")
@login_required
def detail(tax_return_id):
    tax_return = TaxReturn.query.get_or_404(tax_return_id)
    approved_documents = approved_documents_for(tax_return)
    document_rows = [
        {"document": document, "latest_result": latest_result_for(document)}
        for document in approved_documents
    ]
    return render_template(
        "prep/detail.html",
        tax_return=tax_return,
        approved_documents=approved_documents,
        document_rows=document_rows,
        prep_summary=prep_summary_for(approved_documents),
    )


@prep_bp.route("/package/<int:package_id>")
@login_required
def worksheet(package_id):
    package = TaxReturn.query.get_or_404(package_id)
    return render_template(
        "prep/worksheet.html",
        package=package,
        worksheet_sections=prep_worksheet_sections_for(package),
        confidence_badge_class=confidence_badge_class,
        confidence_badge_label=confidence_badge_label,
    )


@prep_bp.route("/package/<int:package_id>/notes", methods=["POST"])
@login_required
def update_notes(package_id):
    package = TaxReturn.query.get_or_404(package_id)
    package.prep_notes = request.form.get("prep_notes", "").strip() or None
    db.session.commit()
    flash("Prep worksheet notes saved.", "success")
    return redirect(url_for("prep.worksheet", package_id=package.id))


@prep_bp.route("/tax-return/<int:tax_return_id>/start", methods=["POST"])
@login_required
def start(tax_return_id):
    tax_return = TaxReturn.query.get_or_404(tax_return_id)
    tax_return.status = "in_prep"
    if not tax_return.prep_started_at:
        tax_return.prep_started_at = utc_now()
    db.session.commit()
    flash("Prep started.", "success")
    next_url = request.form.get("next") or url_for("prep.detail", tax_return_id=tax_return.id)
    return redirect(next_url)


@prep_bp.route("/tax-return/<int:tax_return_id>/complete", methods=["POST"])
@login_required
def complete(tax_return_id):
    tax_return = TaxReturn.query.get_or_404(tax_return_id)
    tax_return.status = "in_review"
    tax_return.prep_completed_at = utc_now()
    db.session.commit()
    flash("Prep completed and moved to review.", "success")
    next_url = request.form.get("next") or url_for("prep.detail", tax_return_id=tax_return.id)
    return redirect(next_url)


@prep_bp.route("/package/<int:package_id>/send-back", methods=["POST"])
@login_required
def send_back(package_id):
    package = TaxReturn.query.get_or_404(package_id)
    package.status = "organizer_review_pending"
    db.session.commit()
    flash("Package sent back to review.", "warning")
    return redirect(url_for("prep.worksheet", package_id=package.id))
