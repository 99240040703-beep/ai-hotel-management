from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

try:
    from database import get_db
    from middleware.auth import require_admin
except (ImportError, ValueError):
    from ..database import get_db
    from ..middleware.auth import require_admin
from crud import get_all_users, create_user
from schemas import UserCreate

router = APIRouter(
    prefix="/users",
    tags=["Users"]
)


@router.get("/")
def read_users(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    return get_all_users(db)


@router.post("/")
def add_user(
    item: UserCreate,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    return create_user(db, item)
