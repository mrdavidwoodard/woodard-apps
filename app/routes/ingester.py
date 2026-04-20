import logging
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app import db
from app.models import Client, Document, TaxReturn
from app.services.package_readiness import (
    create_default_requirements,
    is_organizer_document,
    match_uploaded_document_to_requirement,
    recalculate_package_readiness,
)
from app.services import sharepoint

ingester_bp = Blueprint("ingester", __name__, url_prefix="/ingester")
logger = logging.getLogger(__name__)
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def slugify(value):
    return sharepoint.slugify_client_name(value)


def get_upload_destination(client_name, tax_year, original_filename):
    safe_filename = secure_filename(original_filename) or "uploaded-document"
    client_slug = slugify(client_name)
    relative_folder = Path(client_slug) / str(tax_year)
    absolute_folder = Path(current_app.config["UPLOAD_FOLDER"]) / relative_folder
    absolute_folder.mkdir(parents=True, exist_ok=True)

    destination = absolute_folder / safe_filename
    if destination.exists():
        stem = destination.stem
        suffix = destination.suffix
        counter = 1
        while destination.exists():
            destination = absolute_folder / f"{stem}-{counter}{suffix}"
            counter += 1

    relative_path = relative_folder / destination.name
    return destination, relative_path.as_posix()


@ingester_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        client_name = request.form.get("client_display_name", "").strip()
        client_type = request.form.get("client_type", "").strip()
        tax_year = request.form.get("tax_year", "").strip()
        work_type = request.form.get("work_type", request.form.get("return_type", "")).strip()
        document_type = request.form.get("document_type", "").strip()
        source = request.form.get("source", "").strip()
        uploaded_file = request.files.get("document")
        form_data = request.form.to_dict()

        required_values = [client_name, client_type, tax_year, work_type, document_type, source]
        if not all(required_values):
            flash("Client, intake package, and document details are required.", "danger")
            return render_template("ingester/upload.html", form_data=form_data)

        if not uploaded_file or not uploaded_file.filename:
            flash("Please choose a tax document to upload.", "danger")
            return render_template("ingester/upload.html", form_data=form_data)

        if not allowed_file(uploaded_file.filename):
            flash("Unsupported file type. Please upload a PDF, PNG, JPG, or JPEG file.", "danger")
            return render_template("ingester/upload.html", form_data=form_data)

        if is_organizer_document(document_type, uploaded_file.filename):
            document_type = "organizer"
            form_data["document_type"] = document_type

        try:
            tax_year_int = int(tax_year)
        except ValueError:
            flash("Tax year must be a valid number.", "danger")
            return render_template("ingester/upload.html", form_data=form_data)

        if tax_year_int < 1900 or tax_year_int > 2200:
            flash("Tax year must be between 1900 and 2200.", "danger")
            return render_template("ingester/upload.html", form_data=form_data)

        stored_file_path = None

        client = Client.query.filter(Client.display_name.ilike(client_name)).first()
        if not client:
            client = Client(display_name=client_name, client_type=client_type)
            db.session.add(client)
            db.session.flush()
        else:
            client.client_type = client_type

        tax_return = TaxReturn.query.filter_by(
            client=client,
            tax_year=tax_year_int,
            return_type=work_type,
        ).first()
        if not tax_return:
            tax_return = TaxReturn(
                client=client,
                tax_year=tax_year_int,
                return_type=work_type,
                work_type=work_type,
                status="new",
                assigned_user=current_user,
            )
            db.session.add(tax_return)
            db.session.flush()
            create_default_requirements(tax_return)
        elif not tax_return.work_type:
            tax_return.work_type = work_type
        try:
            destination, stored_file_path = get_upload_destination(client.display_name, tax_year_int, uploaded_file.filename)
            uploaded_file.save(destination)
            file_size_bytes = destination.stat().st_size
            file_extension = destination.suffix.lstrip(".").lower()

            db.session.flush()

            document = Document(
                tax_return=tax_return,
                client=client,
                source=source,
                file_name=destination.name,
                original_file_name=uploaded_file.filename,
                stored_file_path=stored_file_path,
                original_file_type=file_extension,
                file_size_bytes=file_size_bytes,
                document_type=document_type,
                status="uploaded",
                uploaded_by_user=current_user,
            )

            try:
                upload_result = sharepoint.upload_intake_document(destination, client.display_name, tax_year_int, destination.name)
            except Exception as exc:
                upload_result = {"ok": False, "error": str(exc)}

            document.sharepoint_folder_path = upload_result.get("folder_path")
            if upload_result.get("ok"):
                document.sharepoint_file_url = upload_result.get("web_url")
                document.sharepoint_item_id = upload_result.get("item_id")
                document.sharepoint_drive_id = upload_result.get("drive_id")
                document.sharepoint_upload_status = "mock_uploaded" if upload_result.get("mode") == "mock" else "uploaded"
                logger.info(
                    "SharePoint upload succeeded in %s mode for file %s at %s",
                    upload_result.get("mode"),
                    destination.name,
                    document.sharepoint_folder_path,
                )
            else:
                document.sharepoint_upload_status = "failed"
                logger.warning("SharePoint upload failed for %s: %s", document.sharepoint_folder_path, upload_result.get("error"))
                flash("Document saved locally, but SharePoint upload failed.", "warning")

            db.session.add(document)
            db.session.flush()
            match_result = match_uploaded_document_to_requirement(tax_return, document)
            recalculate_package_readiness(tax_return)
            db.session.commit()
        except Exception:
            db.session.rollback()
            if stored_file_path:
                saved_path = Path(current_app.config["UPLOAD_FOLDER"]) / stored_file_path
                if saved_path.exists():
                    saved_path.unlink()
            logger.exception("Failed to save ingester upload.")
            flash("The upload could not be saved. Please try again.", "danger")
            return render_template("ingester/upload.html", form_data=form_data)

        logger.info("Ingester upload saved: client_id=%s tax_return_id=%s document_id=%s", client.id, tax_return.id, document.id)
        if match_result["is_organizer"] and match_result["matched"]:
            flash("Organizer uploaded and matched to Intake Package.", "success")
        elif match_result["is_organizer"] and match_result["already_satisfied"]:
            flash("Organizer uploaded; requirement already satisfied.", "info")
        else:
            flash("Document uploaded and matched to Intake Package.", "success")
        return redirect(url_for("packages.detail", package_id=tax_return.id))

    return render_template("ingester/upload.html")
