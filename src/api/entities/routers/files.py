import base64
import hashlib
import hmac
import os
from datetime import datetime
from urllib.parse import urlencode

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from entities.dependencies import get_db
from entities.models.models import File
from entities.services.file_service import FileService
from entities.services.logging_service import LoggingUtility

# --- Initialization ---
router = APIRouter()
logging_utility = LoggingUtility()
load_dotenv()

# --- Signature Verification ---
def verify_signature(file_id: str, expires: int, signature: str) -> bool:
    secret_key = os.getenv("SIGNED_URL_SECRET", "default_secret_key")
    data = f"{file_id}:{expires}"
    computed_signature = hmac.new(secret_key.encode(), data.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed_signature, signature)

# --- Download Endpoint ---
from mimetypes import guess_extension

from mimetypes import guess_extension

@router.get("/v1/files/download", response_class=StreamingResponse)
def download_file(
    file_id: str = Query(..., description="Unique file ID"),
    expires: int = Query(..., description="UNIX timestamp for expiration"),
    signature: str = Query(..., description="HMAC SHA-256 signature"),
    db: Session = Depends(get_db)
):
    logging_utility.info(f"Received request to download file with ID: {file_id}")

    if datetime.utcnow().timestamp() > expires:
        logging_utility.error("Signed URL has expired")
        raise HTTPException(status_code=400, detail="Signed URL has expired")

    if not verify_signature(file_id, expires, signature):
        logging_utility.error("Invalid signature for file download request")
        raise HTTPException(status_code=403, detail="Invalid signature")

    file_service = FileService(db)

    try:
        file_stream, filename, mime_type = file_service.get_file_with_metadata(file_id)
        logging_utility.info(f"File retrieved successfully for file ID: {file_id}")
    except Exception as e:
        logging_utility.error(f"Error retrieving file object for file ID {file_id}: {str(e)}")
        raise HTTPException(status_code=404, detail=f"File not found: {str(e)}")

    # Ensure filename has proper extension
    if '.' not in filename:
        ext = guess_extension(mime_type)
        if ext:
            filename += ext

    is_inline = mime_type.startswith("image/") or mime_type.startswith("text/") or mime_type == "application/pdf"
    disposition_type = "inline" if is_inline else "attachment"

    headers = {
        "Content-Disposition": f'{disposition_type}; filename="{filename}"',
        "X-Content-Type-Options": "nosniff"
    }

    return StreamingResponse(file_stream, media_type=mime_type, headers=headers)

# --- Signed URL Endpoint ---
@router.get("/v1/uploads/{file_id}/signed-url")
def generate_signed_url(
    file_id: str,
    expires_in: int = Query(600, description="Validity of the signed URL in seconds (default: 600)"),
    db: Session = Depends(get_db)
):
    """
    Returns a signed download URL for the given file ID.
    """
    logging_utility.info(f"Generating signed URL for file: {file_id} with TTL: {expires_in}s")

    file_service = FileService(db)
    file_record = db.query(File).filter(File.id == file_id).first()

    if not file_record:
        logging_utility.error("File not found for signed URL request")
        raise HTTPException(status_code=404, detail="File not found")

    try:
        secret_key = os.getenv("SIGNED_URL_SECRET", "default_secret_key")
        base_url = os.getenv("BASE_URL", "http://localhost:9000")

        expires = int((datetime.utcnow().timestamp()) + expires_in)
        data = f"{file_id}:{expires}"
        signature = hmac.new(secret_key.encode(), data.encode(), hashlib.sha256).hexdigest()

        query = urlencode({
            "file_id": file_id,
            "expires": expires,
            "signature": signature
        })

        signed_url = f"{base_url}/v1/files/download?{query}"
        logging_utility.info("Signed URL generated successfully for file_id: %s", file_id)

        return {"signed_url": signed_url}

    except Exception as e:
        logging_utility.error("Failed to generate signed URL: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to generate signed URL")

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
