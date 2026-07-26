import json
from typing import Any

from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.services.masters import get_masters
from app.services.rate_limit import redis_client
from app.services.serialization import master_dict

MASTER_CACHE_KEY = "masters:public:v1"


def master_payload(db: Session) -> dict[str, list[dict[str, Any]]]:
    try:
        cached = redis_client().get(MASTER_CACHE_KEY)
        if cached:
            return json.loads(cached)
    except RedisError:
        pass

    values = get_masters(db)
    payload = {
        key: [
            master_dict(item) | ({"industry_id": item.industry_id} if hasattr(item, "industry_id") else {})
            for item in items
        ]
        for key, items in values.items()
    }
    try:
        redis_client().setex(MASTER_CACHE_KEY, 3600, json.dumps(payload, ensure_ascii=False))
    except RedisError:
        pass
    return payload


def invalidate_master_cache() -> None:
    try:
        redis_client().delete(MASTER_CACHE_KEY)
    except RedisError:
        pass
