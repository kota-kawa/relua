from fastapi import APIRouter

from app.db import DbSession
from app.schemas import MastersResponse
from app.services.master_cache import master_payload

router = APIRouter(tags=["masters"])


@router.get("/masters", response_model=MastersResponse)
def masters(db: DbSession) -> dict[str, list[object]]:
    return master_payload(db)
