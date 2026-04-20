import logging
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app import db
from app.models import Client, Document, TaxReturn
from app.services.package_readiness import (
    initialize_requirements_for_package,
    is_organizer_document,
    match_uploaded_document_to_requirement,
    recalculate_package_readiness,
    requirement_display_name,
)
from app.services import sharepoint

ingester_bp = Blueprint("ingester", __name__, url_prefix="/ingester")
logger = logging.getLogger(__name__)
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}

OTHER_DOCUMENT_TYPE_OPTIONS = [
    ("organizer", "Organizer"),
    ("w2", "W-2"),
    ("1099_int", "1099-INT"),
    ("1099_div", "1099-DIV"),
    ("1099_b", "1099-B"),
    ("1099_nec", "1099-NEC"),
    ("1098", "1098 Mortgage Interest"),
    ("k1", "K-1"),
    ("source_document", "Source Document"),
    ("other", "Other / Unmatched"),
]


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


def build_package_upload_context(package):
    if not package:
        return None

    section_summaries = []
    missing_items = []
    received_items = []

    for requirement in package.package_document_requirements.all():
        if not requirement.section:
            continue
        item = {
            "id": requirement.id,
            "document_type": requirement.document_type,
            "label": requirement.name or requirement.display_name or requirement_display_name(requirement.document_type),
            "section": requirement.section.name,
            "is_received": requirement.is_received,
            "is_required": requirement.is_required,
            "is_expected_this_year": requirement.is_expected_this_year,
        }
        if requirement.is_expected_this_year and requirement.is_required and not requirement.is_received:
            missing_items.append(item)
        elif requirement.is_expected_this_year and requirement.is_received:
            received_items.append(item)

    sections_by_id = {
        requirement.section.id: requirement.section
        for requirement in package.package_document_requirements.all()
        if requirement.section
    }
    for section in sorted(
        sections_by_id.values(),
        key=lambda section: (section.display_order, section.name),
    ):
        requirements = [
            requirement
            for requirement in package.package_document_requirements.filter_by(section_id=section.id).all()
            if requirement.is_expected_this_year
        ]
        if requirements:
            section_summaries.append({"section": section, "requirements": requirements})

    missing_types = {item["document_type"] for item in missing_items}
    other_options = [
        {"value": value, "label": label}
        for value, label in OTHER_DOCUMENT_TYPE_OPTIONS
        if value not in missing_types
    ]

    return {
        "package": package,
        "missing_items": missing_items,
        "received_items": received_items,
        "section_summaries": section_summaries,
        "missing_type_options": [
            {"value": item["document_type"], "label": item["label"], "section": item["section"]}
            for item in missing_items
        ],
        "other_type_options": other_options,
    }


def render_upload_form(form_data=None, package=None):
    return render_template(
        "ingester/upload.html",
        form_data=form_data,
        upload_context=build_package_upload_context(package),
        other_document_type_options=[
            {"value": value, "label": label}
            for value, label in OTHER_DOCUMENT_TYPE_OPTIONS
        ],
    )


@ingester_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    package_id = request.values.get("package_id")
    package_context = None
    if package_id:
        try:
            package_context = db.session.get(TaxReturn, int(package_id))
        except ValueError:
            package_context = None

    if request.method == "POST":
        client_name = request.form.get("client_display_name", "").strip()
        client_type = request.form.get("client_type", "").strip()
        tax_year = request.form.get("tax_year", "").strip()
        work_type = request.form.get("work_type", request.form.get("return_type", "")).strip()
        document_type = request.form.get("document_type", "").strip()
        source = request.form.get("source", "").strip()
        uploaded_file = request.files.get("document")
        form_data = request.form.to_dict()

        if package_context:
            client_name = package_context.client.display_name
            client_type = package_context.client.client_type
            tax_year = str(package_context.tax_year)
            work_type = package_context.work_type or package_context.return_type
            form_data.update(
                {
                    "package_id": str(package_context.id),
                    "client_display_name": client_name,
                    "client_type": client_type,
                    "tax_year": tax_year,
                    "work_type": work_type,
                }
            )

        required_values = [client_name, client_type, tax_year, work_type, document_type, source]
        if not all(required_values):
            flash("Client, intake package, and document details are required.", "danger")
            return render_upload_form(form_data=form_data, package=package_context)

        if not uploaded_file or not uploaded_file.filename:
            flash("Please choose a tax document to upload.", "danger")
            return render_upload_form(form_data=form_data, package=package_context)

        if not allowed_file(uploaded_file.filename):
            flash("Unsupported file type. Please upload a PDF, PNG, JPG, or JPEG file.", "danger")
            return render_upload_form(form_data=form_data, package=package_context)

        if is_organizer_document(document_type, uploaded_file.filename):
            document_type = "organizer"
            form_data["document_type"] = document_type

        try:
            tax_year_int = int(tax_year)
        except ValueError:
            flash("Tax year must be a valid number.", "danger")
            return render_upload_form(form_data=form_data, package=package_context)

        if tax_year_int < 1900 or tax_year_int > 2200:
            flash("Tax year must be between 1900 and 2200.", "danger")
            return render_upload_form(form_data=form_data, package=package_context)

        stored_file_path = None

        if package_context:
            tax_return = package_context
            client = tax_return.client
        else:
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
                initialize_requirements_for_package(tax_return)
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
                source_system="internal",
                source_file_name=uploaded_file.filename,
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
            return render_upload_form(form_data=form_data, package=package_context)

        logger.info("Ingester upload saved: client_id=%s tax_return_id=%s document_id=%s", client.id, tax_return.id, document.id)
        if match_result["is_organizer"] and match_result["matched"]:
            flash("Organizer uploaded and matched to Intake Package.", "success")
        elif match_result["is_organizer"] and match_result["already_satisfied"]:
            flash("Organizer uploaded; requirement already satisfied.", "info")
        elif match_result["matched"]:
            requirement_name = match_result["requirement"].name or match_result["requirement"].display_name
            flash(f"Document uploaded and matched to expected item: {requirement_name}.", "success")
        else:
            flash("Document uploaded but no expected item match was found.", "info")
        return redirect(url_for("packages.detail", package_id=tax_return.id))

    if package_context:
        form_data = {
            "package_id": package_context.id,
            "client_display_name": package_context.client.display_name,
            "client_type": package_context.client.client_type,
            "tax_year": package_context.tax_year,
            "work_type": package_context.work_type or package_context.return_type,
            "source": "manual_upload",
            "document_type": "",
        }
        return render_upload_form(form_data=form_data, package=package_context)

    return render_upload_form()
