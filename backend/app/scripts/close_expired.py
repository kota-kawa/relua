from sqlalchemy import select, update

from app.dates import today_in_tokyo
from app.db import SessionLocal
from app.models import Opportunity, RecruitmentStatus


def run() -> int:
    with SessionLocal() as db:
        closed_id = db.scalar(select(RecruitmentStatus.id).where(RecruitmentStatus.name == "締切"))
        if closed_id is None:
            raise RuntimeError("募集状況マスタ「締切」がありません")
        result = db.execute(
            update(Opportunity)
            .where(
                Opportunity.deadline < today_in_tokyo(),
                Opportunity.status_id != closed_id,
                Opportunity.deleted_at.is_(None),
            )
            .values(status_id=closed_id)
        )
        db.commit()
        return int(result.rowcount or 0)


if __name__ == "__main__":
    print(f"updated={run()}")
