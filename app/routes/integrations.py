import logging
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required
from werkzeug.utils import secure_filename

from app import db
from app.models import Client, Document, TaxReturn, User
from app.routes.ingester import allowed_file, get_upload_destination
from app.services import sharepoint
from app.services.package_readiness import (
    classify_document_text,
    detect_document_type_from_filename,
    extract_pdf_text,
    match_uploaded_document_to_requirement,
    recalculate_package_readiness,
)
from app.services.structured_extraction import (
    SUPPORTED_STRUCTURED_TYPES,
    canonical_structured_type,
    run_structured_extraction_for_document,
)
from app.services.taxdome import apply_taxdome_organizer_request_event, find_or_create_client

integrations_bp = Blueprint("integrations", __name__, url_prefix="/integrations")
logger = logging.getLogger(__name__)


def append_classification_note(document, note):
    if not note:
        return
    existing_notes = document.classification_notes or ""
    if note in existing_notes:
        return
    document.classification_notes = f"{existing_notes} {note}".strip()


@integrations_bp.route("/taxdome/organizer-request", methods=["GET", "POST"])
@login_required
def taxdome_organizer_request():
    users = User.query.filter_by(is_active=True).order_by(User.last_name.asc(), User.first_name.asc()).all()

    if request.method == "POST":
        form_data = request.form.to_dict()
        required_values = [
            form_data.get("client_display_name", "").strip(),
            form_data.get("client_type", "").strip(),
            form_data.get("tax_year", "").strip(),
            form_data.get("work_type", "").strip(),
        ]
        if not all(required_values):
            flash("Client display name, client type, tax year, and work type are required.", "danger")
            return render_template("integrations/taxdome_organizer_request.html", users=users, form_data=form_data)

        try:
            int(form_data["tax_year"])
        except ValueError:
            flash("Tax year must be a valid number.", "danger")
            return render_template("integrations/taxdome_organizer_request.html", users=users, form_data=form_data)

        assigned_user = None
        assigned_user_id = form_data.get("assigned_user_id")
        if assigned_user_id:
            assigned_user = db.session.get(User, int(assigned_user_id))

        try:
            result = apply_taxdome_organizer_request_event(form_data, assigned_user=assigned_user)
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return render_template("integrations/taxdome_organizer_request.html", users=users, form_data=form_data)

        messages = []
        messages.append("client created" if result["client_created"] else "client reused")
        messages.append("client work created" if result["client_work_created"] else "client work reused")
        messages.append(
            "default organizer requirements created"
            if result["requirements_created"]
            else "existing organizer requirements reused"
        )
        if result.get("expectation_source") == "prior_year" and result.get("prior_package"):
            messages.append(f"expectations seeded from {result['prior_package'].tax_year}")
        elif result.get("expectation_source") == "template":
            messages.append("template expectations used")
        flash(f"Simulated TaxDome organizer request processed: {', '.join(messages)}.", "success")
        return redirect(url_for("packages.detail", package_id=result["client_work"].id))

    return render_template("integrations/taxdome_organizer_request.html", users=users)


