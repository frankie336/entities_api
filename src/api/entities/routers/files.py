import hashlib
import hmac
import os
from datetime import datetime

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query, Depends, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from entities.dependencies import get_db
from entities.services.file_service import FileService
from entities.services.logging_service import LoggingUtility

router = APIRouter()
logging_utility = LoggingUtility()
load_dotenv()


def verify_signature(file_id: str, expires: int, signature: str) -> bool:
    secret_key = os.getenv("SIGNED_URL_SECRET", "k-WBnsS54HZrM8ZVzYiQ-MLPOV53TuuhzEJOdG8kHcM")
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

    # Expiry check
    if datetime.utcnow().timestamp() > expires:
        logging_utility.error("Signed URL has expired")
        raise HTTPException(status_code=400, detail="Signed URL has expired")

    # Signature verification
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

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"'
    }

    return StreamingResponse(file_stream, media_type=mime_type, headers=headers)
