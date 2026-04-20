from datetime import datetime

from app import db
from app.models import Client, TaxReturn
from app.services.package_readiness import initialize_requirements_for_package, recalculate_package_readiness


def parse_due_date(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def find_or_create_client(display_name, client_type, taxdome_client_id=None):
    created = False
    client = None

    if taxdome_client_id:
        client = Client.query.filter_by(taxdome_client_id=taxdome_client_id).first()

    if not client:
        client = Client.query.filter(Client.display_name.ilike(display_name)).first()

    if not client:
        client = Client(
            display_name=display_name,
            client_type=client_type,
            taxdome_client_id=taxdome_client_id or None,
        )
        db.session.add(client)
        db.session.flush()
        created = True
    else:
        client.display_name = display_name or client.display_name
        client.client_type = client_type or client.client_type
        if taxdome_client_id and not client.taxdome_client_id:
            client.taxdome_client_id = taxdome_client_id

    return client, created


def find_or_create_client_work(client, tax_year, work_type, assigned_user=None):
    created = False
    client_work = (
        TaxReturn.query.filter_by(client_id=client.id, tax_year=tax_year)
        .order_by(TaxReturn.created_at.asc())
        .first()
    )

    if not client_work:
        client_work = TaxReturn(
            client=client,
            tax_year=tax_year,
            return_type=work_type,
            work_type=work_type,
            status="waiting_on_client",
            source_system="taxdome",
            assigned_user=assigned_user,
        )
        db.session.add(client_work)
        db.session.flush()
        created = True
    elif assigned_user and not client_work.assigned_user:
        client_work.assigned_user = assigned_user
    if work_type:
        client_work.package_type = work_type

    return client_work, created


def apply_taxdome_organizer_request_event(event_data, assigned_user=None):
    """Simulate a TaxDome organizer request event and create/reuse internal workflow records."""
    client_display_name = event_data["client_display_name"].strip()
    client_type = event_data.get("client_type", "individual").strip() or "individual"
    tax_year = int(event_data["tax_year"])
    work_type = (event_data.get("work_type") or "").strip()
    taxdome_client_id = (event_data.get("taxdome_client_id") or "").strip() or None
    taxdome_job_id = (event_data.get("taxdome_job_id") or "").strip() or None
    organizer_request_id = (event_data.get("taxdome_organizer_request_id") or "").strip() or None
    due_date = parse_due_date((event_data.get("due_date") or "").strip())

    client, client_created = find_or_create_client(client_display_name, client_type, taxdome_client_id)
    client_work, client_work_created = find_or_create_client_work(client, tax_year, work_type, assigned_user)
    existing_requirement_count = client_work.package_document_requirements.count()

    client_work.source_system = "taxdome"
    client_work.taxdome_job_id = taxdome_job_id or client_work.taxdome_job_id
    client_work.taxdome_organizer_request_id = organizer_request_id or client_work.taxdome_organizer_request_id
    client_work.due_date = due_date or client_work.due_date
    if client_work_created or client_work.status == "new":
        client_work.status = "waiting_on_client"

    initialization = initialize_requirements_for_package(client_work)

    recalculate_package_readiness(client_work)

    return {
        "client": client,
        "client_work": client_work,
        "client_created": client_created,
        "client_work_created": client_work_created,
        "requirements_created": existing_requirement_count == 0,
        "expectation_source": initialization["source"],
        "prior_package": initialization["prior_package"],
    }
