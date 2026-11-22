from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.crefito_review import CrefitoResult, CrefitoReview
from app.models.user import Professional
from app.repositories import crefito_reviews

PUBLIC_REGISTRIES = {3: "https://www.crefito3.org.br/dsn/consultapf/buscas.html"}


def clear_verification(professional: Professional):
    professional.verification_status = "unverified"
    professional.verified_at = None
    professional.verification_reference = None


def request_review(db: Session, professional: Professional):
    if professional.crefito_number is None:
        return
    review = CrefitoReview(professional_id=professional.id)
    if professional.crefito_region not in PUBLIC_REGISTRIES:
        review.result = CrefitoResult.NEEDS_REVIEW
        review.reason = "region_not_covered"
        review.reviewed_at = datetime.now(UTC)
    db.add(review)


def replace_review(db: Session, professional: Professional):
    previous = crefito_reviews.current_review(db, professional.id)
    if previous is not None:
        previous.current = False
    request_review(db, professional)


def pending_review(db: Session, review_id: str):
    professional, review = crefito_reviews.lock_review(db, review_id)
    if review is None or review.id != review_id or review.result is not None:
        raise ValueError("Review is unavailable or already processed")
    return professional, review


def record_result(db: Session, review_id: str, result: CrefitoResult, reviewer_id: str):
    professional, review = pending_review(db, review_id)
    review.result = result
    review.reason = result.value
    review.source = f"crefito-{professional.crefito_region}"
    review.reviewer_id = reviewer_id
    review.reviewed_at = datetime.now(UTC)
    if result == CrefitoResult.CANCELLED:
        review.authorization_withdrawn = professional.verification_status == "verified"
        clear_verification(professional)
    db.commit()
