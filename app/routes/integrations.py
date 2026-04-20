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
    detect_document_type_from_filename,
    match_uploaded_document_to_requirement,
    recalculate_package_readiness,
)
from app.services.taxdome import apply_taxdome_organizer_request_event, find_or_create_client

integrations_bp = Blueprint("integrations", __name__, url_prefix="/integrations")
logger = logging.getLogger(__name__)


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
            detected_type = detect_document_type_from_filename(uploaded_file.filename)
            document_type = detected_type or "source_document"

            document = Document(
                tax_return=package,
                client=package.client,
                source="taxdome",
                source_system="taxdome",
                source_file_name=uploaded_file.filename,
                detected_document_type=detected_type,
                matching_method="filename_rule" if detected_type else "unmatched",
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
            document.matching_method = "filename_rule" if match_result["matched"] and detected_type else "unmatched"
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
            flash(f"Document automatically matched to expected item: {requirement_name}.", "success")
        else:
            flash("Document uploaded but could not be automatically matched.", "info")
        return redirect(url_for("packages.detail", package_id=package.id))

    return render_template("integrations/taxdome_upload_document.html", packages=packages)
