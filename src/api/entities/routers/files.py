from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
import os
import hmac
import hashlib
from datetime import datetime
from sqlalchemy.orm import Session

from entities.dependencies import get_db
from entities.services.file_service import FileService
from entities.services.logging_service import LoggingUtility

router = APIRouter()
logging_utility = LoggingUtility()


def verify_signature(file_id: str, expires: int, signature: str) -> bool:
    secret_key = os.getenv("SIGNED_URL_SECRET", "default_secret_key")
    data = f"{file_id}:{expires}"
    computed_signature = hmac.new(secret_key.encode(), data.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed_signature, signature)


@router.get("/v1/files/download", response_class=StreamingResponse)
def download_file(
        file_id: str = Query(...),
        expires: int = Query(...),
        signature: str = Query(...),
        db: Session = Depends(get_db)
):
    logging_utility.info(f"Received request to download file with ID: {file_id}")

    # Check URL expiry
    if datetime.utcnow().timestamp() > expires:
        logging_utility.error("Signed URL has expired")
        raise HTTPException(status_code=400, detail="Signed URL has expired")

    # Verify the signature
    if not verify_signature(file_id, expires, signature):
        logging_utility.error("Invalid signature for file download request")
        raise HTTPException(status_code=403, detail="Invalid signature")

    # Retrieve file using FileService
    file_service = FileService(db)
    try:
        file_obj = file_service.get_file_as_object(file_id)
        logging_utility.info(f"File retrieved successfully for file ID: {file_id}")
    except Exception as e:
        logging_utility.error(f"Error retrieving file object for file ID {file_id}: {str(e)}")
        raise HTTPException(status_code=404, detail=f"File not found: {str(e)}")

    # Set default MIME type and headers
    mime_type = "application/octet-stream"
    headers = {"Content-Disposition": f"attachment; filename={file_id}"}

    return StreamingResponse(file_obj, media_type=mime_type, headers=headers)