@integrations_bp.route("/taxdome/upload-document", methods=["GET", "POST"])
@login_required
def taxdome_upload_document():
    packages = (
        TaxReturn.query.join(TaxReturn.client)
        .filter(TaxReturn.source_system == "taxdome")
        .order_by(TaxReturn.tax_year.desc(), Client.display_name.asc())
        .all()
    )

    if request.method == "POST":
        form_data = request.form.to_dict()
        uploaded_file = request.files.get("document")
        package_id = form_data.get("package_id")
        client_display_name = form_data.get("client_display_name", "").strip()
        tax_year = form_data.get("tax_year", "").strip()
        taxdome_client_id = (form_data.get("taxdome_client_id") or "").strip() or None
        taxdome_job_id = (form_data.get("taxdome_job_id") or "").strip() or None

        if not uploaded_file or not uploaded_file.filename:
            flash("Please choose a file to simulate TaxDome document intake.", "danger")
            return render_template("integrations/taxdome_upload_document.html", packages=packages, form_data=form_data)

        if not allowed_file(uploaded_file.filename):
            flash("Unsupported file type. Please upload a PDF, PNG, JPG, or JPEG file.", "danger")
            return render_template("integrations/taxdome_upload_document.html", packages=packages, form_data=form_data)

        package = None
        if package_id:
            try:
                package = db.session.get(TaxReturn, int(package_id))
            except ValueError:
                package = None
        else:
            if not client_display_name or not tax_year:
                flash("Choose an Intake Package or provide client display name and tax year.", "danger")
                return render_template("integrations/taxdome_upload_document.html", packages=packages, form_data=form_data)
            try:
                tax_year_int = int(tax_year)
            except ValueError:
                flash("Tax year must be a valid number.", "danger")
                return render_template("integrations/taxdome_upload_document.html", packages=packages, form_data=form_data)

            client, _created = find_or_create_client(client_display_name, "individual", taxdome_client_id)
            package = (
                TaxReturn.query.filter_by(client_id=client.id, tax_year=tax_year_int)
                .order_by(TaxReturn.created_at.desc())
                .first()
            )

        if not package:
            flash("No matching TaxDome-created Client Work / Intake Package was found.", "danger")
            return render_template("integrations/taxdome_upload_document.html", packages=packages, form_data=form_data)

        stored_file_path = None
        try:
            destination, stored_file_path = get_upload_destination(
                package.client.display_name,
                package.tax_year,
                secure_filename(uploaded_file.filename),
            )
            uploaded_file.save(destination)
            filename_detected_type = detect_document_type_from_filename(uploaded_file.filename)
            logger.info(
                "TaxDome document classification filename_result file=%s detected_type=%s",
                uploaded_file.filename,
                filename_detected_type or "none",
            )
            detected_type = filename_detected_type
            document_type = detected_type or "source_document"
            classification_confidence = "high" if filename_detected_type else None
            classification_notes = (
                f"Filename rule matched '{filename_detected_type}'." if filename_detected_type else "Filename rules did not identify a supported type."
            )

            document = Document(
                tax_return=package,
                client=package.client,
                source="taxdome",
                source_system="taxdome",
                source_file_name=uploaded_file.filename,
                detected_document_type=detected_type,
                matching_method="filename_rule" if detected_type else "unmatched",
                classification_confidence=classification_confidence,
                classification_notes=classification_notes,
                file_name=destination.name,
                original_file_name=uploaded_file.filename,
                stored_file_path=stored_file_path,
                original_file_type=destination.suffix.lstrip(".").lower(),
                file_size_bytes=destination.stat().st_size,
                document_type=document_type,
                status="uploaded",
            )

            try:
                upload_result = sharepoint.upload_intake_document(
                    destination,
                    package.client.display_name,
                    package.tax_year,
                    destination.name,
                )
            except Exception as exc:
                upload_result = {"ok": False, "error": str(exc)}

            document.sharepoint_folder_path = upload_result.get("folder_path")
            if upload_result.get("ok"):
                document.sharepoint_file_url = upload_result.get("web_url")
                document.sharepoint_item_id = upload_result.get("item_id")
                document.sharepoint_drive_id = upload_result.get("drive_id")
                document.sharepoint_upload_status = "mock_uploaded" if upload_result.get("mode") == "mock" else "uploaded"
            else:
                document.sharepoint_upload_status = "failed"
                logger.warning("SharePoint upload failed for TaxDome simulation file %s: %s", destination.name, upload_result.get("error"))
                flash("Document saved locally, but SharePoint upload failed.", "warning")

            db.session.add(document)
            db.session.flush()
            if taxdome_job_id:
                package.taxdome_job_id = taxdome_job_id

            match_result = match_uploaded_document_to_requirement(package, document)
            logger.info(
                "TaxDome document matching initial_result document_id=%s matched=%s requirement_id=%s",
                document.id,
                match_result["matched"],
                match_result["requirement"].id if match_result["requirement"] else None,
            )
            if not match_result["matched"] and document.original_file_type == "pdf":
                logger.info("TaxDome document classification running_pdf_text_extraction document_id=%s", document.id)
                extracted_text, extraction_note = extract_pdf_text(destination)
                document.extracted_text = extracted_text or None
                logger.info(
                    "TaxDome document classification extracted_text_length document_id=%s length=%s note=%s",
                    document.id,
                    len(extracted_text or ""),
                    extraction_note or "none",
                )
                content_result = classify_document_text(extracted_text)
                logger.info(
                    "TaxDome document classification content_result document_id=%s detected_type=%s confidence=%s notes=%s",
                    document.id,
                    content_result["document_type"] or "none",
                    content_result["confidence"] or "none",
                    content_result["notes"],
                )
                if extraction_note:
                    document.classification_notes = f"{document.classification_notes} {extraction_note}".strip()
                if content_result["document_type"]:
                    document.document_type = content_result["document_type"]
                    document.detected_document_type = content_result["document_type"]
                    document.matching_method = "content_rule"
                    document.classification_confidence = content_result["confidence"]
                    document.classification_notes = f"{extraction_note or ''} {content_result['notes']}".strip()
                    match_result = match_uploaded_document_to_requirement(package, document)
                    logger.info(
                        "TaxDome document matching content_result document_id=%s matched=%s requirement_id=%s",
                        document.id,
                        match_result["matched"],
                        match_result["requirement"].id if match_result["requirement"] else None,
                    )
                elif not extraction_note:
                    document.classification_notes = content_result["notes"]
                else:
                    document.classification_notes = f"{extraction_note} {content_result['notes']}".strip()
            elif not match_result["matched"]:
                logger.info(
                    "TaxDome document classification skipped_content_fallback document_id=%s original_file_type=%s",
                    document.id,
                    document.original_file_type,
                )

            if match_result["matched"]:
                if document.matching_method not in {"content_rule", "filename_rule"}:
                    document.matching_method = "filename_rule" if filename_detected_type else "content_rule"
            else:
                document.matching_method = "unmatched"

            if match_result["matched"] and document.original_file_type == "pdf":
                normalized_document_type = canonical_structured_type(document.detected_document_type or document.document_type)
                if normalized_document_type in SUPPORTED_STRUCTURED_TYPES:
                    if not document.extracted_text:
                        logger.info(
                            "TaxDome structured extraction extracting_pdf_text document_id=%s document_type=%s",
                            document.id,
                            normalized_document_type,
                        )
                        extracted_text, extraction_note = extract_pdf_text(destination)
                        document.extracted_text = extracted_text or None
                        append_classification_note(document, extraction_note)
                        logger.info(
                            "TaxDome structured extraction extracted_text_length document_id=%s length=%s note=%s",
                            document.id,
                            len(extracted_text or ""),
                            extraction_note or "none",
                        )

                    if document.extracted_text:
                        structured_result = run_structured_extraction_for_document(document)
                        if structured_result:
                            logger.info(
                                "TaxDome structured extraction completed document_id=%s result_id=%s confidence=%s status=%s",
                                document.id,
                                structured_result.id,
                                structured_result.confidence_score,
                                structured_result.validation_status,
                            )
                    else:
                        logger.info(
                            "TaxDome structured extraction skipped_no_text document_id=%s document_type=%s",
                            document.id,
                            normalized_document_type,
                        )
                else:
                    logger.info(
                        "TaxDome structured extraction skipped_unsupported_type document_id=%s document_type=%s",
                        document.id,
                        normalized_document_type or "none",
                    )
            logger.info(
                "TaxDome document classification final_result document_id=%s detected_type=%s matching_method=%s confidence=%s matched=%s",
                document.id,
                document.detected_document_type or "none",
                document.matching_method or "none",
                document.classification_confidence or "none",
                match_result["matched"],
            )
            recalculate_package_readiness(package)
            db.session.commit()
        except Exception:
            db.session.rollback()
            if stored_file_path:
                saved_path = Path(current_app.config["UPLOAD_FOLDER"]) / stored_file_path
                if saved_path.exists():
                    saved_path.unlink()
            logger.exception("Failed to save simulated TaxDome document upload.")
            flash("The TaxDome document simulation could not be saved. Please try again.", "danger")
            return render_template("integrations/taxdome_upload_document.html", packages=packages, form_data=form_data)

        if match_result["matched"]:
            requirement_name = match_result["requirement"].name or match_result["requirement"].display_name
            match_source = "content-based detection" if document.matching_method == "content_rule" else "filename rule"
            flash(f"Document automatically matched to expected item: {requirement_name} ({match_source}).", "success")
        else:
            flash("Document uploaded but could not be automatically classified.", "info")
        return redirect(url_for("packages.detail", package_id=package.id))

    return render_template("integrations/taxdome_upload_document.html", packages=packages)
