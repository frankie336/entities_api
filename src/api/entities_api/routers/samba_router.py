import hashlib
import hmac
import os
from datetime import datetime

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Response,
                     UploadFile)
from projectdavid_common import ValidationInterface
from sqlalchemy.orm import Session

from entities_api.dependencies import get_api_key, get_db
from entities_api.models.models import ApiKey as ApiKeyModel
from entities_api.services.file_service import FileService
from entities_api.services.logging_service import LoggingUtility

router = APIRouter()
logging_utility = LoggingUtility()


@router.post(
    "/uploads", response_model=ValidationInterface.FileResponse, status_code=201
)
def upload_file(
    file: UploadFile = File(...),
    purpose: str = Form(...),
    user_id: str = Form(...),
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(f"[{auth_key.user_id}] Uploading file: {file.filename}")
    request = ValidationInterface.FileUploadRequest(purpose=purpose, user_id=user_id)
    file_service = FileService(db)
    file_metadata = file_service.upload_file(file, request)
    return ValidationInterface.FileResponse.model_validate(file_metadata)


@router.get("/uploads/{file_id}", response_model=ValidationInterface.FileResponse)
def get_file_by_id(
    file_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        f"[{auth_key.user_id}] Retrieving file metadata for ID: {file_id}"
    )
    file_service = FileService(db)
    file_metadata = file_service.get_file_by_id(file_id)
    if not file_metadata:
        raise HTTPException(status_code=404, detail=f"File with ID {file_id} not found")
    return ValidationInterface.FileResponse.model_validate(file_metadata)


@router.get("/uploads/{file_id}/object", response_class=Response)
def download_file_as_object(
    file_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    file_service = FileService(db)
    file_obj = file_service.get_file_as_object(file_id)
    return Response(content=file_obj.read(), media_type="application/octet-stream")


@router.get("/uploads/{file_id}/signed-url", response_model=dict)
def get_signed_url(
    file_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    file_service = FileService(db)
    signed_url = file_service.get_file_as_signed_url(file_id)
    return {"signed_url": signed_url}


@router.get("/uploads/{file_id}/base64", response_model=dict)
def get_file_as_base64(
    file_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    file_service = FileService(db)
    b64_str = file_service.get_file_as_base64(file_id)
    return {"base64": b64_str}


@router.delete("/uploads/{file_id}", response_model=dict)
def delete_file(
    file_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    file_service = FileService(db)
    success = file_service.delete_file_by_id(file_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"File with ID {file_id} not found")
    return {"deleted": True}


@router.get("/files/download", response_class=Response)
def download_file_via_signed_url(
    file_id: str,
    expires: int,
    signature: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    try:
        secret_key = os.getenv("SIGNED_URL_SECRET", "default_secret_key")
        data = f"{file_id}:{expires}"
        expected_signature = hmac.new(
            key=secret_key.encode(), msg=data.encode(), digestmod=hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected_signature):
            raise HTTPException(status_code=403, detail="Invalid signature")

        if int(datetime.utcnow().timestamp()) > expires:
            raise HTTPException(status_code=410, detail="URL has expired")

        file_service = FileService(db)
        file_obj = file_service.get_file_as_object(file_id)
        return Response(
            content=file_obj.read(),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={file_id}"},
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        logging_utility.error(f"[{auth_key.user_id}] Download error: {str(e)}")
        raise HTTPException(status_code=500, detail="File download failed")
