from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crefito_review import CrefitoReview
from app.models.user import Professional


def current_review(db: Session, professional_id: str):
    return db.scalar(select(CrefitoReview).where(
        CrefitoReview.professional_id == professional_id, CrefitoReview.current.is_(True),
    ).with_for_update())


def lock_review(db: Session, review_id: str):
    professional_id = db.scalar(select(CrefitoReview.professional_id).where(
        CrefitoReview.id == review_id,
    ))
    if professional_id is None:
        return None, None
    professional = db.get(Professional, professional_id, with_for_update=True, populate_existing=True)
    if professional is None:
        return None, None
    return professional, current_review(db, professional.id)


def pending_reviews(db: Session, limit: int):
    return db.scalars(select(CrefitoReview.id).where(
        CrefitoReview.current.is_(True), CrefitoReview.result.is_(None),
    ).order_by(CrefitoReview.created_at, CrefitoReview.id).limit(limit)).all()
