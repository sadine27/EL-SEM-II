"""Port of n8n node `Drive Upload (Scraped)`."""
from __future__ import annotations

import base64

from el import google_drive
from el.logger import get_logger

log = get_logger(__name__)


def _file_parts(file_item: dict) -> tuple[str, bytes, str]:
    json_part = file_item.get("json") or {}
    binary = ((file_item.get("binary") or {}).get("data") or {})
    filename = json_part.get("filename") or binary.get("fileName")
    encoded = binary.get("data")
    mime_type = binary.get("mimeType") or "application/octet-stream"
    if not filename:
        raise ValueError("scraped_json_file is missing filename")
    if not encoded:
        raise ValueError("scraped_json_file is missing binary.data.data")
    return filename, base64.b64decode(encoded), mime_type


def run(ctx: dict, provider: google_drive.DriveProvider | None = None) -> dict:
    file_item = ctx.get("scraped_json_file")
    if not file_item:
        ctx["scraped_drive_upload_result"] = {"ok": True, "uploaded": False}
        log.warning("Drive Upload (Scraped): no scraped_json_file to upload")
        return ctx

    folder_id = ctx.get("scraped_drive_folder_id") or google_drive.SCRAPED_FOLDER_ID
    try:
        filename, content, mime_type = _file_parts(file_item)
        p = provider or google_drive.default_provider()
        response = p.upload_file(filename, content, mime_type, folder_id=folder_id)
        ctx["scraped_drive_upload_result"] = {
            "ok": True,
            "uploaded": True,
            "filename": filename,
            "folder_id": folder_id,
            "response": response,
        }
        log.info("Drive Upload (Scraped): uploaded %s to folder %s", filename, folder_id)
    except Exception as exc:
        ctx["scraped_drive_upload_result"] = {
            "ok": False,
            "uploaded": False,
            "folder_id": folder_id,
            "error": str(exc),
        }
        log.warning("Drive Upload (Scraped) failed; continuing: %s", exc)
    return ctx
