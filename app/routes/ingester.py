import logging
import re
from pathlib import Path

from flask import Blueprint, current_app, flash, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app import db
from app.models import Client, Document, TaxReturn
from app.services import sharepoint

ingester_bp = Blueprint("ingester", __name__, url_prefix="/ingester")
logger = logging.getLogger(__name__)
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def slugify(value):
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return slug.strip("-") or "client"


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


def build_sharepoint_folder_path(client_name, tax_year):
    base_folder = current_app.config.get("SHAREPOINT_BASE_FOLDER") or ""
    client_slug = slugify(client_name)
    return str(Path(base_folder) / client_slug / str(tax_year)).replace("\\", "/").strip("/")


@ingester_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        client_name = request.form.get("client_display_name", "").strip()
        client_type = request.form.get("client_type", "").strip()
        tax_year = request.form.get("tax_year", "").strip()
        return_type = request.form.get("return_type", "").strip()
        document_type = request.form.get("document_type", "").strip()
        source = request.form.get("source", "").strip()
        uploaded_file = request.files.get("document")
        form_data = request.form.to_dict()

        required_values = [client_name, client_type, tax_year, return_type, document_type, source]
        if not all(required_values):
            flash("Client, return, and document details are required.", "danger")
            return render_template("ingester/upload.html", form_data=form_data)

        if not uploaded_file or not uploaded_file.filename:
            flash("Please choose a tax document to upload.", "danger")
            return render_template("ingester/upload.html", form_data=form_data)

        if not allowed_file(uploaded_file.filename):
            flash("Unsupported file type. Please upload a PDF, PNG, JPG, or JPEG file.", "danger")
            return render_template("ingester/upload.html", form_data=form_data)

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

        tax_return = TaxReturn(
            client=client,
            tax_year=tax_year_int,
            return_type=return_type,
            status="new",
            assigned_user=current_user,
        )
        try:
            destination, stored_file_path = get_upload_destination(client.display_name, tax_year_int, uploaded_file.filename)
            uploaded_file.save(destination)
            file_size_bytes = destination.stat().st_size
            file_extension = destination.suffix.lstrip(".").lower()

            db.session.add(tax_return)
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

            if sharepoint.is_configured():
                folder_path = build_sharepoint_folder_path(client.display_name, tax_year_int)
                try:
                    upload_result = sharepoint.upload_file_to_sharepoint(destination, folder_path, destination.name)
                except Exception as exc:
                    upload_result = {"ok": False, "error": str(exc)}

                if upload_result.get("ok"):
                    document.sharepoint_file_url = upload_result.get("web_url")
                    document.sharepoint_item_id = upload_result.get("item_id")
                    document.sharepoint_drive_id = upload_result.get("drive_id")
                    document.sharepoint_upload_status = "uploaded"
                else:
                    document.sharepoint_upload_status = "failed"
                    logger.warning("SharePoint upload failed: %s", upload_result.get("error"))
                    flash("Document saved locally, but SharePoint upload failed.", "warning")

            db.session.add(document)
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
        flash("Document uploaded and intake record created.", "success")
        return render_template(
            "ingester/upload.html",
            detail_url=url_for("returns.returns_detail", tax_return_id=tax_return.id),
        )

    return render_template("ingester/upload.html")
