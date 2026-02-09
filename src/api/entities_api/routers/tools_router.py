from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

# --- Core Dependencies ---
from src.api.entities_api.dependencies import get_api_key, get_db, get_web_reader
from src.api.entities_api.models.models import ApiKey as ApiKeyModel
from src.api.entities_api.models.models import User as UserModel
from src.api.entities_api.services.logging_service import LoggingUtility
from src.api.entities_api.services.web_reader import UniversalWebReader

# --- Router Setup ---
# We group these under "Tools"
router = APIRouter()
logging_utility = LoggingUtility()


# --- Request Models ---
class WebReadRequest(BaseModel):
    url: str
    force_refresh: bool = False


class WebScrollRequest(BaseModel):
    url: str
    page: int


# ✅ ADDED: The missing Pydantic model for search
class WebSearchRequest(BaseModel):
    url: str
    query: str


# --- Helper for Code Reuse (Optional, but keeps routes clean) ---
def verify_admin_privileges(db: Session, auth_key: ApiKeyModel) -> UserModel:
    """
    Helper to enforce Admin-only access, mimicking the logic in users_router.
    """
    requesting_admin = (
        db.query(UserModel).filter(UserModel.id == auth_key.user_id).first()
    )
    if not requesting_admin or not requesting_admin.is_admin:
        logging_utility.warning(
            f"Unauthorized web access attempt by user ID: {auth_key.user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required to use Web Tools.",
        )
    return requesting_admin


# --- Routes ---


@router.post("/tools/web/read", summary="Read a URL (Page 0)")
async def read_url(
    payload: WebReadRequest,
    reader: UniversalWebReader = Depends(get_web_reader),
    db: Session = Depends(get_db),  # Needed for Admin Check
    auth_key: ApiKeyModel = Depends(get_api_key),  # Needed for Identity
):
    """
    **Agent Action:** Read a new URL.
    **Security:** Admin Only.
    """
    # 1. Admin Security Check
    admin_user = verify_admin_privileges(db, auth_key)

    logging_utility.info(
        f"Admin '{admin_user.email}' requesting to read URL: {payload.url}"
    )

    # 2. Execute Logic
    try:
        # Pass the force_refresh flag to the service
        result = await reader.read(payload.url, force_refresh=payload.force_refresh)
        return {"content": result}
    except Exception as e:
        logging_utility.error(f"Web read failed for {payload.url}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Web browsing failed: {str(e)}")


@router.post("/tools/web/scroll", summary="Scroll to a specific page")
async def scroll_url(
    payload: WebScrollRequest,
    reader: UniversalWebReader = Depends(get_web_reader),
    db: Session = Depends(get_db),  # Needed for Admin Check
    auth_key: ApiKeyModel = Depends(get_api_key),  # Needed for Identity
):
    """
    **Agent Action:** Scroll an existing URL.
    **Security:** Admin Only.
    """
    # 1. Admin Security Check
    admin_user = verify_admin_privileges(db, auth_key)

    logging_utility.info(
        f"Admin '{admin_user.email}' requesting scroll on URL: {payload.url} (Page {payload.page})"
    )

    # 2. Execute Logic
    try:
        result = await reader.scroll(payload.url, payload.page)
        return {"content": result}
    except Exception as e:
        logging_utility.error(f"Web scroll failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Scrolling failed: {str(e)}")


@router.post("/tools/web/search", summary="Search text inside a loaded URL")
async def search_url(
    payload: WebSearchRequest,
    reader: UniversalWebReader = Depends(get_web_reader),
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    """
    **Agent Action:** Search for a specific term across ALL pages of a URL.
    **Benefit:** Saves context window by not reading every page manually.
    """
    verify_admin_privileges(db, auth_key)  # Same auth as before

    try:
        result = await reader.search(payload.url, payload.query)
        return {"content": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
