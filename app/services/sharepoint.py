import logging
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import requests
from flask import current_app


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
logger = logging.getLogger(__name__)


class SharePointError(Exception):
    pass


def is_configured():
    required_values = (
        current_app.config.get("SHAREPOINT_TENANT_ID"),
        current_app.config.get("SHAREPOINT_CLIENT_ID"),
        current_app.config.get("SHAREPOINT_CLIENT_SECRET"),
        current_app.config.get("SHAREPOINT_SITE_ID"),
        current_app.config.get("SHAREPOINT_DRIVE_ID"),
    )
    return all(required_values)


def is_enabled():
    return current_app.config.get("SHAREPOINT_ENABLED", False)


def get_access_token():
    tenant_id = current_app.config.get("SHAREPOINT_TENANT_ID")
    client_id = current_app.config.get("SHAREPOINT_CLIENT_ID")
    client_secret = current_app.config.get("SHAREPOINT_CLIENT_SECRET")

    if not tenant_id or not client_id or not client_secret:
        raise SharePointError("SharePoint client credentials are not configured.")

    response = requests.post(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
        timeout=30,
    )
    if not response.ok:
        raise SharePointError(f"Token request failed: {response.status_code} {response.text}")

    token = response.json().get("access_token")
    if not token:
        raise SharePointError("Token response did not include an access token.")
    return token


def graph_headers(access_token):
    return {"Authorization": f"Bearer {access_token}"}


def normalize_graph_path(path):
    return str(PurePosixPath(str(path).replace("\\", "/"))).strip("/")


def graph_path_url(drive_id, folder_path):
    encoded_path = quote(normalize_graph_path(folder_path), safe="/")
    return f"{GRAPH_BASE_URL}/drives/{drive_id}/root:/{encoded_path}"


def ensure_folder_path_exists(folder_path):
    drive_id = current_app.config.get("SHAREPOINT_DRIVE_ID")
    if not is_configured():
        return {"ok": False, "error": "SharePoint is not configured."}

    access_token = get_access_token()
    headers = graph_headers(access_token)
    current_path = ""

    for part in normalize_graph_path(folder_path).split("/"):
        if not part:
            continue

        parent_path = current_path
        current_path = normalize_graph_path(PurePosixPath(current_path) / part)
        get_response = requests.get(graph_path_url(drive_id, current_path), headers=headers, timeout=30)
        if get_response.status_code == 200:
            continue
        if get_response.status_code != 404:
            return {"ok": False, "error": f"Folder lookup failed: {get_response.status_code} {get_response.text}"}

        if parent_path:
            create_url = f"{graph_path_url(drive_id, parent_path)}:/children"
        else:
            create_url = f"{GRAPH_BASE_URL}/drives/{drive_id}/root/children"

        create_response = requests.post(
            create_url,
            headers={**headers, "Content-Type": "application/json"},
            json={
                "name": part,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "replace",
            },
            timeout=30,
        )
        if create_response.status_code not in {200, 201}:
            return {"ok": False, "error": f"Folder creation failed: {create_response.status_code} {create_response.text}"}

    return {"ok": True}


def upload_file_to_sharepoint(local_file_path, destination_path, filename):
    local_path = Path(local_file_path)
    if not local_path.exists():
        return {"ok": False, "error": f"Local file not found: {local_path}"}

    if not is_enabled():
        logger.info("Using mock SharePoint mode for upload: %s", local_path)
        destination_file_path = normalize_graph_path(PurePosixPath(destination_path) / filename)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        return {
            "ok": True,
            "mode": "mock",
            "web_url": f"https://mock-sharepoint.local/{quote(destination_file_path, safe='/')}",
            "item_id": f"mock-item-{timestamp}",
            "drive_id": "mock-drive",
        }

    logger.info("Using real SharePoint mode for upload: %s", local_path)
    if not is_configured():
        return {"ok": False, "mode": "real", "error": "SharePoint is enabled but not fully configured."}

    folder_result = ensure_folder_path_exists(destination_path)
    if not folder_result.get("ok"):
        return folder_result

    access_token = get_access_token()
    drive_id = current_app.config["SHAREPOINT_DRIVE_ID"]
    destination_file_path = normalize_graph_path(PurePosixPath(destination_path) / filename)
    encoded_path = quote(destination_file_path, safe="/")
    upload_url = f"{GRAPH_BASE_URL}/drives/{drive_id}/root:/{encoded_path}:/content"

    with local_path.open("rb") as file_handle:
        response = requests.put(upload_url, headers=graph_headers(access_token), data=file_handle, timeout=120)

    if response.status_code not in {200, 201}:
        return {"ok": False, "mode": "real", "error": f"File upload failed: {response.status_code} {response.text}"}

    payload = response.json()
    logger.info("Real SharePoint upload succeeded: item_id=%s", payload.get("id"))
    return {
        "ok": True,
        "mode": "real",
        "web_url": payload.get("webUrl"),
        "item_id": payload.get("id"),
        "drive_id": payload.get("parentReference", {}).get("driveId", drive_id),
    }
