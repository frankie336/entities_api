import hashlib
import hmac
import os
from datetime import datetime
from urllib.parse import urlencode

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from entities_api.dependencies import get_db
from entities_api.models.models import File
from entities_api.services.file_service import FileService
from entities_api.services.logging_service import LoggingUtility

# --- Initialization ---
router = APIRouter()
logging_utility = LoggingUtility()
load_dotenv()

# --- Signature Verification ---
def verify_signature(file_id: str, expires: int, signature: str, use_real_filename: bool = False) -> bool:
    secret_key = os.getenv("SIGNED_URL_SECRET", "default_secret_key")
    data = f"{file_id}:{expires}:{use_real_filename}"
    computed_signature = hmac.new(secret_key.encode(), data.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed_signature, signature)

# --- Download Endpoint ---

@router.get("/v1/files/download", response_class=StreamingResponse)
def download_file(
    file_id: str,
    expires: int,
    signature: str,
    use_real_filename: bool = Query(False),
    db: Session = Depends(get_db)
):
    if datetime.utcnow().timestamp() > expires:
        raise HTTPException(status_code=400, detail="Signed URL has expired")

    data = f"{file_id}:{expires}:{use_real_filename}"
    if not verify_signature(file_id, expires, signature, use_real_filename):
        raise HTTPException(status_code=403, detail="Invalid signature")

    file_service = FileService(db)
    file_stream, filename, mime_type = file_service.get_file_with_metadata(file_id)

    is_inline = mime_type.startswith(("image/", "text/")) or mime_type == "application/pdf"
    disposition_type = "inline" if is_inline else "attachment"

    headers = {
        "Content-Disposition": f'{disposition_type}; filename="{filename if use_real_filename else file_id}"',
        "X-Content-Type-Options": "nosniff"
    }

    return StreamingResponse(file_stream, media_type=mime_type, headers=headers)



# --- Signed URL Endpoint ---
@router.get("/v1/uploads/{file_id}/signed-url")
def generate_signed_url(
    file_id: str,
    expires_in: int = Query(600),
    use_real_filename: bool = Query(False),
    db: Session = Depends(get_db)
):
    logging_utility.info(f"Generating signed URL for file: {file_id} with TTL: {expires_in}s")

    file_record = db.query(File).filter(File.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    secret_key = os.getenv("SIGNED_URL_SECRET", "default_secret_key")
    base_url = os.getenv("BASE_URL", "http://localhost:9000")
    expires = int((datetime.utcnow().timestamp()) + expires_in)

    data = f"{file_id}:{expires}:{use_real_filename}"
    signature = hmac.new(secret_key.encode(), data.encode(), hashlib.sha256).hexdigest()

    query_params = {
        "file_id": file_id,
        "expires": expires,
        "signature": signature,
        "use_real_filename": str(use_real_filename).lower()
    }

    signed_url = f"{base_url}/v1/files/download?{urlencode(query_params)}"
    return {"signed_url": signed_url}



# --- Base64 Endpoint ---
@router.get("/v1/uploads/{file_id}/base64")
def get_file_as_base64(
    file_id: str,
    db: Session = Depends(get_db)
):
    """
    Returns a BASE64-encoded version of the file content.
    """
    logging_utility.info(f"Retrieving file as BASE64: {file_id}")
    file_service = FileService(db)

    try:
        base64_content = file_service.get_file_as_base64(file_id)
        logging_utility.info("BASE64 content generated successfully.")
        return {"file_id": file_id, "base64": base64_content}
    except Exception as e:
        logging_utility.error("Failed to return BASE64 content: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve BASE64 content")
