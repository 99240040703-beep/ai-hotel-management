from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

try:
    from database import get_db
    from middleware.auth import require_current_user, require_admin
except (ImportError, ValueError):
    from ..database import get_db
    from ..middleware.auth import require_current_user, require_admin
from services import event_service
from models import Review
from schemas import ReviewCreate
from ml.sentiment import analyze_sentiment, summarize_reviews

router = APIRouter(
    prefix="/reviews",
    tags=["Reviews & Feedback"],
)


# Reviews are shown on the public menu, so reading stays open.
@router.get("/")
def read_reviews(db: Session = Depends(get_db)):
    return db.query(Review).order_by(Review.id.desc()).all()


@router.post("/")
def add_review(
    item: ReviewCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    """
    Every new review is classified by the NLP model on the way in.

    The reviewer is taken from the session, so a guest cannot post a
    review under someone else's name.
    """
    result = analyze_sentiment(item.comment)

    review = Review(
        customer_name=current_user["user_name"],
        menu_item=item.menu_item,
        rating=item.rating,
        comment=item.comment,
        sentiment=result["sentiment"],
        sentiment_score=result["score"],
        user_id=current_user["user_id"],
    )

    db.add(review)
    db.commit()
    db.refresh(review)

    # Phase 6C. The review row itself carries sentiment and created_at, so
    # this event adds no new fact about the review - it puts feedback into
    # the same log as orders and stock, which is what lets a single
    # question span both.
    event_service.record_event(
        db,
        event_service.REVIEW_CREATED,
        event_service.ENTITY_REVIEW,
        entity_id=review.id,
        actor_user_id=current_user["user_id"],
        metadata={
            "menu_item": review.menu_item,
            "rating": review.rating,
            "sentiment": review.sentiment,
        },
    )

    try:
        db.commit()
        # A commit expires the instance; FastAPI serialises from __dict__
        # without reloading, so refresh before returning it.
        db.refresh(review)
    except Exception:
        db.rollback()

    return review


@router.get("/mine")
def read_my_reviews(
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    """Only the signed-in guest's own reviews."""
    reviews = (
        db.query(Review)
        .filter(Review.user_id == current_user["user_id"])
        .order_by(Review.id.desc())
        .all()
    )

    if not reviews:
        reviews = (
            db.query(Review)
            .filter(
                Review.customer_name == current_user["user_name"],
                Review.user_id.is_(None),
            )
            .order_by(Review.id.desc())
            .all()
        )

    return reviews


@router.get("/summary")
def review_summary(db: Session = Depends(get_db)):
    """Aggregated sentiment for the admin dashboard."""
    return summarize_reviews(db.query(Review).all())


# Moderation is an admin action, so deletion requires an admin token.
@router.delete("/{review_id}")
def delete_review(
    review_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    review = db.query(Review).filter(Review.id == review_id).first()

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    db.delete(review)
    db.commit()

    return {"message": "Review deleted successfully"}
