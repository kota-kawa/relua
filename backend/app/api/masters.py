from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import MastersResponse
from app.services.master_cache import master_payload

router = APIRouter(tags=["masters"])


@router.get("/masters", response_model=MastersResponse)
def masters(db: Annotated[Session, Depends(get_db)]) -> dict[str, list[object]]:
    return master_payload(db)
